"""Issue classifier — two-stage: rules first, then LLM fallback.

Stage 1 (always): keyword matching on title/body/labels.
Stage 2 (optional): LLM call when rules are uncertain (UNKNOWN or confidence ≤ 0.6).

Callers use the sync ``classify()`` for pure rules, or ``async_classify()``
to get LLM-enhanced results when available.
"""

from __future__ import annotations

from collections import Counter
import json
import re

from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.issue import IssueCategory, IssueClassification
from app.schemas.repository import CategorySummary

# Keywords are grouped by category. Label matches get double weight.
KEYWORDS: dict[IssueCategory, set[str]] = {
    IssueCategory.BUG: {"bug", "crash", "error", "exception", "fail", "broken", "traceback", "报错", "崩溃", "缺陷"},
    IssueCategory.FEATURE_REQUEST: {"feature", "enhancement", "proposal", "request", "support", "功能", "建议", "需求"},
    IssueCategory.QUESTION: {"question", "how to", "help", "usage", "why", "what", "咨询", "怎么", "如何", "疑问"},
    IssueCategory.DOCUMENTATION: {"doc", "docs", "documentation", "readme", "guide", "文档", "说明"},
    IssueCategory.DUPLICATE: {"duplicate", "duplicated", "same as", "重复"},
    IssueCategory.INFO_NEEDED: {"reproduce", "minimal", "more info", "missing", "insufficient", "复现", "信息不足", "缺少"},
    IssueCategory.INVALID: {"invalid", "wontfix", "not planned", "无效"},
    IssueCategory.MAINTENANCE: {"refactor", "cleanup", "chore", "deps", "dependency", "维护", "依赖"},
}

# Suggested action text returned alongside every classification.
SUGGESTED_ACTIONS: dict[IssueCategory, str] = {
    IssueCategory.BUG: "Ask for reproduction details if needed, then locate impacted modules and create a fix plan.",
    IssueCategory.FEATURE_REQUEST: "Clarify expected behavior, scope the request, and decide whether it fits the roadmap.",
    IssueCategory.QUESTION: "Answer from README, docs, and code examples; consider turning repeated questions into FAQ.",
    IssueCategory.DOCUMENTATION: "Check related docs and prepare a documentation update or guidance reply.",
    IssueCategory.DUPLICATE: "Link the canonical issue and close or merge discussion after maintainer confirmation.",
    IssueCategory.INFO_NEEDED: "Request environment, version, reproduction steps, logs, and expected versus actual behavior.",
    IssueCategory.INVALID: "Explain why the issue is outside scope or not actionable, then close if appropriate.",
    IssueCategory.MAINTENANCE: "Route to dependency, refactor, or housekeeping workflow.",
    IssueCategory.UNKNOWN: "Triage manually or send to an LLM-based classifier once that module is enabled.",
}

# Categories that benefit most from LLM disambiguation.
_LLM_THRESHOLD = 0.6


class IssueClassifier:
    """Classify an issue into an ``IssueCategory``.

    Usage::

        # Sync: pure rule-based (fast, no LLM needed)
        result = classifier.classify(title="Bug: crash", body="...", labels=["bug"])

        # Async: rules + LLM fallback for uncertain cases
        result = await classifier.async_classify(title="...", body="...", labels=[])
    """

    # ── Sync: rule-based classification ───────────────────────────────

    def classify(self, title: str, body: str | None, labels: list[str]) -> IssueClassification:
        """Score each category by keyword matching and return the top result.

        - Keyword matches in labels score 2×.
        - Empty body adds an ``INFO_NEEDED`` signal.
        - Confidence is ``top_score / total_score``, clamped to ``[0.35, 0.95]``.
        """
        text = " ".join([title, body or "", " ".join(labels)]).lower()
        label_text = " ".join(labels).lower()
        scores: Counter[IssueCategory] = Counter()
        signals: list[str] = []

        for category, keywords in KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    score = 2 if keyword in label_text else 1
                    scores[category] += score
                    signals.append(f"{category.value}:{keyword}")

        # Empty-body boost: issue without a body is likely missing information.
        # When this is the only signal, keep confidence low so the LLM fallback
        # in ``async_classify()`` gets a chance to analyse the issue properly.
        empty_body_signals: list[str] = []
        if not (body and body.strip()) and scores[IssueCategory.INFO_NEEDED] == 0:
            scores[IssueCategory.INFO_NEEDED] += 1
            empty_body_signals = ["info_needed:empty_body"]

        if not scores:
            return IssueClassification(
                category=IssueCategory.UNKNOWN,
                confidence=0.2,
                reason="No strong label, title, or body keyword matched the rule classifier.",
                suggested_action=SUGGESTED_ACTIONS[IssueCategory.UNKNOWN],
                signals=[],
            )

        category, score = scores.most_common(1)[0]
        total = sum(scores.values())
        confidence = min(0.95, max(0.35, score / total))
        # If the only signal was the empty-body heuristic, the classifier has
        # no real evidence — drop confidence so the LLM fallback can refine.
        if empty_body_signals and len(scores) == 1:
            confidence = 0.3
            signals.extend(empty_body_signals)
        return IssueClassification(
            category=category,
            confidence=round(confidence, 2),
            reason=f"Matched {score} signal(s) for {category.value}.",
            suggested_action=SUGGESTED_ACTIONS[category],
            signals=signals[:8],
        )

    # ── Async: rules + LLM fallback ───────────────────────────────────

    def __init__(self) -> None:
        self._llm_available = bool(settings.llm_api_key)
        if self._llm_available:
            self._client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_api_base_url,
            )

    async def async_classify(
        self,
        title: str,
        body: str | None,
        labels: list[str],
    ) -> IssueClassification:
        """Two-stage classification: rules → LLM fallback when uncertain.

        When the rule-based result is UNKNOWN or its confidence is
        ≤``_LLM_THRESHOLD``, and the LLM is configured, the classifier
        calls an OpenAI-compatible model to re-classify the issue.
        """
        # Stage 1: rules.
        rule_result = self.classify(title, body, labels)

        # Stage 2: LLM fallback if rules are uncertain.
        needs_llm = (
            self._llm_available
            and (
                rule_result.category == IssueCategory.UNKNOWN
                or rule_result.confidence <= _LLM_THRESHOLD
            )
        )
        if not needs_llm:
            return rule_result

        llm_result = await self._llm_classify(title, body, labels)
        return llm_result if llm_result is not None else rule_result

    async def _llm_classify(
        self,
        title: str,
        body: str | None,
        labels: list[str],
    ) -> IssueClassification | None:
        """Ask the LLM to classify the issue. Returns ``None`` on failure."""
        categories_str = ", ".join(c.value for c in IssueCategory)
        prompt = (
            f"Classify this GitHub issue into exactly one category: {categories_str}.\n\n"
            f"Title: {title}\n"
            f"Body: {body or '(empty)'}\n"
            f"Labels: {', '.join(labels) if labels else '(none)'}\n\n"
            "Respond in JSON only:\n"
            '{"category": "<category>", "confidence": 0.0-1.0, "reason": "<brief reason>", '
            '"signals": ["<key evidence>"]}\n'
            "confidence must be >= 0.5 if you are sure, < 0.5 if uncertain."
        )

        try:
            completion = await self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an issue triage assistant. Classify GitHub issues "
                            "with precision. Respond in JSON only, no markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
        except Exception:
            return None

        raw = (completion.choices[0].message.content or "").strip()
        if not raw:
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        category_str = (data.get("category") or "").strip().lower()
        try:
            category = IssueCategory(category_str)
        except ValueError:
            return None

        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        signals = data.get("signals", [])
        if not isinstance(signals, list):
            signals = []
        signals = [str(s) for s in signals[:8]]

        return IssueClassification(
            category=category,
            confidence=round(confidence, 2),
            reason=data.get("reason", f"LLM classified as {category.value}.") or "",
            suggested_action=SUGGESTED_ACTIONS.get(category, ""),
            signals=signals,
        )

    # ── Summary helper ────────────────────────────────────────────────

    def summarize(self, categories: list[IssueCategory]) -> list[CategorySummary]:
        """Aggregate a list of categories into a sorted summary (most frequent first)."""
        counter = Counter(category.value for category in categories)
        return [CategorySummary(category=category, count=count) for category, count in counter.most_common()]

"""Rule-based issue classifier.

Categorizes GitHub issues into types (BUG, FEATURE_REQUEST, QUESTION, etc.)
using keyword matching on title, body, and labels.
"""

from collections import Counter

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


class IssueClassifier:
    """Classify an issue into an ``IssueCategory`` using keyword scoring."""

    def classify(self, title: str, body: str | None, labels: list[str]) -> IssueClassification:
        """Score each category by keyword matches and return the top result.

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
        if not (body and body.strip()) and scores[IssueCategory.INFO_NEEDED] == 0:
            scores[IssueCategory.INFO_NEEDED] += 1
            signals.append("info_needed:empty_body")

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
        return IssueClassification(
            category=category,
            confidence=round(confidence, 2),
            reason=f"Matched {score} signal(s) for {category.value}.",
            suggested_action=SUGGESTED_ACTIONS[category],
            signals=signals[:8],
        )

    def summarize(self, categories: list[IssueCategory]) -> list[CategorySummary]:
        """Aggregate a list of categories into a sorted summary (most frequent first)."""
        counter = Counter(category.value for category in categories)
        return [CategorySummary(category=category, count=count) for category, count in counter.most_common()]

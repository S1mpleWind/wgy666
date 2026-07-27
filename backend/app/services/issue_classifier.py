"""Issue classifier — two-stage: rules first, then LLM fallback.

Stage 1 (always): keyword matching on title/body/labels.
Stage 2 (optional): LLM call when rules are uncertain (UNKNOWN or confidence ≤ 0.6).

Callers use the sync ``classify()`` for pure rules, or ``async_classify()``
to get LLM-enhanced results when available.

====================================================================
Issue 分类器 —— 两阶段分类：规则匹配 + LLM 兜底
====================================================================

阶段 1（规则匹配，始终执行）：
  基于关键词词典对 Issue 的标题、正文、标签进行匹配打分。
  返回置信度最高的类别及信号列表。

阶段 2（LLM 兜底，可选）：
  当 LLM API 可用时，对规则分类结果置信度低的情况，
  调用 LLM 进行二次判断，以提高分类准确度。

分类类别（IssueCategory）：
  - BUG            缺陷/崩溃报告
  - FEATURE_REQUEST 功能建议/新需求
  - QUESTION       使用咨询/疑问
  - DOCUMENTATION  文档问题
  - DUPLICATE      重复 Issue
  - INFO_NEEDED    信息不足，需要补充
  - INVALID        无效/不在范围内
  - MAINTENANCE    维护/重构/依赖更新
  - UNKNOWN        无法归类（需人工处理）

评分规则：
  - 标签中的关键词命中权重 ×2（标签通常比正文标题更可信）。
  - 正文为空自动增加 INFO_NEEDED 信号。
  - 置信度 = 最高得分 / 总得分，限制在 [0.35, 0.95] 区间内。
  - 仅由空正文触发的信号置信度强制为 0.3（证据不足，需 LLM 二次判断）。

使用方式：
    classifier = IssueClassifier()
    # 同步：纯规则（快速，无需 LLM）
    result = classifier.classify(title="Bug: crash", body="...", labels=["bug"])
    # 异步：规则 + LLM（高置信度时跳过 LLM，低置信度时调用 LLM 增强）
    result = await classifier.async_classify(title="...", body="...", labels=[])
"""

from __future__ import annotations

from collections import Counter
import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.schemas.issue import IssueCategory, IssueClassification
from app.schemas.repository import CategorySummary

# Keywords are grouped by category. Label matches get double weight.
# 每个类别的关键词集合：标签命中权重 ×2
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

# 每个类别的建议操作，随分类结果一起返回给调用方
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

# LLM 二次分类的置信度阈值：规则结果 ≤ 0.6 时触发 LLM 兜底
_LLM_THRESHOLD = 0.6


class IssueClassifier:
    """Classify an issue into an ``IssueCategory``.

    两阶段分类器：
      - classify()       纯规则，同步、零依赖。
      - async_classify() 规则 + LLM 兜底，异步，需要 LLM API。

    Usage::

        # Sync: pure rule-based (fast, no LLM needed)
        result = classifier.classify(title="Bug: crash", body="...", labels=["bug"])

        # Async: rules + LLM fallback for uncertain cases
        result = await classifier.async_classify(title="...", body="...", labels=[])
    """

    # ── Sync: rule-based classification ───────────────────────────────
    # 同步规则分类

    def classify(self, title: str, body: str | None, labels: list[str]) -> IssueClassification:
        """Score each category by keyword matching and return the top result.

        - Keyword matches in labels score 2×.
        - Empty body adds an ``INFO_NEEDED`` signal.
        - Confidence is ``top_score / total_score``, clamped to ``[0.35, 0.95]``.

        步骤：
        1. 将标题、正文、标签拼接为统一文本 → 小写化。
        2. 单独提取标签文本（用于 2× 加权检测）。
        3. 遍历关键词词典，对每个命中累加分数：
             - 标签中命中：+2 分（高权重，标签通常更可靠）。
             - 标题/正文中命中：+1 分。
        4. 正文为空 → 追加 INFO_NEEDED 信号（权重较低）。
        5. 计算置信度 → 返回得分最高的类别。

        Args:
            title:  Issue 标题。
            body:   Issue 正文（可为 None 表示空）。
            labels: 标签列表（如 ``["bug", "triaged"]``）。

        Returns:
            IssueClassification 包含类别、置信度、推理原因等字段。
        """
        text = " ".join([title, body or "", " ".join(labels)]).lower()
        label_text = " ".join(labels).lower()
        scores: Counter[IssueCategory] = Counter()
        signals: list[str] = []

        for category, keywords in KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    # 标签命中权重 ×2，正文/标题命中权重 ×1
                    score = 2 if keyword in label_text else 1
                    scores[category] += score
                    signals.append(f"{category.value}:{keyword}")

        # 空正文提升：没有正文的 issue 大概率信息不足。
        # 但仅当这是唯一信号时，置信度保持较低以便 LLM 兜底有分析机会。
        empty_body_signals: list[str] = []
        if not (body and body.strip()) and scores[IssueCategory.INFO_NEEDED] == 0:
            scores[IssueCategory.INFO_NEEDED] += 1
            empty_body_signals = ["info_needed:empty_body"]

        if not scores:
            # 完全没有任何关键词命中 → 返回 UNKNOWN
            return IssueClassification(
                category=IssueCategory.UNKNOWN,
                confidence=0.2,
                reason="No strong label, title, or body keyword matched the rule classifier.",
                suggested_action=SUGGESTED_ACTIONS[IssueCategory.UNKNOWN],
                signals=[],
            )

        # 取最高分作为分类结果
        category, score = scores.most_common(1)[0]
        total = sum(scores.values())
        # 置信度 = 最高分占总分的比例，限制在 [0.35, 0.95]
        confidence = min(0.95, max(0.35, score / total))
        # 如果空正文启发式是唯一信号，置信度应为 0.3，便于 LLM 兜底
        if empty_body_signals and len(scores) == 1:
            confidence = 0.3
            signals.extend(empty_body_signals)
        return IssueClassification(
            category=category,
            confidence=round(confidence, 2),
            reason=f"Matched {score} signal(s) for {category.value}.",
            suggested_action=SUGGESTED_ACTIONS[category],
            signals=signals[:8],  # 最多保留 8 个信号
        )

    # ── Async: rules + LLM fallback ───────────────────────────────────
    # 异步 + LLM 兜底

    def __init__(self) -> None:
        """初始化 LLM 客户端（如果配置了 API Key）。"""
        self._cfg = get_effective_config()
        self._llm_available = bool(self._cfg.llm_api_key)
        if self._llm_available:
            self._client = AsyncOpenAI(
                api_key=self._cfg.llm_api_key,
                base_url=self._cfg.llm_api_base_url,
            )

    async def async_classify(
        self,
        title: str,
        body: str | None,
        labels: list[str],
    ) -> IssueClassification:
        """Use rules first and call the LLM only for uncertain results."""
        rule_result = self.classify(title, body, labels)
        uncertain = (
            rule_result.category == IssueCategory.UNKNOWN
            or rule_result.confidence <= _LLM_THRESHOLD
        )
        if self._llm_available and uncertain:
            llm_result = await self._llm_classify(title, body, labels)
            if llm_result is not None:
                return llm_result

        return rule_result

    async def _llm_classify(
        self,
        title: str,
        body: str | None,
        labels: list[str],
    ) -> IssueClassification | None:
        """Ask the LLM to classify the issue. Returns ``None`` on failure.

        LLM 分类调用：

        构造结构化的 Prompt → 调用 LLM → 解析 JSON 返回结果。

        返回 None 的情况：
          - LLM API 调用失败（网络问题、API 错误等）。
          - LLM 返回的 JSON 无法解析。
          - LLM 返回的类别字符串不是有效的 IssueCategory。

        Args:
            title:  Issue 标题。
            body:   Issue 正文。
            labels: 标签列表。

        Returns:
            IssueClassification 或 None（失败时）。
        """
        categories_str = ", ".join(c.value for c in IssueCategory)
        prompt = (
            f"Classify this GitHub issue into exactly one category: {categories_str}.\n\n"
            f"Title: {title}\n"
            f"Body: {body or '(empty)'}\n"
            f"Labels: {', '.join(labels) if labels else '(none)'}\n\n"
            "Respond in JSON only:\n"
            '{"category": "<category>", "confidence": 0.0-1.0, '
            '"reason": "<brief reason, include duplicate issue# if applicable>", '
            '"signals": ["<key evidence>"], '
            '"auto_reply_draft": "(if this is a question, info_needed, duplicate, '
            'or documentation issue, write a draft reply in Chinese; '
            'for duplicate, mention which issue it duplicates); '
            'otherwise leave empty"}\n'
            "confidence must be >= 0.5 if you are sure, < 0.5 if uncertain."
        )

        try:
            completion = await self._client.chat.completions.create(
                model=self._cfg.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an issue triage assistant for an open-source project. "
                            "Classify GitHub issues with precision. "
                            "For non-code issues (question, info_needed, duplicate, documentation), "
                            "write a helpful auto-reply draft in Chinese. "
                            "Respond in JSON only, no markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,   # 低温度保证相对一致的分类结果
                max_tokens=500,    # 限制输出长度避免浪费 token
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("LLM classification failed: %s", exc)
            return None

        raw = (completion.choices[0].message.content or "").strip()
        if not raw:
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        # 验证并标准化类别的字符串
        category_str = (data.get("category") or "").strip().lower()
        try:
            category = IssueCategory(category_str)
        except ValueError:
            return None  # 无效类别，返回 None 回退到规则

        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        signals = data.get("signals", [])
        if not isinstance(signals, list):
            signals = []
        signals = [str(s) for s in signals[:8]]

        auto_reply_draft = str(data["auto_reply_draft"]).strip() if data.get("auto_reply_draft") else None

        return IssueClassification(
            category=category,
            confidence=round(confidence, 2),
            reason=data.get("reason", f"LLM classified as {category.value}.") or "",
            suggested_action=SUGGESTED_ACTIONS.get(category, ""),
            signals=signals,
            auto_reply_draft=auto_reply_draft,
        )

    # ── Summary helper ────────────────────────────────────────────────
    # 摘要辅助方法

    def summarize(self, categories: list[IssueCategory]) -> list[CategorySummary]:
        """Aggregate a list of categories into a sorted summary (most frequent first).

        将多个分类结果聚合为频率统计摘要，按出现次数降序排列。

        Args:
            categories: Issue 类别列表。

        Returns:
            CategorySummary 列表（按出现次数降序）。
        """
        counter = Counter(category.value for category in categories)
        return [CategorySummary(category=category, count=count) for category, count in counter.most_common()]

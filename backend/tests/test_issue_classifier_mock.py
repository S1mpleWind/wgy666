"""
进阶要求 — Mock 单元测试（覆盖率 100%）

测试目标：IssueClassifier.async_classify() 的 LLM 兜底逻辑

Mock 对象：self._client.chat.completions.create（外部 LLM API 调用）

测试覆盖：
  1. LLM 返回有效 JSON → 返回 LLM 分类结果
  2. LLM 抛出异常 → 回退到规则分类
  3. LLM 返回无效 JSON → 回退到规则分类
  4. LLM 返回无效类别字符串 → 回退到规则分类
  5. 验证 LLM 被调用了正确的参数（prompt 包含 issue 信息）
  6. LLM 的 auto_reply_draft 字段保留
  7. 规则分类：无关键词命中 → UNKNOWN
  8. 规则分类：空正文触发 INFO_NEEDED + 置信度 0.3
  9. LLM 返回空响应 → 回退到规则
  10. LLM 返回非列表 signals → 兼容处理
  11. summarize() 辅助方法
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.issue_classifier import IssueClassifier
from app.schemas.issue import IssueCategory, IssueClassification


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def classifier():
    """每次测试创建新的分类器实例。"""
    return IssueClassifier()


# ---------------------------------------------------------------------------
# 辅助函数：构造 LLM 返回的 Mock 响应
# ---------------------------------------------------------------------------

def _mock_llm_response(content: str):
    """构造一个模拟的 LLM chat completion 响应。

    Args:
        content: LLM 返回的 JSON 字符串

    Returns:
        MagicMock 对象，模拟 OpenAI 的 chat.completions.create() 返回值
    """
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Test 1: LLM 返回有效 JSON → 应返回 LLM 的分类结果
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_returns_valid_json_uses_llm_result(classifier):
    """
    Mock LLM 返回一个有效的 JSON 分类结果。
    验证 async_classify() 返回的是 LLM 的结果（而非规则结果）。
    """
    # 确保 LLM 可用
    with patch.object(classifier, "_llm_available", True):
        # Mock LLM API 返回 bug 类别
        mock_resp = _mock_llm_response(json.dumps({
            "category": "bug",
            "confidence": 0.92,
            "reason": "Title contains 'exception' and body has stack trace.",
            "signals": ["keyword:exception", "stack_trace"],
            "auto_reply_draft": "",
        }))
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await classifier.async_classify(
                title="NullPointerException in login module",
                body="java.lang.NullPointerException at com.app.LoginController.java:42",
                labels=["bug"],
            )

    # 验证：应该返回 LLM 的结果（置信度 0.92 匹配 LLM 返回的值）
    assert result.category == IssueCategory.BUG
    assert result.confidence == 0.92
    assert result.reason == "Title contains 'exception' and body has stack trace."


# ---------------------------------------------------------------------------
# Test 2: LLM 抛出异常 → 应回退到规则分类
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_exception_falls_back_to_rules(classifier):
    """
    Mock LLM API 调用抛出异常（网络超时）。
    验证 async_classify() 回退到纯规则分类。
    """
    with patch.object(classifier, "_llm_available", True):
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(side_effect=Exception("LLM API timeout")),
        ):
            result = await classifier.async_classify(
                title="Bug: app crashes on startup",
                body="With traceback error",
                labels=["bug"],
            )

    # 回退到规则：标题含 "bug" 和 "crash" → BUG
    assert result.category == IssueCategory.BUG
    # 规则置信度在 [0.35, 0.95] 范围内
    assert 0.35 <= result.confidence <= 0.95


# ---------------------------------------------------------------------------
# Test 3: LLM 返回不可解析的 JSON → 应回退到规则分类
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_invalid_json_falls_back_to_rules(classifier):
    """
    Mock LLM 返回一段非 JSON 的普通文本。
    验证 _llm_classify() 解析失败后返回 None，async_classify() 回退到规则。
    """
    with patch.object(classifier, "_llm_available", True):
        mock_resp = _mock_llm_response("I think this is a bug, but I'm not sure.")
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await classifier.async_classify(
                title="Something is broken",
                body="It doesn't work",
                labels=[],
            )

    # 规则兜底：body 为空，没有被明确分类
    assert result is not None
    # 不能是 None 就行
    assert isinstance(result, IssueClassification)


# ---------------------------------------------------------------------------
# Test 4: LLM 返回的类别字符串无效 → 应回退到规则分类
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_invalid_category_falls_back_to_rules(classifier):
    """
    Mock LLM 返回的 JSON 中 category 字段不在 IssueCategory 枚举中。
    验证 _llm_classify() 因 ValueError 返回 None，回退到规则。
    """
    with patch.object(classifier, "_llm_available", True):
        mock_resp = _mock_llm_response(json.dumps({
            "category": "critical_security_vulnerability",  # 无效类别
            "confidence": 0.95,
            "reason": "Security issue.",
            "signals": ["security"],
            "auto_reply_draft": "",
        }))
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await classifier.async_classify(
                title="Security bug: password leak",
                body="Credentials exposed in logs",
                labels=["bug"],
            )

    # 无效类别 → 回退到规则 → bug 关键词命中
    assert result.category == IssueCategory.BUG


# ---------------------------------------------------------------------------
# Test 5: 验证 LLM 被调用时传入了正确的 prompt 参数
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_called_with_correct_prompt(classifier):
    """
    验证 async_classify() 确实调用了 LLM API，
    且 prompt 中包含 issue 的标题、正文和标签信息。
    """
    with patch.object(classifier, "_llm_available", True):
        mock_create = AsyncMock(return_value=_mock_llm_response(json.dumps({
            "category": "question",
            "confidence": 0.85,
            "reason": "User is asking how to use the tool.",
            "signals": ["how_to"],
            "auto_reply_draft": "请参考 README 中的安装说明...",
        })))
        with patch.object(
            classifier._client.chat.completions, "create",
            new=mock_create,
        ):
            await classifier.async_classify(
                title="How to install this project?",
                body="I followed the steps but got an error.",
                labels=["question"],
            )

    # 验证 LLM 被调用了 1 次
    mock_create.assert_awaited_once()

    # 验证参数
    _, kwargs = mock_create.await_args
    assert "model" in kwargs, "缺少 model 参数"
    assert "messages" in kwargs, "缺少 messages 参数"

    messages_text = str(kwargs["messages"])
    assert "How to install this project?" in messages_text, "prompt 中缺少标题"
    assert "I followed the steps" in messages_text, "prompt 中缺少正文"
    assert "question" in messages_text, "prompt 中缺标签"


# ---------------------------------------------------------------------------
# Test 6: LLM 返回的 auto_reply_draft 应被保留
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_auto_reply_draft_is_preserved(classifier):
    """
    Mock LLM 返回的 auto_reply_draft 字段应出现在最终分类结果中。
    """
    with patch.object(classifier, "_llm_available", True):
        mock_resp = _mock_llm_response(json.dumps({
            "category": "question",
            "confidence": 0.9,
            "reason": "User needs help.",
            "signals": ["help"],
            "auto_reply_draft": "感谢您的提问！请参考以下步骤：\n1. 执行 pip install\n2. 运行示例代码",
        }))
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await classifier.async_classify(
                title="How to get started?",
                body=None,
                labels=[],
            )

    assert result.auto_reply_draft is not None
    assert "pip install" in result.auto_reply_draft


# ---------------------------------------------------------------------------
# Test 7: 规则分类 — 无关键词命中 → UNKNOWN（覆盖 classify() 的 UNKNOWN 分支）
# ---------------------------------------------------------------------------

def test_classify_no_keywords_returns_unknown(classifier):
    """
    标题和正文都不含任何关键词，也没有标签。
    验证 classify() 返回 UNKNOWN 类型。
    """
    result = classifier.classify(
        title="abcdefghijklmn",
        body="This is completely random text with no matching keywords",
        labels=[],
    )

    assert result.category == IssueCategory.UNKNOWN
    assert result.confidence == 0.2
    assert result.signals == []


# ---------------------------------------------------------------------------
# Test 8: 规则分类 — 空正文触发 INFO_NEEDED + 置信度 0.3（覆盖 lines 147-148, 167-168）
# ---------------------------------------------------------------------------

def test_classify_empty_body_triggers_info_needed_with_low_confidence(classifier):
    """
    正文为空、标题不含任何关键词时：
      - 空正文启发式触发 → INFO_NEEDED 加 1 分（lines 147-148）
      - 这是唯一的信号 → 置信度强制设为 0.3（lines 167-168）
    """
    result = classifier.classify(
        title="nobody home here",
        body=None,
        labels=[],
    )

    assert result.category == IssueCategory.INFO_NEEDED
    assert result.confidence == 0.3
    assert "info_needed:empty_body" in result.signals


# ---------------------------------------------------------------------------
# Test 9: LLM 返回空响应 → 回退到规则（覆盖 _llm_classify line 271）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_returns_empty_response_falls_back_to_rules(classifier):
    """
    Mock LLM 返回 content 为 None（空响应）。
    验证 _llm_classify() 在 line 271 处返回 None，
    async_classify() 回退到规则分类。
    """
    with patch.object(classifier, "_llm_available", True):
        mock_resp = _mock_llm_response(content=None)
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await classifier.async_classify(
                title="Bug: null pointer",
                body="NPE in production",
                labels=["bug"],
            )

    # LLM 返回空 → 规则兜底
    assert result is not None
    assert isinstance(result, IssueClassification)
    # 规则命中 bug 关键词
    assert result.category == IssueCategory.BUG


# ---------------------------------------------------------------------------
# Test 10: LLM 返回的 signals 不是列表 → 兼容处理（覆盖 _llm_classify line 288）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_signals_not_a_list_handled_gracefully(classifier):
    """
    Mock LLM 返回的 JSON 中 signals 字段是字符串而非列表。
    验证 _llm_classify() 将非列表 signals 转为空列表（line 288），
    不抛出异常。
    """
    with patch.object(classifier, "_llm_available", True):
        mock_resp = _mock_llm_response(json.dumps({
            "category": "bug",
            "confidence": 0.9,
            "reason": "Bug found.",
            "signals": "just_a_string",  # 不是列表，触发 line 288
            "auto_reply_draft": "",
        }))
        with patch.object(
            classifier._client.chat.completions, "create",
            new=AsyncMock(return_value=mock_resp),
        ):
            result = await classifier.async_classify(
                title="Bug report",
                body="Found a problem",
                labels=["bug"],
            )

    # JSON 解析成功 → 使用 LLM 结果（signals 为空列表）
    assert result.category == IssueCategory.BUG
    assert result.signals == []


# ---------------------------------------------------------------------------
# Test 11: summarize() 辅助方法（覆盖 lines 316-317）
# ---------------------------------------------------------------------------

def test_summarize_aggregates_categories(classifier):
    """
    验证 summarize() 接收 IssueCategory 列表，
    返回按频率排序的 CategorySummary 列表。
    """
    categories = [
        IssueCategory.BUG,
        IssueCategory.BUG,
        IssueCategory.QUESTION,
        IssueCategory.FEATURE_REQUEST,
    ]

    summaries = classifier.summarize(categories)

    assert len(summaries) == 3
    assert summaries[0].category == "bug"
    assert summaries[0].count == 2
    assert summaries[1].category == "question"
    assert summaries[1].count == 1
    assert summaries[2].category == "feature_request"
    assert summaries[2].count == 1

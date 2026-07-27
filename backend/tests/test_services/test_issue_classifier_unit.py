"""Unit and mock tests for the project's issue classification service."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.issue import IssueCategory
from app.services.issue_classifier import IssueClassifier


def test_classify_bug_with_weighted_label_signal() -> None:
    result = IssueClassifier().classify(
        title="Application crash after login",
        body="The request raises an exception.",
        labels=["bug"],
    )

    assert result.category == IssueCategory.BUG
    assert result.confidence == 0.8
    assert "bug:bug" in result.signals


@pytest.mark.parametrize(
    ("title", "body", "labels", "category"),
    [
        ("Please add export support", "A feature request", [], IssueCategory.FEATURE_REQUEST),
        ("How to configure this?", "", [], IssueCategory.QUESTION),
        ("Update README guide", "Documentation typo", [], IssueCategory.DOCUMENTATION),
        ("Same as #12", "duplicate issue", [], IssueCategory.DUPLICATE),
        ("Refactor dependency cleanup", "", [], IssueCategory.MAINTENANCE),
        ("", None, [], IssueCategory.INFO_NEEDED),
        ("wontfix", "invalid request", [], IssueCategory.INVALID),
        ("Unexpected wording", "No matching terms here", [], IssueCategory.UNKNOWN),
    ],
)
def test_classify_covers_rule_categories(
    title: str,
    body: str | None,
    labels: list[str],
    category: IssueCategory,
) -> None:
    result = IssueClassifier().classify(title, body, labels)

    assert result.category == category
    assert 0 <= result.confidence <= 1


def test_empty_body_only_signal_has_low_confidence() -> None:
    result = IssueClassifier().classify("No details", "   ", [])

    assert result.category == IssueCategory.INFO_NEEDED
    assert result.confidence == 0.3
    assert result.signals == ["info_needed:empty_body"]


def test_summarize_sorts_by_frequency() -> None:
    summary = IssueClassifier().summarize(
        [IssueCategory.BUG, IssueCategory.QUESTION, IssueCategory.BUG]
    )

    assert [(item.category, item.count) for item in summary] == [
        (IssueCategory.BUG.value, 2),
        (IssueCategory.QUESTION.value, 1),
    ]


def _classifier_with_mock_client(response_content: str | None) -> IssueClassifier:
    classifier = IssueClassifier()
    classifier._llm_available = True
    classifier._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content=response_content)
                            )
                        ]
                    )
                )
            )
        )
    )
    return classifier


@pytest.mark.asyncio
async def test_async_classify_uses_mocked_llm_response() -> None:
    classifier = _classifier_with_mock_client(
        '{"category":"question","confidence":1.2,'
        '"reason":"需要说明用法","signals":["how to"],'
        '"auto_reply_draft":"请查看文档"}'
    )

    result = await classifier.async_classify("How to use it?", "", [])

    assert result.category == IssueCategory.QUESTION
    assert result.confidence == 1.0
    assert result.auto_reply_draft == "请查看文档"
    classifier._client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("response_content", [None, "not-json", '{"category":"not-valid"}'])
async def test_async_classify_falls_back_for_invalid_mock_response(
    response_content: str | None,
) -> None:
    classifier = _classifier_with_mock_client(response_content)

    result = await classifier.async_classify("Bug: crash", "details", ["bug"])

    assert result.category == IssueCategory.BUG


@pytest.mark.asyncio
async def test_async_classify_falls_back_when_mocked_llm_raises() -> None:
    classifier = _classifier_with_mock_client(None)
    classifier._client.chat.completions.create.side_effect = RuntimeError("offline")

    result = await classifier.async_classify("Feature request", "support this", [])

    assert result.category == IssueCategory.FEATURE_REQUEST

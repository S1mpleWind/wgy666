"""Tests for the two-stage IssueClassifier (rules + LLM fallback)."""

from app.schemas.issue import IssueCategory
from app.services.issue_classifier import IssueClassifier


# ── Rule-based classification (always works, no external deps) ─────────────

def test_classify_bug_by_keyword():
    """Bug keywords in body produce BUG category."""
    result = IssueClassifier().classify(
        title="Unexpected error",
        body="Getting a traceback exception when saving",
        labels=["bug"],
    )
    assert result.category == IssueCategory.BUG
    assert result.confidence >= 0.35


def test_classify_question_by_keyword():
    """Question keywords produce QUESTION category."""
    result = IssueClassifier().classify(
        title="How to install",
        body="I need help with setup",
        labels=["question"],
    )
    assert result.category == IssueCategory.QUESTION


def test_classify_unknown_when_no_match():
    """No matching keywords produces UNKNOWN."""
    result = IssueClassifier().classify(
        title="Random title",
        body="Completely unrelated text with no keywords",
        labels=[],
    )
    assert result.category == IssueCategory.UNKNOWN


def test_classify_empty_body_gets_info_needed():
    """Empty body with no keywords produces INFO_NEEDED."""
    result = IssueClassifier().classify(
        title="Something is not right",
        body=None,
        labels=[],
    )
    assert result.category == IssueCategory.INFO_NEEDED


def test_classify_labels_get_double_weight():
    """Label matches get 2× weight, overriding body-only matches."""
    result = IssueClassifier().classify(
        title="Random title",
        body="This is about documentation",
        labels=["bug"],
    )
    # "bug" label match (2×) beats "documentation" in body (1×).
    assert result.category == IssueCategory.BUG


def test_classify_returns_signals():
    """Classification includes signal list."""
    result = IssueClassifier().classify(
        title="Bug: crash when saving",
        body="Exception error traceback",
        labels=["bug"],
    )
    assert len(result.signals) >= 1
    assert any("bug" in s for s in result.signals)


def test_classify_returns_suggested_action():
    """Classification includes a non-empty suggested_action."""
    result = IssueClassifier().classify(
        title="Bug crash",
        body="Error occurred",
        labels=["bug"],
    )
    assert result.suggested_action
    assert "fix" in result.suggested_action.lower()


# ── Async classification with LLM fallback ────────────────────────────────

def test_async_classify_rules_only_when_confident():
    """When rules are confident (>0.6), async_classify returns rules result."""
    import asyncio

    classifier = IssueClassifier()
    result = asyncio.run(
        classifier.async_classify(
            title="Crash when saving file",
            body="Getting an exception traceback",
            labels=["bug"],
        )
    )
    # Rules should be confident enough → no LLM needed.
    assert result.category == IssueCategory.BUG
    assert result.confidence > 0.6


def test_async_classify_falls_back_to_rules_on_llm_failure():
    """When LLM is not configured, async_classify falls back to rules."""
    import asyncio
    from app.core.config import settings

    old_key = settings.llm_api_key
    settings.llm_api_key = None

    try:
        classifier = IssueClassifier()
        # This should NOT raise — graceful fallback to rules.
        result = asyncio.run(
            classifier.async_classify(
                title="Random title with no keywords",
                body="Completely unrelated",
                labels=[],
            )
        )
        # Falls back to rules → INFO_NEEDED (empty body boost)
        assert result.category in (
            IssueCategory.UNKNOWN, IssueCategory.INFO_NEEDED
        )
    finally:
        settings.llm_api_key = old_key


def test_async_classify_passes_through_confident_rules():
    """async_classify returns the rule result directly when confidence > 0.6."""
    import asyncio

    classifier = IssueClassifier()
    result = asyncio.run(
        classifier.async_classify(
            title="Crash: exception when starting",
            body="Error traceback in logs",
            labels=["bug"],
        )
    )
    assert result.category == IssueCategory.BUG
    assert result.confidence > 0.6

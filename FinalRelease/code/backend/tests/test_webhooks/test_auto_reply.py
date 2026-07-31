"""Tests for the IssueAutoReplyService.

These tests verify the interface contract between the webhook module
and the LLM layer. All tests work without an LLM API key.
"""

import pytest
from app.core.config import settings
from app.webhooks.auto_reply import IssueAutoReplyService


def test_generate_reply_returns_none_when_llm_not_configured():
    """When LLM_API_KEY is unset, generate_reply returns None."""
    old_key = settings.llm_api_key
    settings.llm_api_key = None
    try:
        service = IssueAutoReplyService()
        import asyncio
        result = asyncio.run(
            service.generate_reply(
                owner="fastapi",
                name="fastapi",
                issue_title="How do I add middleware?",
                issue_body="I need to add custom middleware...",
                labels=["question"],
            )
        )
        assert result is None
    finally:
        settings.llm_api_key = old_key


def test_generate_reply_graceful_on_api_failure():
    """When the LLM API call fails (e.g. fake key), returns None gracefully."""
    old_key = settings.llm_api_key
    settings.llm_api_key = "sk-fake-key-that-will-fail"
    try:
        service = IssueAutoReplyService()
        import asyncio
        result = asyncio.run(
            service.generate_reply(
                owner="test",
                name="repo",
                issue_title="Test question",
                issue_body="How do I run tests?",
                labels=["question"],
            )
        )
        # API call fails → exception caught → returns None
        assert result is None
    finally:
        settings.llm_api_key = old_key


def test_propose_fix_pr_returns_none():
    """propose_fix_pr is a stub that always returns None."""
    service = IssueAutoReplyService()
    import asyncio
    result = asyncio.run(
        service.propose_fix_pr(
            owner="o",
            name="r",
            issue_title="Bug",
            issue_body="Fix this",
        )
    )
    assert result is None


def test_service_initialization():
    """Service initializes based on LLM_API_KEY presence."""
    old_key = settings.llm_api_key

    settings.llm_api_key = None
    s1 = IssueAutoReplyService()
    assert s1._llm_available is False

    settings.llm_api_key = "some-key"
    s2 = IssueAutoReplyService()
    assert s2._llm_available is True

    settings.llm_api_key = old_key

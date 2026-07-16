"""Tests for the AutoFixService framework stub."""

from app.services.auto_fix import AutoFixService


def test_fix_issue_returns_unsuccessful():
    """fix_issue returns a non-success result when pipeline is not implemented."""
    import asyncio
    from app.core.config import settings

    old_key = settings.llm_api_key
    settings.llm_api_key = "test-key"
    try:
        service = AutoFixService()
        result = asyncio.run(
            service.fix_issue(
                owner="o",
                name="r",
                issue_number=42,
                issue_title="Bug: crash on login",
                issue_body="Traceback error",
                labels=["bug"],
            )
        )
        assert result.success is False
        assert result.branch_name == "auto-fix/issue-42"
        assert "not yet implemented" in (result.error or "")
    finally:
        settings.llm_api_key = old_key


def test_fix_issue_returns_error_when_no_llm():
    """fix_issue returns error when LLM is not configured."""
    import asyncio
    from app.core.config import settings

    old_key = settings.llm_api_key
    settings.llm_api_key = None
    try:
        service = AutoFixService()
        result = asyncio.run(
            service.fix_issue(
                owner="o",
                name="r",
                issue_number=1,
                issue_title="Bug",
                issue_body=None,
                labels=[],
            )
        )
        assert result.success is False
        assert "not configured" in (result.error or "")
    finally:
        settings.llm_api_key = old_key


def test_fix_proposal_dataclass():
    """FixProposal and FixFileChange dataclasses work as expected."""
    from app.services.auto_fix import FixFileChange, FixProposal

    proposal = FixProposal(
        branch_name="fix/test",
        title="fix: test bug",
        pr_body="Closes #1",
        files=[
            FixFileChange(path="src/main.py", content="fixed", commit_message="fix bug"),
        ],
    )
    assert proposal.branch_name == "fix/test"
    assert proposal.files[0].path == "src/main.py"
    assert proposal.files[0].sha is None

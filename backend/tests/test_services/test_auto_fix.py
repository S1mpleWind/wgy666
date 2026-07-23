"""Tests for the AutoFixService framework stub."""

from app.services.auto_fix import AutoFixService


def test_fix_issue_returns_unsuccessful_when_repository_is_not_synced():
    """fix_issue stops before GitHub mutations when the repository is absent."""
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
        assert result.branch_name is not None
        assert result.branch_name.startswith("auto-fix/issue-42-")
        assert "not synced" in (result.error or "")
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


def test_auto_fix_uses_repository_default_branch(monkeypatch):
    """Existing-file lookup and PR creation use the target default branch."""
    import asyncio
    from datetime import datetime, timezone

    from app.assistant.harness import AgentHarness
    from app.core.config import settings
    from app.schemas.repository import (
        ClassifiedFile,
        FileCategory,
        RepositoryFileContent,
        RepositoryIdentity,
        RepositorySnapshot,
        RepositoryStats,
    )
    from app.storage import repository_store

    snapshot = RepositorySnapshot(
        identity=RepositoryIdentity(
            owner="default-branch-test",
            name="repo",
            full_name="default-branch-test/repo",
            html_url="https://github.com/default-branch-test/repo",
            default_branch="develop",
        ),
        stats=RepositoryStats(primary_language="Python"),
        files=[ClassifiedFile(path="app.py", category=FileCategory.SOURCE, size=10)],
        source_contents=[
            RepositoryFileContent(
                path="app.py",
                category=FileCategory.SOURCE,
                content="print('old')",
                size=12,
            )
        ],
        synced_at=datetime.now(timezone.utc),
    )
    repository_store.save(snapshot)

    async def fake_harness_run(self, messages, snapshot, max_rounds=None):
        return (
            "```json\n"
            '{"title":"fix: update app","pr_body":"Update app safely.",'
            '"files":[{"path":"app.py","content":"print(\\"new\\")",'
            '"commit_message":"fix: update app"}]}\n'
            "```",
            [],
        )

    monkeypatch.setattr(AgentHarness, "run", fake_harness_run)

    calls: dict[str, object] = {}

    class FakeGitHubClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_file_content(self, ref, path, ref_name, max_bytes):
            calls["file_ref"] = ref_name
            return "print('old')", False

        async def _get(self, path, params=None):
            calls["sha_ref"] = params["ref"]
            return {"sha": "old-sha"}

        async def get_repository(self, ref):
            return {"default_branch": "develop"}

        async def get_commits(self, ref, limit):
            return [{"sha": "base-sha"}]

        async def create_branch(self, ref, branch_name, sha):
            calls["branch"] = branch_name

        async def create_or_update_file(self, ref, path, content, commit_message, branch, sha=None):
            calls["updated_sha"] = sha

        async def create_pull_request(self, ref, title, head, base, body):
            calls["pr_base"] = base
            return {"html_url": "https://github.com/default-branch-test/repo/pull/1"}

    monkeypatch.setattr("app.services.auto_fix.GitHubClient", FakeGitHubClient)

    previous_key = settings.llm_api_key
    settings.llm_api_key = "test-key"
    try:
        result = asyncio.run(
            AutoFixService().fix_issue(
                owner="default-branch-test",
                name="repo",
                issue_number=5,
                issue_title="Bug in app",
                issue_body="The app fails",
                labels=["bug"],
            )
        )
    finally:
        settings.llm_api_key = previous_key

    assert result.success is True
    assert result.files_changed == ["app.py"]
    assert calls["file_ref"] == "develop"
    assert calls["sha_ref"] == "develop"
    assert calls["pr_base"] == "develop"
    assert calls["updated_sha"] == "old-sha"
    assert str(calls["branch"]).startswith("auto-fix/issue-5-")

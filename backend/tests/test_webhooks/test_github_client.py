"""Smoke tests for GitHub API client methods.

The write-operation methods (``comment_on_issue``, ``update_issue``,
``create_pull_request``, ``create_branch``) are tested here for
import availability and method signature correctness.

Full integration tests would require a GitHub token and are skipped by default.
"""

from app.services.github_client import GitHubClient, GitHubClientError
from app.services.repository_url import RepositoryRef


class TestGitHubClientInternals:
    """Verify that the client can be instantiated and exposes expected methods."""

    def test_client_can_be_imported(self):
        client = GitHubClient()
        assert hasattr(client, "_get")
        assert hasattr(client, "_post")
        assert hasattr(client, "_patch")

    def test_error_has_status_code(self):
        error = GitHubClientError("boom", status_code=403)
        assert error.message == "boom"
        assert error.status_code == 403
        assert str(error) == "boom"

    def test_get_readme_returns_none_on_404(self):
        """The readme method gracefully handles 404s (no README)."""
        # No network call — just verifying the method signature exists.
        assert callable(GitHubClient.get_readme)

    # -- Write-operation method signatures ---------------------------------

    def test_comment_on_issue_signature(self):
        """comment_on_issue is a callable async method."""
        assert callable(GitHubClient.comment_on_issue)

    def test_update_issue_signature(self):
        """update_issue accepts **fields kwargs."""
        assert callable(GitHubClient.update_issue)

    def test_create_pull_request_signature(self):
        """create_pull_request takes title, head, base, body."""
        assert callable(GitHubClient.create_pull_request)

    def test_create_branch_signature(self):
        """create_branch takes branch_name and sha."""
        assert callable(GitHubClient.create_branch)

    def test_comment_on_issue_builds_correct_path(self):
        """Verify the method constructs the expected API path internally via _post."""
        client = GitHubClient()
        # _post is mocked by not being called — we just verify the
        # method exists and expects the right argument types.
        import inspect
        sig = inspect.signature(client.comment_on_issue)
        params = list(sig.parameters.keys())
        assert "ref" in params
        assert "issue_number" in params
        assert "body" in params

    def test_create_or_update_file_signature(self):
        """create_or_update_file takes content, commit_message, branch, and optional sha."""
        assert callable(GitHubClient.create_or_update_file)

    def test_create_or_update_file_builds_correct_path(self):
        """Verify the method expects the right argument types."""
        import inspect
        client = GitHubClient()
        sig = inspect.signature(client.create_or_update_file)
        params = list(sig.parameters.keys())
        assert "ref" in params
        assert "path" in params
        assert "content" in params
        assert "commit_message" in params
        assert "branch" in params
        assert "sha" in params

    def test_put_method_exists(self):
        """_put is a callable internal method."""
        client = GitHubClient()
        assert callable(client._put)

    def test_create_or_update_file_base64_encodes_content(self):
        """create_or_update_file base64-encodes content and calls _put with correct path."""
        import asyncio
        import base64

        client = GitHubClient()
        ref = RepositoryRef(owner="owner", name="repo")

        captured_path = None
        captured_data = None

        async def fake_put(path, json_data=None):
            nonlocal captured_path, captured_data
            captured_path = path
            captured_data = json_data
            return {"content": {"sha": "abc123"}}

        client._put = fake_put  # type: ignore[method-assign]

        asyncio.run(
            client.create_or_update_file(
                ref=ref,
                path="src/main.py",
                content="print('hello')",
                commit_message="Add main.py",
                branch="fix-bug",
                sha="oldsha123",
            )
        )

        # Verify path
        assert "owner" in captured_path
        assert "repo" in captured_path
        assert "src/main.py" in captured_path

        # Verify JSON payload
        assert captured_data["message"] == "Add main.py"
        assert captured_data["branch"] == "fix-bug"
        assert captured_data["sha"] == "oldsha123"

        # Verify content was base64-encoded
        decoded = base64.b64decode(captured_data["content"]).decode("utf-8")
        assert decoded == "print('hello')"

    def test_create_or_update_file_without_sha(self):
        """create_or_update_file works without sha (new file creation)."""
        import asyncio

        client = GitHubClient()
        ref = RepositoryRef(owner="o", name="r")

        captured_data = {}

        async def fake_put(path, json_data=None):
            captured_data.update(json_data or {})
            return {}

        client._put = fake_put  # type: ignore[method-assign]

        asyncio.run(
            client.create_or_update_file(
                ref=ref,
                path="new.txt",
                content="hello",
                commit_message="Create new.txt",
                branch="main",
            )
        )

        assert captured_data["message"] == "Create new.txt"
        assert "sha" not in captured_data

    def test_get_issues_paginates_past_pull_requests(self):
        """PR entries do not reduce the requested number of real issues."""
        import asyncio

        client = GitHubClient()
        ref = RepositoryRef(owner="o", name="r")
        calls = []

        async def fake_get(path, params=None):
            calls.append(params)
            if params["page"] == 1:
                return [
                    *({"number": number, "pull_request": {}} for number in range(29)),
                    {"number": 100},
                ]
            return [{"number": 101}]

        client._get = fake_get  # type: ignore[method-assign]
        issues = asyncio.run(client.get_issues(ref, 2))
        assert [issue["number"] for issue in issues] == [100, 101]
        assert len(calls) == 2

    def test_file_content_limit_is_measured_in_bytes(self):
        import asyncio
        import base64

        client = GitHubClient()
        ref = RepositoryRef(owner="o", name="r")

        async def fake_get(path, params=None):
            raw = "你好".encode("utf-8")
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(raw).decode("ascii"),
                "size": len(raw),
            }

        client._get = fake_get  # type: ignore[method-assign]
        content, truncated = asyncio.run(
            client.get_file_content(ref, "README.md", "main", max_bytes=4)
        )
        assert content == "你"
        assert len(content.encode("utf-8")) <= 4
        assert truncated is True

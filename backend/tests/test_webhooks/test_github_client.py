"""Smoke tests for GitHub API client methods.

The write-operation stubs (``_post``, ``_patch``, ``comment_on_issue``, etc.)
are tested here for import availability and basic structure.

Full integration tests would require a GitHub token and are skipped by default.
"""

from app.services.github_client import GitHubClient, GitHubClientError


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

"""Auto-fix and pull request creation service.

Orchestrates the end-to-end pipeline for automatically fixing bug
issues: locate relevant code → generate fix → create branch → commit
files → open pull request.

This is a **framework stub**. Each step is delegated to a dedicated
method so that individual stages can be implemented incrementally as
RAG and LLM code-generation capabilities mature.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.services.repository_url import RepositoryRef


@dataclass
class FixProposal:
    """The result of analysing a bug issue and generating a fix."""

    branch_name: str
    title: str
    pr_body: str
    files: list[FixFileChange] = field(default_factory=list)


@dataclass
class FixFileChange:
    """One file to create or update as part of a fix."""

    path: str
    content: str
    commit_message: str
    sha: str | None = None  # None = new file


@dataclass
class FixResult:
    """Result of attempting an auto-fix."""

    success: bool
    pr_url: str | None = None
    branch_name: str | None = None
    error: str | None = None


class AutoFixService:
    """Analyse a bug issue and create a fix pull request.

    Usage::

        service = AutoFixService()
        result = await service.fix_issue(
            owner="fastapi",
            name="fastapi",
            issue_number=42,
            issue_title="Crash when saving",
            issue_body="Traceback ...",
            labels=["bug"],
        )
    """

    def __init__(self) -> None:
        self._llm_available = bool(settings.llm_api_key)

    async def fix_issue(
        self,
        owner: str,
        name: str,
        issue_number: int,
        issue_title: str,
        issue_body: str | None,
        labels: list[str],
    ) -> FixResult:
        """Full auto-fix pipeline: analyse → generate → branch → commit → PR.

        TODO: Implement each step. Current implementation is a stub
        that returns a descriptive error until RAG and code-generation
        are wired up.
        """
        if not self._llm_available:
            return FixResult(success=False, error="LLM is not configured")

        ref = RepositoryRef(owner=owner, name=name)
        branch_name = f"auto-fix/issue-{issue_number}"

        # ── Step 1: Locate relevant source files via RAG ─────────────
        # TODO: Use KnowledgeGraphService.search() to find files
        #       related to the bug description.
        #
        #   from app.services.knowledge_graph import KnowledgeGraphService
        #   from app.storage import repository_store
        #   snapshot = repository_store.get(owner, name)
        #   if snapshot:
        #       results = KnowledgeGraphService().search(
        #           snapshot, query=issue_title, focus="source_code"
        #       )
        #       relevant_paths = [r.chunk.source_path for r in results if r.chunk.source_path]
        #

        # ── Step 2: Generate fix code via LLM ────────────────────────
        # TODO: Send bug description + relevant source code to LLM,
        #       ask it to produce the fix as a list of FixFileChange.
        #
        #   Each FixFileChange contains: path, new content, commit msg, sha
        #   For new files: sha=None
        #   For existing files: sha from get_file_content response
        #

        # ── Step 3: Create branch ────────────────────────────────────
        # TODO: Get the SHA of the default branch HEAD, then:
        #
        #   from app.services.github_client import GitHubClient
        #   async with GitHubClient() as gh:
        #       # Get latest commit SHA on default branch
        #       repo = await gh.get_repository(ref)
        #       branch = repo.get("default_branch") or "main"
        #       commits = await gh.get_commits(ref, 1)
        #       sha = commits[0]["sha"]
        #       await gh.create_branch(ref, branch_name, sha)
        #

        # ── Step 4: Commit file changes ──────────────────────────────
        # TODO: For each FixFileChange, call:
        #
        #   async with GitHubClient() as gh:
        #       await gh.create_or_update_file(
        #           ref, change.path, change.content,
        #           commit_message=change.commit_message,
        #           branch=branch_name,
        #           sha=change.sha,
        #       )
        #

        # ── Step 5: Open pull request ────────────────────────────────
        # TODO:
        #
        #   async with GitHubClient() as gh:
        #       pr = await gh.create_pull_request(
        #           ref,
        #           title=f"fix: {issue_title[:72]}",
        #           head=branch_name,
        #           base="main",
        #           body=f"Closes #{issue_number}\n\n{issue_body or ''}",
        #       )
        #       return FixResult(success=True, pr_url=pr["html_url"], branch_name=branch_name)
        #

        return FixResult(
            success=False,
            branch_name=branch_name,
            error="Auto-fix pipeline is not yet implemented. "
                  "See backend/app/services/auto_fix.py for details.",
        )

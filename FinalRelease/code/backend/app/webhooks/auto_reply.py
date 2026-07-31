"""Issue auto-reply and PR creation service.

Uses the existing LLM infrastructure (same AsyncOpenAI client as
AgentHarness) to generate automatic replies for non-bug issues.
"""

from __future__ import annotations

from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.services.repository_query import RepositoryQueryService
from app.services.usage import tracked_chat_completion


@dataclass
class AutoReplyResult:
    """Result from attempting to generate an automatic reply."""

    reply_text: str
    used_llm: bool
    model: str | None = None


@dataclass
class PullRequestProposal:
    """A proposed PR to fix an issue."""

    branch_name: str
    title: str
    body: str
    changes_summary: str


class IssueAutoReplyService:
    """Generate automatic replies for GitHub Issues using the LLM.

    Usage::

        service = IssueAutoReplyService()
        reply = await service.generate_reply(
            owner="fastapi",
            name="fastapi",
            issue_title="How do I add middleware?",
            issue_body="...",
            labels=["question"],
        )
        if reply:
            # post reply as a GitHub comment
            ...
    """

    def __init__(self) -> None:
        self._cfg = get_effective_config()
        self._llm_available = bool(
            self._cfg.llm_api_key and self._cfg.llm_api_base_url and self._cfg.llm_model
        )
        if self._llm_available:
            self._client = AsyncOpenAI(
                api_key=self._cfg.llm_api_key,
                base_url=self._cfg.llm_api_base_url,
            )
        self._query = RepositoryQueryService()

    async def generate_reply(
        self,
        owner: str,
        name: str,
        issue_title: str,
        issue_body: str | None,
        labels: list[str],
    ) -> AutoReplyResult | None:
        """Generate an automatic reply for a non-bug issue.

        Uses the LLM to understand the issue and generate a helpful
        response. Falls back to ``None`` when the LLM is not configured.
        """
        if not self._llm_available:
            return None

        # Load repo context so the LLM knows what the project is about.
        try:
            snapshot, _ = await self._query.get_snapshot(owner, name, "cache_first")
            repo_context = (
                f"Repository: {snapshot.identity.full_name}\n"
                f"Description: {snapshot.description or 'N/A'}\n"
                f"Primary language: {snapshot.stats.primary_language or 'unknown'}\n"
                f"Stars: {snapshot.stats.stars}  /  Issues: {len(snapshot.issues)}"
            )
        except Exception:
            repo_context = f"Repository: {owner}/{name}"

        labels_str = ", ".join(labels) if labels else "(none)"
        body_str = issue_body or "(no body provided)"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful open-source project maintainer assistant. "
                    "Respond to a GitHub issue with a concise, friendly reply in Chinese. "
                    "Be constructive and informative. If the issue asks for help, "
                    "provide guidance based on common practices. "
                    "If it's a feature request, acknowledge it politely. "
                    "Keep the reply under 200 words."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Issue Context\n\n{repo_context}\n\n"
                    f"**Title**: {issue_title}\n"
                    f"**Body**: {body_str}\n"
                    f"**Labels**: {labels_str}\n\n"
                    f"Generate a reply to this issue as the project maintainer."
                ),
            },
        ]

        try:
            completion = await tracked_chat_completion(
                self._client,
                model=self._cfg.llm_model,
                messages=messages,
                temperature=0.7,
                max_tokens=600,
            )
        except Exception:
            # LLM call failed — return nothing rather than breaking
            return None

        reply_text = (completion.choices[0].message.content or "").strip()
        if not reply_text:
            return None

        return AutoReplyResult(
            reply_text=reply_text,
            used_llm=True,
            model=self._cfg.llm_model,
        )

    # ── PR creation (stub / future) ──────────────────────────────────

    async def propose_fix_pr(
        self,
        owner: str,
        name: str,
        issue_title: str,
        issue_body: str | None,
    ) -> PullRequestProposal | None:
        """Propose a pull request that fixes the given issue.

        TODO(future): Integrate with code analysis and GitHub API to
        create a fix branch, apply changes, and open a PR.  The GitHub
        client already has stub methods:

            await client.create_branch(ref, branch_name, sha)
            await client.create_pull_request(ref, title, head, base, body)
        """
        return None

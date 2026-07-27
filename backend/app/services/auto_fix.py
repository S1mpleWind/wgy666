"""Auto-fix and pull request creation service.

Orchestrates the full pipeline: use AgentHarness to analyse a bug issue →
generate fix → create branch → commit files → open pull request.

Steps ③④⑤ (create branch → commit files → open PR) use the GitHub Contents API.
Steps ①② (RAG locate + LLM fix generation) use AgentHarness with tool-calling.

====================================================================
自动修复 Pull Request 服务
====================================================================

编排完整的自动修复流水线：
  - 使用 AgentHarness 分析 bug issue → 生成修复代码 → 创建分支 → 提交文件 → 打开 PR。
  - 步骤 ③④⑤（创建分支 → 提交文件 → 打开 PR）使用 GitHub Contents API 执行。
  - 步骤 ①②（RAG 定位问题代码 + LLM 生成修复）使用 AgentHarness 调用工具链完成。

模型说明：
  - FixProposal: 分析和生成修复代码后的中间结果，包含分支名、PR 标题、PR 描述、文件变更列表。
  - FixFileChange: 单文件变更描述，可表示新建文件或覆盖已有文件（sha 为 None 表示新建）。
  - FixResult:  自动修复的最终结果，记录是否成功、PR 链接、分支名及错误信息。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.assistant.harness import AgentHarness
from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.services.github_client import GitHubClient, GitHubClientError
from app.services.repository_url import RepositoryRef
from app.storage import repository_store


@dataclass
class FixProposal:
    """The result of analysing a bug issue and generating a fix.

    Attributes:
        branch_name: 新分支名称，例如 ``auto-fix/issue-42``。
        title:       修复 PR 的标题。
        pr_body:     PR 正文，说明修复内容。
        files:       需要修改或新增的文件列表（FixFileChange 列表）。
    """

    branch_name: str
    title: str
    pr_body: str
    files: list[FixFileChange] = field(default_factory=list)


@dataclass
class FixFileChange:
    """One file to create or update as part of a fix.

    Attributes:
        path:          文件在仓库中的相对路径（如 ``src/main.py``）。
        content:       文件的完整新内容（UTF-8 格式）。
        commit_message: 针对该文件的 commit message。
        sha:           文件的当前 SHA 用于更新已有文件；``None`` 表示新建文件。
                       （从 Files API 获取，用于防止覆盖他人的并发修改）
    """

    path: str
    content: str
    commit_message: str
    sha: str | None = None  # None = new file


@dataclass
class FixResult:
    """Result of attempting an auto-fix.

    Attributes:
        success:      修复是否成功。
        pr_url:       成功时指向 PR 的 HTML 链接。
        branch_name:  创建的分支名。
        error:        失败时的错误说明。
    """

    success: bool
    pr_url: str | None = None
    branch_name: str | None = None
    error: str | None = None
    files_changed: list[str] = field(default_factory=list)
    summary: str | None = None


class AutoFixService:
    """Analyse a bug issue and create a fix pull request.

    通过 AgentHarness 调用 LLM，分析 issue 并在仓库中定位问题代码，
    生成修复方案，然后通过 GitHub API 创建分支、提交文件并打开 Pull Request。

    Usage::

        service = AutoFixService()
        result = await service.fix_issue(
            owner="fastapi", name="fastapi",
            issue_number=42,
            issue_title="Crash when saving",
            issue_body="Traceback ...",
            labels=["bug"],
        )
    """

    def __init__(self) -> None:
        # 检查是否配置了 LLM API key，未配置则无法生成修复
        self._llm_available = bool(get_effective_config().llm_api_key)

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

        完整流水线步骤：
            ① 使用 AgentHarness 探索仓库并定位问题文件
            ② LLM 生成修复代码（JSON 格式输出）
            ③ 在 GitHub 上创建新分支
            ④ 逐一提交每个文件的修改
            ⑤ 打开 Pull Request

        Args:
            owner:       仓库所有者。
            name:        仓库名。
            issue_number: 要修复的 issue 编号。
            issue_title:  Issue 标题。
            issue_body:   Issue 正文。
            labels:       Issue 标签列表（用于辅助上下文理解）。

        Returns:
            FixResult 包含成功状态、PR 链接或错误信息。
        """
        if not self._llm_available:
            return FixResult(success=False, error="LLM is not configured")

        ref = RepositoryRef(owner=owner, name=name)

        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[:17]
        branch_name = f"auto-fix/issue-{issue_number}-{suffix}"


        # ── Step ①②: Use AgentHarness to locate files + generate fix ──
        # AgentHarness 通过 RAG 知识图谱搜索 + 文件搜索工具定位相关代码，
        # 然后由 LLM 生成修复方案，以 JSON 格式返回文件变更列表。
        fix_proposal = await self._generate_fix_with_harness(
            owner, name, issue_number, issue_title, issue_body, labels, branch_name,
        )
        if fix_proposal is None or not fix_proposal.files:
            return FixResult(
                success=False,
                branch_name=branch_name,
                error=fix_proposal.pr_body if fix_proposal and fix_proposal.pr_body
                     else "Could not generate fix code.",
            )

        # ── Step ③: Create branch ───────────────────────────────────
        try:
            async with GitHubClient() as gh:
                repo = await gh.get_repository(ref)
                default_branch = repo.get("default_branch") or "main"
                commits = await gh.get_commits(ref, 1)
                if not commits:
                    return FixResult(success=False, error="No commits found on default branch.")
                sha = commits[0]["sha"]
                await gh.create_branch(ref, branch_name, sha)

            # ── Step ④: Commit each file change ─────────────────────────
            async with GitHubClient() as gh:
                for change in fix_proposal.files:
                    await gh.create_or_update_file(
                        ref, change.path, change.content,
                        commit_message=change.commit_message,
                        branch=branch_name,
                        sha=change.sha,
                    )

            # ── Step ⑤: Open pull request ───────────────────────────────
            async with GitHubClient() as gh:
                pr = await gh.create_pull_request(
                    ref,
                    title=fix_proposal.title or f"fix: {issue_title[:72]}",
                    head=branch_name,
                    base=default_branch,
                    body=f"Closes #{issue_number}\n\n{fix_proposal.pr_body}\n\n"
                         f"_🤖 Auto-generated by IssueScope_",
                )
        except GitHubClientError as exc:
            return FixResult(
                success=False,
                branch_name=branch_name,
                error=f"GitHub operation failed: {exc.message}",
                files_changed=[change.path for change in fix_proposal.files],
            )

        files_changed = [change.path for change in fix_proposal.files]
        return FixResult(
            success=True,
            pr_url=pr["html_url"],
            branch_name=branch_name,
            files_changed=files_changed,
            summary=fix_proposal.pr_body,
        )

    # ── Step ①②: AgentHarness-based fix generation ─────────────────────

    async def _generate_fix_with_harness(
        self,
        owner: str,
        name: str,
        issue_number: int,
        issue_title: str,
        issue_body: str | None,
        labels: list[str],
        branch_name: str,
    ) -> FixProposal | None:
        """Use AgentHarness to explore the repo and generate a fix.

        The LLM calls tools (search_files, knowledge_graph_search) to
        understand the issue, then outputs a JSON block with file changes.

        工作流程：
        1. 从 repository_store 获取已同步的仓库快照。
        2. 构造 system prompt，告知 LLM 使用工具探索仓库、定位根因、生成修复。
        3. LLM 调用 search_files / knowledge_graph_search 等工具获取上下文。
        4. LLM 最终输出一个 JSON 块，包含修复后的文件内容。
        5. 解析 JSON → 为每个已有文件查询当前 SHA → 返回 FixProposal。

        Args:
            owner:        仓库所有者。
            name:         仓库名。
            issue_number: Issue 编号。
            issue_title:  Issue 标题。
            issue_body:   Issue 正文。
            labels:       Issue 标签。
            branch_name:  目标分支名。

        Returns:
            FixProposal 或 None（LLM 未能生成有效结果时）。
        """
        # 获取已同步的仓库快照（包含文件树、知识图谱等）；未同步则无法分析
        snapshot = repository_store.get(owner, name)
        if snapshot is None:
            return FixProposal(branch_name=branch_name, title="", pr_body="Repository not synced yet.", files=[])

        ref = RepositoryRef(owner=owner, name=name)
        harness = AgentHarness()
        labels_str = ", ".join(labels) if labels else "(none)"
        body_str = issue_body or "(no body provided)"

        from app.services.memory_service import get_similar_fixes
        similar_fixes = await get_similar_fixes(owner, name, issue_title, issue_body)
        memory_text = ""
        if similar_fixes:
            memory_text = "\n\nPast fixes from this repository:\n" + "\n".join(
                f"- {item['title']}: {item['summary']} (files: {', '.join(item['files']) or 'unknown'})"
                for item in similar_fixes
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a code-fixing assistant for an open-source project. "
                    "A user has reported a bug. Your job is to:\n"
                    "1. Use the available tools to explore the repository and understand the code.\n"
                    "2. Find the root cause of the bug.\n"
                    "3. Generate a fix.\n\n"
                    "After your analysis, output a JSON block at the end of your response:\n"
                    '```json\n'
                    '{\n'
                    '  "title": "fix: short description",\n'
                    '  "pr_body": "explanation of the fix",\n'
                    '  "files": [\n'
                    '    {"path": "src/file.py", "content": "full new file content", '
                    '"commit_message": "fix: what changed"}\n'
                    '  ]\n'
                    '}\n'
                    '```\n'
                    "The JSON must be valid and complete. "
                    "For existing files, include the full updated file content in 'content'. "
                    "I will handle getting the file SHA and committing.\n\n"
                    f"Repository: {snapshot.identity.full_name}\n"
                    f"Default branch: {snapshot.identity.default_branch}"
                    f"{memory_text}\n"
                    "Answer in Chinese."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Bug Report\n\n"
                    f"**Title**: {issue_title}\n"
                    f"**Body**: {body_str}\n"
                    f"**Labels**: {labels_str}\n\n"
                    "Please analyse this bug and generate a fix."
                ),
            },
        ]

        # 调用 AgentHarness 执行工具链（RAG 搜索 + LLM 推理）
        final_text, _ = await harness.run(messages, snapshot)
        if not final_text:
            return None

        # 从 LLM 响应中解析 JSON 块。
        # 策略 1：匹配 ```json ... ``` 形式的代码块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', final_text, re.DOTALL)
        if not json_match:
            # 策略 2（兜底）：在文本中查找任何包含 "files" 字段的 JSON 对象
            # 用于处理 LLM 未正确使用 markdown 代码块的情况
            json_match = re.search(r'(\{.*?"files"\s*:.*?\})', final_text, re.DOTALL)
        if not json_match:
            # 无法解析 JSON，将原始响应截取前 500 字符放入 pr_body 用于人工审核
            return FixProposal(
                branch_name=branch_name, title="",
                pr_body=final_text[:500],
                files=[],
            )

        try:
            data = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            return FixProposal(
                branch_name=branch_name, title="",
                pr_body="Failed to parse fix output.",
                files=[],
            )

        files_raw = data.get("files", [])
        if not files_raw:
            return FixProposal(
                branch_name=branch_name, title=data.get("title", ""),
                pr_body=data.get("pr_body", ""),
                files=[],
            )

        # 为已有文件查询当前 SHA，防止覆盖他人的并发修改。
        # 通过 GitHub Contents API 获取文件元数据中的 SHA。
        async with GitHubClient() as gh:
            files: list[FixFileChange] = []
            for f in files_raw:
                path = f.get("path", "")
                content = f.get("content", "")
                commit_msg = f.get("commit_message", f"fix: {issue_title[:60]}")

                # 尝试获取已有文件的 SHA
                sha = None
                try:
                    existing = await gh.get_file_content(
                        ref, path, snapshot.identity.default_branch, 1,
                    )
                    if existing[0] is not None:
                        # Need SHA from the contents API response.
                        from urllib.parse import quote
                        encoded_path = quote(path, safe="/")
                        try:
                            # 直接通过 _get 访问 Contents API 获取完整元数据
                            payload = await gh._get(
                                f"/repos/{ref.owner}/{ref.name}/contents/{encoded_path}",
                                params={"ref": snapshot.identity.default_branch},
                            )
                            sha = payload.get("sha")
                        except Exception:
                            sha = None
                except Exception:
                    sha = None

                files.append(FixFileChange(
                    path=path, content=content,
                    commit_message=commit_msg, sha=sha,
                ))

        return FixProposal(
            branch_name=branch_name,
            title=data.get("title", f"fix: {issue_title[:72]}"),
            pr_body=data.get("pr_body", issue_title),
            files=files,
        )

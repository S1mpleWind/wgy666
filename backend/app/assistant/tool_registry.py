"""OpenAI tool registry for repository assistant capabilities."""

import json
from typing import Any

from app.assistant.tools import RepositoryAssistantTools, ToolResult
from app.schemas.repository import RepositorySnapshot


FILE_CATEGORIES = [
    "source_code",
    "tests",
    "documentation",
    "configuration",
    "ci_cd",
    "dependency",
    "build",
    "assets",
    "data",
    "other",
]

ISSUE_CATEGORIES = [
    "bug",
    "feature_request",
    "question",
    "documentation",
    "duplicate",
    "info_needed",
    "invalid",
    "maintenance",
    "unknown",
]


class RepositoryToolRegistry:
    """Expose repository query capabilities as OpenAI-compatible tools."""

    def __init__(self) -> None:
        self.tools = RepositoryAssistantTools()

    def openai_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in Chat Completions format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "repo_overview",
                    "description": "Get repository metadata, language, stars, forks, issue counts, file counts, and sync time.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "project_structure",
                    "description": "Analyze repository structure, stack, top directories, entry candidates, tests, docs, and dependencies.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "Search synced repository files by path substring and/or file category.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Optional path substring to search for."},
                            "category": {
                                "type": "string",
                                "enum": FILE_CATEGORIES,
                                "description": "Optional file category filter.",
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_issues",
                    "description": "List synced GitHub issues, optionally filtered by issue category or state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ISSUE_CATEGORIES,
                                "description": "Optional issue classification category.",
                            },
                            "state": {"type": "string", "enum": ["open", "closed"], "description": "Optional GitHub issue state."},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "readme_lookup",
                    "description": "Inspect README content, optionally by keyword such as install, run, test, usage, or config.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Optional README keyword to look up."},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "recent_activity",
                    "description": "Get recent commits and pull requests from synced repository data.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
        ]

    def execute(self, name: str, raw_arguments: str | dict[str, Any] | None, snapshot: RepositorySnapshot) -> ToolResult:
        """Execute a registered tool against the current repository snapshot."""
        arguments = self._parse_arguments(raw_arguments)

        if name == "repo_overview":
            return self.tools.overview(snapshot)
        if name == "project_structure":
            return self.tools.project_structure(snapshot)
        if name == "search_files":
            return self.tools.search_files(
                snapshot,
                query=arguments.get("query"),
                category=arguments.get("category"),
            )
        if name == "list_issues":
            return self.tools.list_issues(
                snapshot,
                category=arguments.get("category"),
                state=arguments.get("state"),
            )
        if name == "readme_lookup":
            return self.tools.readme_lookup(snapshot, query=arguments.get("query"))
        if name == "recent_activity":
            return self.tools.recent_activity(snapshot)

        raise ValueError(f"Unknown assistant tool: {name}")

    def _parse_arguments(self, raw_arguments: str | dict[str, Any] | None) -> dict[str, Any]:
        if raw_arguments is None:
            return {}
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not raw_arguments.strip():
            return {}
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must decode to an object.")
        return parsed

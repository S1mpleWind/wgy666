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

KNOWLEDGE_FOCUS = [
    "overview",
    "structure",
    "modules",
    "dependencies",
    "tests",
    "source_code",
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
                    "name": "knowledge_graph_search",
                    "description": "Search the graph-enhanced RAG knowledge base for directory structure, module boundaries, dependency manifests, and test scripts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Question or keywords to search in graph RAG chunks."},
                            "focus": {
                                "type": "string",
                                "enum": KNOWLEDGE_FOCUS,
                                "description": "Optional area to prioritize.",
                            },
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
            self._function("read_file", "Read indexed source code with optional 1-based line range.", {
                "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1},
            }, ["path"]),
            self._function("read_source_context", "Read indexed source around a 1-based line number.", {
                "path": {"type": "string"}, "line": {"type": "integer", "minimum": 1}, "before": {"type": "integer", "minimum": 0}, "after": {"type": "integer", "minimum": 0},
            }, ["path", "line"]),
            self._function("grep_code", "Search indexed source text or a regular expression.", {
                "pattern": {"type": "string"}, "path": {"type": "string"}, "regex": {"type": "boolean"}, "file_type": {"type": "string"},
            }, ["pattern"]),
            self._function("find_symbol_definition", "Find likely function, class, or variable definitions in indexed source.", {
                "symbol": {"type": "string"}, "path": {"type": "string"},
            }, ["symbol"]),
            self._function("find_symbol_references", "Find source lines that reference a symbol.", {
                "symbol": {"type": "string"}, "path": {"type": "string"},
            }, ["symbol"]),
            self._function("vector_search", "Run semantic search over repository knowledge chunks.", {
                "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}, "filters": {"type": "object"},
            }, ["query"]),
            self._function("resolve_source_path", "Resolve a RAG source_path to an indexed repository file.", {
                "source_path": {"type": "string"},
            }, ["source_path"]),
            self._function("embedding_status", "Report the configured embedding backend and vector dimensions.", {}),
        ]

    def _function(self, name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object", "properties": properties,
                    "required": required or [], "additionalProperties": False,
                },
            },
        }

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
        if name == "knowledge_graph_search":
            return self.tools.knowledge_graph_search(
                snapshot,
                query=arguments.get("query"),
                focus=arguments.get("focus"),
            )
        if name == "recent_activity":
            return self.tools.recent_activity(snapshot)
        if name == "read_file":
            return self.tools.read_file(snapshot, arguments["path"], arguments.get("start_line"), arguments.get("end_line"))
        if name == "read_source_context":
            return self.tools.read_source_context(snapshot, arguments["path"], arguments["line"], arguments.get("before", 5), arguments.get("after", 5))
        if name == "grep_code":
            return self.tools.grep_code(snapshot, arguments["pattern"], arguments.get("path"), arguments.get("regex", False), arguments.get("file_type"))
        if name == "find_symbol_definition":
            return self.tools.find_symbol(snapshot, arguments["symbol"], False, arguments.get("path"))
        if name == "find_symbol_references":
            return self.tools.find_symbol(snapshot, arguments["symbol"], True, arguments.get("path"))
        if name == "vector_search":
            return self.tools.vector_search(snapshot, arguments["query"], arguments.get("limit", 5), arguments.get("filters"))
        if name == "resolve_source_path":
            return self.tools.resolve_source_path(snapshot, arguments["source_path"])
        if name == "embedding_status":
            return self.tools.embedding_status(snapshot)

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

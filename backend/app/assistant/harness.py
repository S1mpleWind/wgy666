"""OpenAI SDK based repository assistant harness.

Harness runs a tool-calling loop: LLM decides which tools to call → executes
them → feeds results back to LLM → repeats until LLM gives a final answer.

``answer()`` wraps this loop for the interactive chat panel (frontend).
``run()`` is the raw loop for backend services (auto-reply, auto-fix).
"""

import json
from typing import Any

from openai import APIError, AsyncOpenAI, BadRequestError, OpenAIError

from app.assistant.tool_registry import RepositoryToolRegistry
from app.assistant.tools import ToolResult, merge_citations
from app.core.config import settings
from app.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from app.schemas.repository import RepositorySnapshot
from app.services.repository_query import RepositoryQueryService


class AgentHarnessError(Exception):
    """Raised when the assistant cannot complete a chat request."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AgentHarness:
    """OpenAI-compatible tool-calling loop.

    Two entry points:
    - ``answer(request)`` — interactive Q&A, returns structured response
    - ``run(messages, snapshot)`` — raw loop, returns plain text
    """

    def __init__(self) -> None:
        self.query = RepositoryQueryService()
        self.registry = RepositoryToolRegistry()
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key or "missing-key",
            base_url=settings.llm_api_base_url,
        )

    # ── Public API ───────────────────────────────────────────────────

    async def answer(self, request: AssistantChatRequest) -> AssistantChatResponse:
        """Interactive Q&A — builds context from request, returns structured response."""
        if not settings.llm_api_key:
            raise AgentHarnessError("LLM_API_KEY is not configured.", status_code=503)

        snapshot, used_cached_data = await self.query.get_snapshot(
            request.owner, request.name, request.freshness,
        )
        messages = self._build_initial_messages(
            request, snapshot.identity.full_name, used_cached_data,
        )

        # Delegate the tool loop to run().
        final_text, tool_results = await self.run(messages, snapshot)

        return AssistantChatResponse(
            answer=final_text or "模型没有返回可用回答。",
            repository=snapshot.identity.full_name,
            used_cached_data=used_cached_data,
            tool_calls=[result.call for result in tool_results],
            citations=merge_citations(tool_results),
        )

    async def run(
        self,
        messages: list[dict[str, Any]],
        snapshot: RepositorySnapshot,
        max_rounds: int | None = None,
    ) -> tuple[str, list[ToolResult]]:
        """Run the tool-calling loop with pre-built messages.

        Args:
            messages: Initial message list (system + user prompts).
            snapshot: Repository snapshot for tool execution.
            max_rounds: Max tool-calling iterations (default from config).

        Returns:
            (final_answer_text, list_of_tool_results)
        """
        max_rounds = max_rounds or max(1, settings.assistant_max_tool_rounds)
        tool_results: list[ToolResult] = []

        for round_index in range(max_rounds):
            # ── Call LLM ─────────────────────────────────────────────
            try:
                completion = await self.client.chat.completions.create(
                    model=settings.llm_model,
                    messages=messages,
                    tools=self.registry.openai_tools(),
                    tool_choice="auto",
                )
            except BadRequestError as exc:
                raise AgentHarnessError(
                    f"LLM tool-calling request was rejected: {exc.message}",
                ) from exc
            except (APIError, OpenAIError) as exc:
                raise AgentHarnessError(f"LLM request failed: {exc}") from exc

            assistant_message = completion.choices[0].message
            tool_calls = assistant_message.tool_calls or []

            # ── LLM answered directly (no tools needed) → done ──────
            if not tool_calls:
                return (assistant_message.content or ""), tool_results

            # ── Execute tools and feed results back ──────────────────
            messages.append(assistant_message.model_dump(exclude_none=True))

            for tool_call in tool_calls:
                result = self.registry.execute(
                    tool_call.function.name,
                    tool_call.function.arguments,
                    snapshot,
                )
                tool_results.append(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": self._tool_result_content(result),
                })

            # ── Force final answer if we've hit the round limit ──────
            if round_index == max_rounds - 1:
                messages.append({
                    "role": "system",
                    "content": (
                        "The maximum number of tool rounds has been reached. "
                        "Give the best possible final answer using only the "
                        "tool results already available. If the evidence is "
                        "insufficient, say what is missing."
                    ),
                })

        # ── Final LLM call after tool rounds exhausted ───────────────
        try:
            final = await self.client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
            )
        except (APIError, OpenAIError) as exc:
            raise AgentHarnessError(f"LLM final-answer request failed: {exc}") from exc

        return (final.choices[0].message.content or ""), tool_results

    # ── Internal helpers ─────────────────────────────────────────────

    def _build_initial_messages(
        self,
        request: AssistantChatRequest,
        repository: str,
        used_cached_data: bool,
    ) -> list[dict[str, Any]]:
        """Build the initial message array for a chat request."""
        freshness = "cached repository state" if used_cached_data else "freshly synced repository state"
        history = [
            {"role": message.role, "content": message.content}
            for message in request.history[-6:]
        ]
        return [
            {
                "role": "system",
                "content": (
                    "You are a repository analysis agent for a GitHub issue analysis platform. "
                    "Answer in Chinese unless the user asks otherwise. "
                    "For repository-specific questions, call one or more provided tools before answering. "
                    "Use only tool results as factual evidence. Do not invent files, issues, commands, or repository facts. "
                    "When tool results are insufficient, say what is missing."
                ),
            },
            *history,
            {
                "role": "user",
                "content": (
                    f"Repository: {repository}\n"
                    f"Data freshness: {freshness}\n"
                    f"Question: {request.message}"
                ),
            },
        ]

    def _tool_result_content(self, result: ToolResult) -> str:
        """Serialize a ToolResult for the LLM to consume as tool response."""
        return json.dumps(
            {
                "tool": result.call.name,
                "summary": result.call.summary,
                "content": result.content,
                "citations": [
                    citation.model_dump(mode="json", exclude_none=True)
                    for citation in result.citations
                ],
            },
            ensure_ascii=False,
        )

"""OpenAI SDK based repository assistant harness.

Harness runs a tool-calling loop: LLM decides which tools to call → executes
them → feeds results back to LLM → repeats until LLM gives a final answer.

``answer()`` wraps this loop for the interactive chat panel (frontend).
``run()`` is the raw loop for backend services (auto-reply, auto-fix).
"""

import json
import logging
from typing import Any
from xml.etree import ElementTree

from openai import APIError, AsyncOpenAI, BadRequestError, OpenAIError

from app.assistant.tool_registry import RepositoryToolRegistry
from app.assistant.tools import ToolResult, merge_citations
from app.core.config import settings
from app.core.effective_config import get_effective_config
from app.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from app.schemas.repository import RepositorySnapshot
from app.services.repository_query import RepositoryQueryService
from app.services.usage import tracked_chat_completion


logger = logging.getLogger(__name__)

DSML_TOOL_CALLS_OPEN = "<｜｜DSML｜｜tool_calls>"
DSML_TOOL_CALLS_CLOSE = "</｜｜DSML｜｜tool_calls>"
TOOL_LIMIT_MESSAGE = "已达到仓库工具调用上限，无法在本轮形成完整回答。请缩小问题范围后重试。"
MAX_FINAL_EVIDENCE_CHARS = 24_000
MAX_TOOL_EVIDENCE_CHARS = 4_000


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
        self._cfg = get_effective_config()
        self.query = RepositoryQueryService()
        self.registry = RepositoryToolRegistry()
        self.client = (
            AsyncOpenAI(
                api_key=self._cfg.llm_api_key,
                base_url=self._cfg.llm_api_base_url,
            )
            if self._cfg.llm_api_key and self._cfg.llm_api_base_url and self._cfg.llm_model
            else None
        )

    # ── Public API ───────────────────────────────────────────────────

    async def answer(self, request: AssistantChatRequest) -> AssistantChatResponse:
        """Interactive Q&A — builds context from request, returns structured response."""
        if self.client is None:
            raise AgentHarnessError("LLM configuration is incomplete for the current user.", status_code=503)

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
        if self.client is None:
            raise AgentHarnessError("LLM configuration is incomplete for the current user.", status_code=503)

        for round_index in range(max_rounds):
            # ── Call LLM ─────────────────────────────────────────────
            try:
                completion = await tracked_chat_completion(
                    self.client,
                    model=self._cfg.llm_model,
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

            recovered_calls = []
            contains_dsml = bool(
                assistant_message.content
                and self._contains_dsml_tool_calls(assistant_message.content)
            )
            if not tool_calls and contains_dsml:
                recovered_calls = self._parse_dsml_tool_calls(assistant_message.content)

            # ── LLM answered directly (no tools needed) → done ──────
            if not tool_calls and not recovered_calls:
                if contains_dsml:
                    logger.error("Suppressing malformed DSML tool-call markup returned by the model.")
                    return TOOL_LIMIT_MESSAGE, tool_results
                return (assistant_message.content or ""), tool_results

            # ── Execute tools and feed results back ──────────────────
            calls_to_execute: list[tuple[str, str | dict[str, Any], str]] = []
            if tool_calls:
                messages.append(assistant_message.model_dump(exclude_none=True))
                calls_to_execute = [
                    (tool_call.function.name, tool_call.function.arguments, tool_call.id)
                    for tool_call in tool_calls
                ]
            else:
                logger.warning(
                    "Recovered %d DSML tool call(s) from assistant message content in round %d.",
                    len(recovered_calls),
                    round_index + 1,
                )
                calls_to_execute = [
                    (name, arguments, f"dsml_{round_index}_{call_index}")
                    for call_index, (name, arguments) in enumerate(recovered_calls)
                ]
                messages.append({
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                        for name, arguments, call_id in calls_to_execute
                    ],
                })

            for tool_name, tool_arguments, tool_call_id in calls_to_execute:
                result = self.registry.execute(
                    tool_name,
                    tool_arguments,
                    snapshot,
                )
                tool_results.append(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
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
        final_messages = self._build_final_synthesis_messages(messages, tool_results)
        try:
            final = await tracked_chat_completion(
                self.client,
                model=self._cfg.llm_model,
                messages=final_messages,
            )
        except (APIError, OpenAIError) as exc:
            raise AgentHarnessError(f"LLM final-answer request failed: {exc}") from exc

        final_message = final.choices[0].message
        final_content = final_message.content or ""
        if not final_message.tool_calls and not self._contains_dsml_tool_calls(final_content):
            return final_content, tool_results

        logger.warning("Model attempted a tool call while final answer synthesis disabled tools; retrying once.")
        retry_messages = [
            *final_messages,
            {
                "role": "system",
                "content": (
                    "Return the final answer now. Do not call tools and do not output tool-call markup, "
                    "XML, DSML, JSON instructions, or descriptions of intended future investigation."
                ),
            },
        ]
        try:
            retry = await tracked_chat_completion(
                self.client,
                model=self._cfg.llm_model,
                messages=retry_messages,
            )
        except (APIError, OpenAIError) as exc:
            raise AgentHarnessError(f"LLM final-answer retry failed: {exc}") from exc

        retry_message = retry.choices[0].message
        retry_content = retry_message.content or ""
        if retry_message.tool_calls or self._contains_dsml_tool_calls(retry_content):
            logger.error("Model returned another tool call after final-answer retry; suppressing protocol text.")
            return self._fallback_answer(tool_results), tool_results
        return retry_content, tool_results

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

    def _contains_dsml_tool_calls(self, content: str) -> bool:
        return DSML_TOOL_CALLS_OPEN in content

    def _build_final_synthesis_messages(
        self,
        messages: list[dict[str, Any]],
        tool_results: list[ToolResult],
    ) -> list[dict[str, str]]:
        question = next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "请总结仓库分析结果。",
        )
        evidence_parts: list[str] = []
        evidence_length = 0
        for result in tool_results:
            part = (
                f"工具：{result.call.name}\n"
                f"摘要：{result.call.summary}\n"
                f"结果：\n{result.content[:MAX_TOOL_EVIDENCE_CHARS]}"
            )
            if evidence_length + len(part) > MAX_FINAL_EVIDENCE_CHARS:
                break
            evidence_parts.append(part)
            evidence_length += len(part)
        evidence = "\n\n---\n\n".join(evidence_parts) or "没有可用的工具结果。"
        return [
            {
                "role": "system",
                "content": (
                    "你是仓库分析助手。请直接用中文回答用户问题，并根据提供的现有证据形成完整正文。"
                    "不要调用工具，不要输出 DSML、XML、JSON 工具指令，也不要描述接下来准备做什么。"
                    "证据不完整时仍应给出基于现有信息的最佳总结。"
                ),
            },
            {
                "role": "user",
                "content": f"用户问题：\n{question}\n\n已有仓库证据：\n{evidence}",
            },
        ]

    def _fallback_answer(self, tool_results: list[ToolResult]) -> str:
        if not tool_results:
            return TOOL_LIMIT_MESSAGE
        sections = []
        for result in tool_results[:8]:
            content = result.content.strip()[:1200]
            sections.append(f"### {result.call.name}\n\n{content or result.call.summary}")
        return "已根据当前获取到的仓库信息整理如下：\n\n" + "\n\n".join(sections)

    def _parse_dsml_tool_calls(self, content: str) -> list[tuple[str, dict[str, Any]]]:
        """Recover DeepSeek DSML tool markup returned in message.content."""
        start = content.find(DSML_TOOL_CALLS_OPEN)
        if start < 0:
            return []
        end = content.find(DSML_TOOL_CALLS_CLOSE, start)
        if end < 0:
            return []
        end += len(DSML_TOOL_CALLS_CLOSE)
        normalized = (
            content[start:end]
            .replace("<｜｜DSML｜｜", "<")
            .replace("</｜｜DSML｜｜", "</")
        )
        try:
            root = ElementTree.fromstring(normalized)
        except ElementTree.ParseError:
            logger.warning("Could not parse DSML tool-call markup returned by the model.")
            return []

        recovered: list[tuple[str, dict[str, Any]]] = []
        for invocation in root.findall("invoke"):
            name = invocation.get("name")
            if not name:
                continue
            arguments: dict[str, Any] = {}
            for parameter in invocation.findall("parameter"):
                parameter_name = parameter.get("name")
                if not parameter_name:
                    continue
                raw_value = parameter.text or ""
                if parameter.get("string", "").lower() == "true":
                    arguments[parameter_name] = raw_value
                    continue
                try:
                    arguments[parameter_name] = json.loads(raw_value)
                except json.JSONDecodeError:
                    arguments[parameter_name] = raw_value
            recovered.append((name, arguments))
        return recovered

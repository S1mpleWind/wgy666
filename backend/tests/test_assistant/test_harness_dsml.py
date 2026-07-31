"""Regression tests for model tool calls leaked as DeepSeek DSML content."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.assistant.harness import AgentHarness, TOOL_LIMIT_MESSAGE
from app.assistant.tools import ToolResult
from app.schemas.assistant import AssistantToolCall


DSML_RESPONSE = """继续深入查看正式 frontend 目录结构。

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="read_file">
<｜｜DSML｜｜parameter name="path" string="true">frontend/src/App.tsx</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="search_files">
<｜｜DSML｜｜parameter name="query" string="true">backend/app/assistant</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=True):
        payload = {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}
        return {key: value for key, value in payload.items() if value is not None}


def completion(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=FakeMessage(content, tool_calls))],
        usage=None,
    )


def harness_with_responses(*responses):
    harness = object.__new__(AgentHarness)
    harness._cfg = SimpleNamespace(llm_model="test-model")
    create = AsyncMock(side_effect=responses)
    harness.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    harness.registry = Mock()
    harness.registry.openai_tools.return_value = [{"type": "function", "function": {"name": "read_file"}}]
    harness.registry.execute.side_effect = lambda name, arguments, snapshot: ToolResult(
        call=AssistantToolCall(
            name=name,
            args=json.loads(arguments) if isinstance(arguments, str) else arguments,
            summary=f"Execute {name}.",
        ),
        content="tool result",
    )
    return harness, create


def native_tool_call(name="repo_overview", arguments="{}", call_id="call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.mark.asyncio
async def test_run_recovers_dsml_content_as_tool_calls():
    harness, create = harness_with_responses(
        completion(DSML_RESPONSE),
        completion("这是最终架构回答。"),
    )

    answer, results = await harness.run([{"role": "user", "content": "解释核心架构"}], Mock(), max_rounds=2)

    assert answer == "这是最终架构回答。"
    assert [result.call.name for result in results] == ["read_file", "search_files"]
    assert harness.registry.execute.call_args_list[0].args[1] == {"path": "frontend/src/App.tsx"}
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_final_answer_retries_and_suppresses_dsml():
    harness, create = harness_with_responses(
        completion(tool_calls=[native_tool_call()]),
        completion(DSML_RESPONSE),
        completion("基于已有证据，这是最终回答。"),
    )

    answer, results = await harness.run([{"role": "user", "content": "解释核心架构"}], Mock(), max_rounds=1)

    assert answer == "基于已有证据，这是最终回答。"
    assert len(results) == 1
    assert "tools" not in create.await_args_list[1].kwargs
    assert "tool_choice" not in create.await_args_list[1].kwargs
    assert all(message["role"] != "tool" for message in create.await_args_list[1].kwargs["messages"])
    assert "已有仓库证据" in create.await_args_list[1].kwargs["messages"][1]["content"]


@pytest.mark.asyncio
async def test_final_answer_never_returns_dsml_after_retry():
    harness, _ = harness_with_responses(
        completion(tool_calls=[native_tool_call()]),
        completion(DSML_RESPONSE),
        completion(DSML_RESPONSE),
    )

    answer, _ = await harness.run([{"role": "user", "content": "解释核心架构"}], Mock(), max_rounds=1)

    assert answer.startswith("已根据当前获取到的仓库信息整理如下")
    assert "DSML" not in answer


@pytest.mark.asyncio
async def test_malformed_dsml_is_never_returned_as_answer():
    malformed = "准备继续读取文件。\n<｜｜DSML｜｜tool_calls><broken>"
    harness, _ = harness_with_responses(completion(malformed))

    answer, results = await harness.run(
        [{"role": "user", "content": "解释核心架构"}],
        Mock(),
        max_rounds=1,
    )

    assert answer == TOOL_LIMIT_MESSAGE
    assert results == []
    assert "DSML" not in answer

"""Unit tests for text-form tool-call recovery (src/tool_call_recovery.py).

Local servers (LM Studio / llama.cpp + Qwen3) sometimes return the model's
native XML tool-call markup inside ``content`` instead of structured
tool_calls. These tests pin down the parser and the client wrapper without a
live server. The malformed blob is built from fragments so this file never
contains literal tag sequences.
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from autogen_core.models import CreateResult, RequestUsage  # noqa: E402

from tool_call_recovery import (  # noqa: E402
    ToolCallRecoveryClient,
    _recover,
    parse_text_tool_calls,
)


def _blob(name="append_md_file_tool", path="D:\\x\\spec.md", content="9. Glossary\nTerm\tDef"):
    """Build a malformed text-form tool call the way Qwen3 emits it."""
    open_fn = "<" + "function=" + name + ">"
    close_fn = "</" + "function>"
    p1o, p2o = "<" + "parameter=file_path>", "<" + "parameter=content>"
    pc = "</" + "parameter>"
    # Note the stray spaces before the closing tags (seen in real failures).
    return f"{open_fn}\n{p1o}\n{path}\n{pc} {p2o}\n{content}\n{pc} {close_fn}"


class _FakeTool:
    def __init__(self, name):
        self.name = name


def test_parse_recovers_call_with_equals_and_stray_space():
    calls = parse_text_tool_calls(_blob(), {"append_md_file_tool"})
    assert calls is not None and len(calls) == 1
    call = calls[0]
    assert call.name == "append_md_file_tool"
    args = json.loads(call.arguments)
    assert args["file_path"] == "D:\\x\\spec.md"
    assert args["content"].startswith("9. Glossary")


def test_parse_ignores_unknown_function_names():
    text = _blob(name="some_other_tool")
    assert parse_text_tool_calls(text, {"append_md_file_tool"}) is None


def test_parse_plain_prose_returns_none():
    assert parse_text_tool_calls("All sections are done. READY", {"append_md_file_tool"}) is None


def test_recover_converts_string_result_only_when_tools_declared():
    usage = RequestUsage(prompt_tokens=10, completion_tokens=5)
    text = _blob()
    result = CreateResult(finish_reason="stop", content=text, usage=usage, cached=False)

    # No tools declared (e.g. the reflection call): left untouched.
    assert _recover(result, None).content == text

    # Tools declared: converted to structured calls.
    recovered = _recover(result, [_FakeTool("append_md_file_tool")])
    assert isinstance(recovered.content, list) and len(recovered.content) == 1
    assert json.loads(recovered.content[0].arguments)["file_path"] == "D:\\x\\spec.md"


def test_wrapper_delegates_and_recovers():
    class _Inner:
        model_info = {"function_calling": True, "vision": False}

        def __init__(self):
            self.calls = []

        async def create(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return CreateResult(
                finish_reason="stop",
                content=_blob(),
                usage=RequestUsage(prompt_tokens=1, completion_tokens=1),
                cached=False,
            )

    inner = _Inner()
    client = ToolCallRecoveryClient(inner)
    assert client.model_info["function_calling"] is True  # delegated property

    tool = _FakeTool("append_md_file_tool")
    result = asyncio.run(client.create([object()], tools=[tool]))
    assert isinstance(result.content, list) and len(result.content) == 1
    assert inner.calls[0][1]["tools"] == [tool]  # forwarded unchanged (same instance)


def test_parse_recovers_truncated_block_without_closing_tags():
    """The server can cut the generation off mid-call; the call must still run."""
    open_fn = "<" + "function=append_md_file_tool>"
    p1o, p2o = "<" + "parameter=file_path>", "<" + "parameter=content>"
    text = f"{open_fn}\n{p1o}\nspec.md\n</parameter>\n{p2o}\n## 4. Functional Requirements\n| F-01 | …"
    calls = parse_text_tool_calls(text, {"append_md_file_tool"})
    assert calls and len(calls) == 1
    args = json.loads(calls[0].arguments)
    assert args["file_path"] == "spec.md"
    assert args["content"].startswith("## 4. Functional Requirements")


def test_parse_splits_parameters_when_the_first_is_unterminated():
    open_fn = "<" + "function=write_mermaid_to_file_tool>"
    p1o, p2o = "<" + "parameter=mermaid_code>", "<" + "parameter=file_path>"
    text = f"{open_fn}\n{p1o}\nflowchart TD\n  A-->B\n{p2o}\ndiagram.mmd"
    calls = parse_text_tool_calls(text, {"write_mermaid_to_file_tool"})
    assert calls and len(calls) == 1
    args = json.loads(calls[0].arguments)
    assert args["mermaid_code"] == "flowchart TD\n  A-->B"
    assert args["file_path"] == "diagram.mmd"


def test_recover_accepts_autogen_dict_tool_specs():
    """AssistantAgent passes OpenAI-style dicts, not tool objects."""
    usage = RequestUsage(prompt_tokens=10, completion_tokens=5)
    result = CreateResult(finish_reason="stop", content=_blob(), usage=usage, cached=False)
    tools = [{"name": "append_md_file_tool", "description": "append", "parameters": {"type": "object"}}]
    recovered = _recover(result, tools)
    assert isinstance(recovered.content, list) and len(recovered.content) == 1
    assert recovered.content[0].name == "append_md_file_tool"


def test_assistant_agent_actually_executes_a_recovered_call():
    """End-to-end through AssistantAgent: the leaked call must run, not be echoed."""
    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import FunctionTool

    written = []

    def append_md_file_tool(content: str) -> str:
        written.append(content)
        return "appended"

    class _FakeClient:
        model_info = {"vision": False, "function_calling": True, "json_output": False,
                      "family": "gpt_4", "structured_output": False}

        async def create(self, *args, **kwargs):
            return CreateResult(finish_reason="stop", content=_blob(),
                                usage=RequestUsage(prompt_tokens=1, completion_tokens=1),
                                cached=False)

        async def close(self):
            pass

    tool = FunctionTool(func=append_md_file_tool, description="append", name="append_md_file_tool")
    agent = AssistantAgent(name="writer", model_client=ToolCallRecoveryClient(_FakeClient()),
                          tools=[tool], reflect_on_tool_use=False)
    response = asyncio.run(agent.run(task="write section 9"))
    assert written == ["9. Glossary\nTerm\tDef"]
    assert "<" + "function=" not in str(response.messages[-1].content)

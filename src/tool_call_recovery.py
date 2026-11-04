"""Recover tool calls that local models emit as plain text.

Some OpenAI-compatible servers (LM Studio / llama.cpp serving Qwen3) fail to
parse the model's native XML tool-call markup into structured ``tool_calls``
and return it inside ``content`` instead. AutoGen treats a string result as a
final TextMessage, so the call is displayed in the UI but never executed.

:func:`model_loader.load_model_client` wraps every client in
:class:`ToolCallRecoveryClient`, which converts such text back into
FunctionCall objects before AutoGen sees them. Recovery only happens when the
content contains a function block whose name matches one of the tools declared
for that request, so ordinary prose is never touched.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, Optional, Sequence

from autogen_core import FunctionCall
from autogen_core.models import CreateResult

logger = logging.getLogger(__name__)

# Tolerate stray whitespace and an optional '=' after the tag name: Qwen3
# emits <function=name> while some outputs show <function= name> or spaces.
# The closing tag is optional because the server can truncate the generation
# before it is emitted; the body then runs to the next block or to the end.
_FN_BLOCK_RE = re.compile(
    r"<\s*function\s*=?\s*(?P<name>[A-Za-z0-9_]+)\s*>((?:(?!<\s*function).)*?)(?=</\s*function\s*>|<\s*function|$)",
    re.DOTALL,
)
_PARAM_RE = re.compile(
    r"<\s*parameter\s*=?\s*(?P<key>[A-Za-z0-9_]+)\s*>((?:(?!<\s*parameter).)*?)(?=</\s*parameter\s*>|<\s*parameter|$)",
    re.DOTALL,
)


def _tool_names(tools: Optional[Sequence[Any]]) -> set[str]:
    """Collect declared tool names from a create() ``tools`` argument.

    AutoGen's AssistantAgent passes OpenAI-style **dicts** (``{"name": ...,
    "description": ...}``), not tool objects, so a getattr-only check silently
    returns an empty set and no recovery ever happens.
    """
    names = set()
    for t in tools or []:
        if isinstance(t, dict):
            name = t.get("name") or (t.get("function") or {}).get("name")
        else:
            name = getattr(t, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


def parse_text_tool_calls(text: str, allowed_names: set[str]) -> list[FunctionCall] | None:
    """Parse text-form tool calls out of *text*.

    Returns a list of FunctionCall objects, or None when no block matches an
    allowed tool name. Parameter values are stripped (Qwen wraps them in
    newlines) and re-serialized as JSON so AutoGen can execute the call.

    Long generations are cut off by the server before the closing tags are
    emitted, so an unterminated block is still parsed: the value of the last
    parameter runs to the next ``<parameter`` tag or to the end of the text.
    """
    if not isinstance(text, str) or "<function" not in text:
        return None
    calls: list[FunctionCall] = []
    for i, m in enumerate(_FN_BLOCK_RE.finditer(text)):
        name = m.group("name")
        if name not in allowed_names:
            continue
        body = m.group(2)
        params: dict[str, str] = {}
        param_matches = list(_PARAM_RE.finditer(body))
        for pm in param_matches:
            value = pm.group(2) or ""
            params[pm.group("key")] = value.strip()
        if not params and not body.strip():
            continue
        try:
            arguments = json.dumps(params)
        except (TypeError, ValueError):
            continue
        calls.append(FunctionCall(id=f"call_recovered_{i}", name=name, arguments=arguments))
    return calls or None


def _recover(result: CreateResult, tools: Optional[Sequence[Any]]) -> CreateResult:
    """Convert a text-form tool-call result into structured FunctionCalls."""
    content = getattr(result, "content", None)
    if not isinstance(content, str):
        return result
    allowed = _tool_names(tools)
    if not allowed:
        return result
    calls = parse_text_tool_calls(content, allowed)
    if not calls:
        return result
    truncated = "</function>" not in content
    logger.info(
        "Recovered %d text-form tool call(s) (%s)%s; executing as structured calls.",
        len(calls),
        ", ".join(c.name for c in calls),
        " (server truncated the payload before the closing tag - the arguments may be partial)"
        if truncated else "",
    )
    return CreateResult(
        finish_reason=result.finish_reason,
        content=calls,
        usage=result.usage,
        cached=result.cached,
        thought=getattr(result, "thought", None),
    )


class ToolCallRecoveryClient:
    """ChatCompletionClient wrapper that recovers text-form tool calls.

    Only ``create`` / ``create_stream`` are intercepted; everything else is
    delegated to the wrapped client (model_info, close, dump_component, ...).
    """

    def __init__(self, inner):
        self._inner = inner

    @property
    def model_info(self) -> dict[str, Any]:
        return self._inner.model_info

    async def create(self, *args: Any, **kwargs: Any) -> CreateResult:
        result = await self._inner.create(*args, **kwargs)
        return _recover(result, kwargs.get("tools"))

    async def create_stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
        async for chunk in self._inner.create_stream(*args, **kwargs):
            if isinstance(chunk, CreateResult):
                yield _recover(chunk, kwargs.get("tools"))
            else:
                yield chunk

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)

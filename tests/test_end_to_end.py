"""End-to-end pipeline test with a scripted (offline) model client.

No API key, no network: the client replays the replies a real model would make,
so the team, the selector, the file tools and both MCP servers are exercised.

Run:  python -m pytest tests/test_end_to_end.py -q
"""

import asyncio
import json
import shutil
import sys
import types
from pathlib import Path

import pytest

from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import SelectorGroupChat
from autogen_ext.memory.canvas import TextCanvasMemory
from autogen_core import FunctionCall
from autogen_core.models import CreateResult, ModelFamily, ModelInfo, RequestUsage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from agents_creator import create_agents_from_config  # noqa: E402

SESSION_ID = "test-session"
WORK_DIR = PROJECT_ROOT / "conversation"

AGENT_NAMES = [
    "user", "planning_agent", "interviewer_agent", "summarizer_agent",
    "functional_spec_writer_agent", "functional_spec_checker_agent",
    "diagram_creator_agent", "mermaid_code_reviewer_agent",
    "use_case_agent", "glossary_agent", "terminate_agent",
]

INTERVIEW_QA = [
    ("What is the main business process the system must support?",
     "Order fulfilment: customers place orders, the warehouse picks and ships them."),
    ("Which departments are involved?",
     "Sales, warehouse and finance."),
    ("What is the current bottleneck?",
     "Manual stock reconciliation between warehouse and finance."),
]

SELECTOR_SCRIPT = (
    ["planning_agent"]
    + sum([["interviewer_agent", "user", "interviewer_agent"] for _ in INTERVIEW_QA], [])
    + ["planning_agent", "summarizer_agent", "glossary_agent", "use_case_agent",
       "functional_spec_writer_agent", "functional_spec_checker_agent",
       "diagram_creator_agent", "mermaid_code_reviewer_agent",
       "terminate_agent", "terminate_agent"]
)


class ScriptedModelClient:
    """Minimal ChatCompletionClient that replays a fixed script."""

    def __init__(self):
        self.turn = 0
        self.selector_step = 0
        self.asked = 0
        self.saved = 0
        self.terminate_step = 0

    def _result(self, content, finish_reason="stop"):
        return CreateResult(
            content=content,
            finish_reason="stop",
            usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
            cached=False,
        )

    def _call(self, name, arguments):
        return FunctionCall(id=f"call_{self.turn}", name=name, arguments=json.dumps(arguments))

    async def create(self, messages, **kwargs):
        self.turn += 1
        system = messages[0].content

        if "select an agent" in system.lower() or "following roles are available" in system.lower():
            name = SELECTOR_SCRIPT[min(self.selector_step, len(SELECTOR_SCRIPT) - 1)]
            self.selector_step += 1
            return self._result(name)

        # A tool result is the last message: reflect with plain text.
        if messages and "FunctionExecutionResult" in type(messages[-1]).__name__:
            if "TERMINATE_AGENT" in messages[0].content.upper() and self.terminate_step >= 2:
                return self._result("Pipeline complete. TERMINATE")
            return self._result("Done with the tool step.")

        role = system.split("\n")[0].upper()

        if "PLANNING AGENT" in role:
            if self.saved < len(INTERVIEW_QA):
                return self._result("ASSIGN: interviewer_agent awaiting_user_reply=true",
                                    finish_reason="stop")
            return self._result("ASSIGN: summarizer_agent awaiting_user_reply=false",
                                finish_reason="stop")

        if "INTERVIEWER" in role:
            if self.asked < len(INTERVIEW_QA) and self.asked <= self.saved:
                question = INTERVIEW_QA[self.asked][0]
                self.asked += 1
                return self._result(f"QUESTION: {question}")
            if self.saved < len(INTERVIEW_QA):
                question, answer = INTERVIEW_QA[self.saved]
                self.saved += 1
                return self._result([self._call("save_conversation_to_jsonl", {
                    "speaker_or_records": [
                        {"speaker": "interviewer", "message": question, "q_index": self.saved},
                        {"speaker": "user", "message": answer, "q_index": self.saved},
                    ],
                    "file_path": f"conversation/{SESSION_ID}/interview.jsonl",
                    "session_id": SESSION_ID,
                })])
            return self._result("READY FOR SYNTHESIS")

        if "SUMMARIZER" in role or "GLOSSARY" in role or "USE_CASE" in role:
            return self._result("Consolidated requirements: order fulfilment across sales, warehouse, finance.",
                finish_reason="stop",
            )

        if "SPEC_WRITER" in role:
            return self._result([self._call("write_md_file_tool", {
                    "content": (
                        "# Functional Specification\n\n"
                        "## Functional Requirements\n1. Order intake\n2. Warehouse picking\n"
                        "3. Stock reconciliation\n\n## Non-Functional Requirements\n"
                        "1. Reports must export to PDF.\n\n## Glossary\n**BA**: Business Analyst\n"
                    ),
                    "file_path": "conversation/functional_specification.md",
                })],
                finish_reason="stop",
            )

        if "CHECKER" in role:
            return self._result([self._call("read_md_file_tool",
                                   {"file_path": "conversation/functional_specification.md"})],
                finish_reason="stop",
            )

        if "DIAGRAM_CREATOR" in role:
            return self._result("flowchart TD\n  A[Customer order] --> B[Warehouse pick]\n"
                        "  B --> C[Ship]\n  C --> D[Finance reconcile]",
                finish_reason="stop",
            )

        if "MERMAID_CODE_REVIEWER" in role:
            return self._result([self._call("write_mermaid_to_file_tool", {
                    "mermaid_code": "flowchart TD\n  A[Customer order] --> B[Warehouse pick]\n"
                                    "  B --> C[Ship]\n  C --> D[Finance reconcile]",
                    "file_path": "conversation/process_diagram.mmd",
                })],
                finish_reason="stop",
            )

        if "TERMINATE_AGENT" in role:
            if self.terminate_step == 0:
                self.terminate_step = 1
                return self._result([
                    self._call("render_mermaid_png", {
                        "input_path": "conversation/process_diagram.mmd",
                        "output_path": "conversation/process_diagram.png",
                    }),
                    self._call("format_and_export", {
                        "session_dir": "conversation",
                        "md": "functional_specification.md",
                        "diagram": "process_diagram.png",
                        "md_out": "functional_specification.formatted.md",
                        "pdf_out": "deliverable.pdf",
                    }),
                ])
            if self.terminate_step == 1:
                self.terminate_step = 2
                return self._result([
                    self._call("ensure_dir_tool", {"dir_path": f"experience/{SESSION_ID}"}),
                    self._call("move_file_tool", {
                        "source_path": "conversation/functional_specification.md",
                        "destination_path": f"experience/{SESSION_ID}/functional_specification.md",
                    }),
                    self._call("move_file_tool", {
                        "source_path": "conversation/process_diagram.mmd",
                        "destination_path": f"experience/{SESSION_ID}/process_diagram.mmd",
                    }),
                    self._call("move_file_tool", {
                        "source_path": "conversation/process_diagram.png",
                        "destination_path": f"experience/{SESSION_ID}/process_diagram.png",
                    }),
                ])
            return self._result("Pipeline complete. TERMINATE")

        return self._result("OK", finish_reason="stop")

    async def create_stream(self, messages, **kwargs):
        yield await self.create(messages, **kwargs)

    def get_token_count(self, msgs):
        return sum(len(str(m.content)) for m in msgs)

    def get_max_token(self):
        return 100_000

    async def close(self):
        pass

    @property
    def model_info(self):
        return ModelInfo(
            family=ModelFamily.UNKNOWN,
            vision=False,
            function_calling=True,
            json_output=True,
            structured_output=False,
            multiple_system_messages=True,
        )

    @property
    def _model_info(self):
        return self.model_info


async def run_pipeline():
    answers = iter([answer for _, answer in INTERVIEW_QA])
    client = ScriptedModelClient()

    canvas_memory = TextCanvasMemory()
    # app.py exposes the canvas tool under the module name 'canvas'.
    canvas = types.SimpleNamespace(update_file_tool=canvas_memory.get_update_file_tool())
    sys.modules["canvas"] = canvas

    user, agents = await create_agents_from_config(
        str(PROJECT_ROOT / "lib" / "agents_config.yaml"),
        AGENT_NAMES,
        model_client=client,
        canvas_memory=canvas_memory,
        input_func=lambda prompt="": next(answers, ""),
    )

    team = SelectorGroupChat(
        participants=[agents[n] for n in AGENT_NAMES if n != "user"] + [user],
        model_client=client,
        max_turns=60,
        termination_condition=MaxMessageTermination(60) | TextMentionTermination("TERMINATE"),
        selector_prompt=(
            "Select an agent to perform task.\n{roles}\n"
            "Current conversation context:\n{history}\n"
            "Read the above conversation, then select an agent from {participants} "
            "to perform the next task. Only select one agent."
        ),
    )
    return await team.run(task="Start the business analyst interview.")


def test_end_to_end_produces_deliverables():
    if not (shutil.which("mmdc") or shutil.which("mmdc.cmd")):
        pytest.skip("mermaid-cli (mmdc) is not installed; PNG rendering cannot be verified")
    WORK_DIR.mkdir(exist_ok=True)
    result = asyncio.run(run_pipeline())

    tool_calls = [m for m in result.messages if getattr(m, "tool_calls", None)]
    assert tool_calls, "no tool calls were executed"

    interview = WORK_DIR / SESSION_ID / "interview.jsonl"
    assert interview.exists(), "interview.jsonl missing"
    records = [json.loads(line) for line in interview.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(r.get("speaker") == "interviewer" for r in records)

    spec = PROJECT_ROOT / "experience" / SESSION_ID / "functional_specification.md"
    assert spec.exists(), "spec was not moved into experience/<session>"
    assert "Functional Requirements" in spec.read_text(encoding="utf-8")

    diagram_png = PROJECT_ROOT / "experience" / SESSION_ID / "process_diagram.png"
    formatted = PROJECT_ROOT / "conversation" / "functional_specification.formatted.md"
    print(f"messages: {len(result.messages)}  tool calls: {len(tool_calls)}")
    print(f"diagram PNG: {diagram_png.exists()}")
    print(f"formatted spec: {formatted.exists()}")
    assert diagram_png.exists(), "the diagram was never rendered to PNG"
    assert formatted.exists(), "the formatted spec was never produced"

    shutil.rmtree(WORK_DIR / SESSION_ID, ignore_errors=True)
    shutil.rmtree(PROJECT_ROOT / "experience" / SESSION_ID, ignore_errors=True)
    for name in ("functional_specification.md", "functional_specification.formatted.md",
                 "process_diagram.mmd", "process_diagram.clean.mmd", "process_diagram.png",
                 "deliverable.pdf"):
        (WORK_DIR / name).unlink(missing_ok=True)


if __name__ == "__main__":
    test_end_to_end_produces_deliverables()
    print("pipeline OK")

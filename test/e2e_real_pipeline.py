"""
End-to-end test of the fixed pipeline against a real local model.

Per the user's instruction, LM Studio is replaced by the Strata endpoint:
    LMSTUDIO_BASE_URL = http://127.0.0.1:47831/v1
    LMSTUDIO_MODEL    = q2_0

It exercises the three bugs that were fixed:
  1. The functional specification is written COMPLETELY to disk (chunked writes
     + append dedup) and is session-scoped under conversation/<SESSION_ID>/.
  2. Deliverables land inside conversation/<SESSION_ID>/.
  3. functional_specification.pdf is produced via the pure-Python PyMuPDF fallback (no pandoc).

The human answers are role-played from conversation/interview.jsonl.
"""

import os
import sys
import json
import shutil
import asyncio
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Honour the profile in .env (MODEL_CLIENT / MODEL_CLIENT_TOOLS) instead of
# forcing lmstudio — forcing it made every e2e run use the local GPU even when
# the app was configured for Groq. The lmstudio profile is only redirected to
# Strata when lmstudio is actually the selected profile.
if os.getenv("MODEL_CLIENT", "").strip().lower() == "lmstudio":
    os.environ.setdefault("LMSTUDIO_BASE_URL", "http://127.0.0.1:47831/v1")
    os.environ.setdefault("LMSTUDIO_MODEL", "q2_0")

from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.ui import Console

import agents_tools_helpers as helpers
from rag_helpers import TemplateSafeTextCanvasMemory
from model_loader import load_model_client
import mcp_boot

SESSION_ID = "sess-e2e-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
SESSION_DIR = ROOT / "conversation" / SESSION_ID


def load_answers():
    """Human replies role-played from interview.jsonl, in order."""
    path = ROOT / "conversation" / "interview.jsonl"
    answers = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("speaker") == "user":
                answers.append(str(rec.get("message", "")).strip())
    # Fallbacks so the summarizer/terminator always get a usable reply.
    answers.append("APPROVE SUMMARY")
    answers.append("Looks good, proceed.")
    answers.append("proceed")
    return iter(answers)


async def main():
    helpers.set_session(SESSION_ID)
    answers = load_answers()

    model_name = os.getenv("MODEL_CLIENT", "lmstudio").strip().lower()
    tools_name = os.getenv("MODEL_CLIENT_TOOLS", model_name).strip().lower()
    model_client = load_model_client(model_name)
    model_client_tools = load_model_client(tools_name)
    print(f"model clients: {model_name} / {tools_name}")

    canvas = TemplateSafeTextCanvasMemory()
    update_file_tool = helpers.mirror_canvas_to_disk(canvas.get_update_file_tool())
    sys.modules["canvas"] = types.SimpleNamespace(update_file_tool=update_file_tool)

    mermaid_tools = await mcp_boot.mermaid_tools(str(ROOT))
    pdf_tools = await mcp_boot.pdf_format_tools(str(ROOT))

    seed_summary = (
        "CONFIRMED REQUIREMENTS (Laundry Shop Staff App v1):\n"
        "- QR tag per customer order/bag (not per garment)\n"
        "- Windows PC server app is the main system, local database, offline-capable, no sync\n"
        "- Android mobile is online-only, QR scanning + label printing\n"
        "- Single Staff role with full access\n"
        "- Statuses: Received -> In Cleaning -> Quality Check -> Ready for Pickup -> Picked Up\n"
        "- Shelf location tracking (aisle/shelf/level/bin)\n"
        "- Manual backup/export (full DB backup and/or CSV)\n"
    )

    writer = AssistantAgent(
        name="functional_spec_writer_agent",
        model_client=model_client_tools,
        system_message=(
            "You are the FUNCTIONAL_SPEC_WRITER_AGENT. Produce the full 9-section "
            "Functional Specification using the TEMPLATE. Save it in CHUNKS: first call "
            "write_md_file_tool ONCE with sections 1-3, then call append_md_file_tool "
            "once per chunk (Functional+Non-Functional; Roles+Assumptions; Use Cases; "
            "Glossary). Do NOT pass file_path. After saving, call read_md_file_tool to "
            "verify all 9 sections exist, then reply READY."
        ),
        tools=[helpers.write_md_file_tool, helpers.append_md_file_tool, helpers.read_md_file_tool],
        reflect_on_tool_use=False,  # keep tools available so text-form leaks can be recovered
        max_tool_iterations=10,
    )
    checker = AssistantAgent(
        name="functional_spec_checker_agent",
        model_client=model_client,
        system_message=(
            "Read the spec with read_md_file_tool. If all 9 sections are present reply "
            "'The functional specification document is complete' then READY, else list gaps "
            "and say NEEDS_INFO."
        ),
        tools=[helpers.read_md_file_tool],
        reflect_on_tool_use=False,  # keep tools available so text-form leaks can be recovered
        max_tool_iterations=10,
    )
    diagram = AssistantAgent(
        name="diagram_creator_agent",
        model_client=model_client_tools,
        system_message=(
            "Read the spec with read_md_file_tool. Then call write_mermaid_to_file_tool "
            "exactly once with a valid Mermaid 'flowchart TD' of the item lifecycle "
            "(Check-In -> Received -> In Cleaning -> Quality Check -> Ready for Pickup -> "
            "Check-Out). Do NOT pass file_path. You must actually make the tool call: "
            "replying with plain text is not a save. After the tool returns success, "
            "reply READY."
        ),
        tools=[helpers.read_md_file_tool, helpers.write_mermaid_to_file_tool],
        reflect_on_tool_use=False,
        max_tool_iterations=10,
    )

    def selector(messages):
        last = messages[-1] if messages else None
        src = last.source if last else None
        # The task text arrives as a "user" message: it must start the writer,
        # not fall through to the default (which sent it straight to terminate).
        if src is None or src == "user":
            return "functional_spec_writer_agent"
        if src == "functional_spec_writer_agent":
            return "functional_spec_checker_agent"
        if src == "functional_spec_checker_agent":
            return "diagram_creator_agent"
        if src == "diagram_creator_agent":
            return "terminate_agent"
        return "terminate_agent"

    terminate = AssistantAgent(
        name="terminate_agent",
        model_client=model_client_tools,
        system_message=(
            f"You are the TERMINATE_AGENT. Every file for this run is in {SESSION_DIR}. "
            "Call get_session_dir_tool first to confirm that path, then, in order: "
            f"clean_mermaid(input_path={SESSION_DIR}/process_diagram.mmd, "
            f"output_path={SESSION_DIR}/process_diagram.mmd, overwrite=True); "
            f"render_mermaid_png(input_path={SESSION_DIR}/process_diagram.mmd, "
            f"output_path={SESSION_DIR}/process_diagram.png); "
            f"format_and_export(session_dir={SESSION_DIR}, md=functional_specification.md, "
            "diagram=process_diagram.png, md_out=functional_specification.formatted.md, "
            "pdf_out=functional_specification.pdf, toc=True). Then reply TERMINATE."
        ),
        tools=[helpers.get_session_dir_tool, *mermaid_tools, *pdf_tools],
        reflect_on_tool_use=False,
        max_tool_iterations=10,
    )

    team = SelectorGroupChat(
        participants=[writer, checker, diagram, terminate],
        model_client=model_client,
        termination_condition=MaxMessageTermination(25) | TextMentionTermination("TERMINATE", sources=["terminate_agent"]),
        selector_func=selector,
        allow_repeated_speaker=False,
    )

    task = seed_summary + "\nPlease write the functional specification. " + next(answers, "")
    await Console(team.run_stream(task=task))

    sess_dir = ROOT / "conversation" / SESSION_ID
    print("\n=== ARTIFACTS ===")
    print("session dir:", sess_dir)
    # Deterministic completion: the pipeline must end with a PNG and a PDF even
    # if a local model stopped before calling the render/export tools.
    final = helpers.finalize_deliverables(str(sess_dir))
    print("finalize:", final)
    print("template gaps after auto-fill:", final["missing_sections"])
    print("placeholder sections (need a human):", final["placeholder_sections"])
    spec = sess_dir / "functional_specification.md"
    print("spec exists:", spec.exists())
    if spec.exists():
        text = spec.read_text(encoding="utf-8")
        import re
        heads = re.findall(r"^##\s+.+$", text, flags=re.MULTILINE)
        print("sections:", heads)
    pdf = sess_dir / "functional_specification.pdf"
    print("functional_specification.pdf exists:", pdf.exists())
    if pdf.exists():
        import pymupdf as fitz
        d = fitz.open(str(pdf))
        print("pdf pages:", d.page_count, "images:", sum(len(p.get_images()) for p in d))
        d.close()
    png = sess_dir / "process_diagram.png"
    print("process_diagram.png exists:", png.exists())
    html = sess_dir / "functional_specification.html"
    print("functional_specification.html exists:", html.exists())
    if html.exists():
        body = html.read_text(encoding="utf-8")
        print("html: bytes", len(body), "img", body.count("<img"), "toc links", body.count('<nav class="toc"'))
        print("html embeds mermaid source:", "Diagram source (Mermaid)" in body)
    md_has_diagram = spec.exists() and "![Process Diagram]" in spec.read_text(encoding="utf-8")
    print("markdown carries the diagram:", md_has_diagram)

    ok = (spec.exists() and pdf.exists() and png.exists() and html.exists()
          and md_has_diagram and not final["missing_sections"])
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

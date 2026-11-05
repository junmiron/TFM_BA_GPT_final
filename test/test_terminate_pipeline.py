"""Direct test of the TERMINATE pipeline (issue 3: PDF must be produced).

Pre-seeds a session folder with a real spec + mermaid diagram, then runs the
terminate agent with the REAL MCP mermaid + PDF tools against Strata q2_0.
"""
import os, sys, asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"lib")); sys.path.insert(0, str(ROOT/"src"))
os.environ["LMSTUDIO_BASE_URL"] = "http://127.0.0.1:47831/v1"
os.environ["LMSTUDIO_MODEL"] = "q2_0"

import agents_tools_helpers as helpers
helpers.set_session("sess-term-test")
sess = ROOT / "conversation" / "sess-term-test"
sess.mkdir(parents=True, exist_ok=True)

(sess / "functional_specification.md").write_text(
    "# Laundry Shop Staff App v1\n\n## 1. Product Overview\nA staff app for laundry shops.\n\n"
    "## 4. Functional Requirements\n| ID | Requirement | Priority |\n|---|---|---|\n"
    "| FR-01.1 | QR tag per order | Must Have |\n\n"
    "## 9. Glossary\n| Term | Definition |\n|---|---|\n| QR | Quick Response |\n",
    encoding="utf-8")
(sess / "process_diagram.mmd").write_text("flowchart TD\n  A[Check-In] --> B[In Cleaning] --> C[Ready] --> D[Pickup]\n", encoding="utf-8")

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.ui import Console
import mcp_boot
from model_loader import load_model_client

async def main():
    mermaid_tools = await mcp_boot.mermaid_tools(str(ROOT))
    pdf_tools = await mcp_boot.pdf_format_tools(str(ROOT))
    client = load_model_client(os.getenv("MODEL_CLIENT", "lmstudio"))

    terminate = AssistantAgent(
        name="terminate_agent",
        model_client=client,
        system_message=(
            "You are the TERMINATE_AGENT. Complete these steps in order using the tools.\n"
            "1) render_mermaid_png with input_path=\"project_root/conversation/sess-term-test/process_diagram.mmd\" "
            "and output_path=\"project_root/conversation/sess-term-test/process_diagram.png\", theme=\"forest\".\n"
            "2) format_and_export with session_dir=\"project_root/conversation/sess-term-test\", "
            "md=\"functional_specification.md\", diagram=\"process_diagram.png\", "
            "md_out=\"functional_specification.formatted.md\", pdf_out=\"functional_specification.pdf\".\n"
            "After both succeed reply TERMINATE."
        ),
        tools=[*mermaid_tools, *pdf_tools],
        reflect_on_tool_use=False,
    )
    result = None
    async for msg in terminate.run_stream(task="Complete the termination steps for sess-term-test."):
        result = msg
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " | ".join(str(c) for c in content)
        print(f"[{getattr(msg, 'source', '?')}] {str(content)[:300]}")
    # Same deterministic completion the app runs after the agent, so the test
    # measures the pipeline, not whether the local model obeyed step 2.
    final = helpers.finalize_deliverables(str(sess))
    print("finalize:", final)
    print("template gaps after auto-fill:", final["missing_sections"])
    print("placeholder sections (need a human):", final["placeholder_sections"])
    print("\n=== ARTIFACTS ===")
    for f in ["process_diagram.png", "functional_specification.formatted.md",
              "functional_specification.pdf", "functional_specification.html"]:
        print(f, "exists:", (sess / f).exists())
    import pymupdf as fitz
    pdf = sess / "functional_specification.pdf"
    if pdf.exists():
        d = fitz.open(str(pdf)); print("pdf pages:", d.page_count); d.close()
        html = sess / "functional_specification.html"
        md = sess / "functional_specification.md"
        ok_html = html.exists() and "data:image/png;base64," in html.read_text(encoding="utf-8")
        ok_md = md.exists() and "![Process Diagram]" in md.read_text(encoding="utf-8")
        print("html self-contained:", ok_html, "| md carries diagram:", ok_md)
        if ok_html and ok_md and not final["missing_sections"]:
            print("RESULT: PASS")
            return 0
    print("RESULT: FAIL")
    return 1

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

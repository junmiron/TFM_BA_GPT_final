"""Check that the bundled MCP servers start and expose the tools the
terminate_agent expects (Mermaid + PDF deliverable pipeline).

Run with:  python -m pytest -q tests/test_mcp_servers.py
"""

import asyncio
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

SERVERS = {
    "mermaid": PROJECT_ROOT / "mcp_servers" / "Mermaid-MCP" / "Mermaid-MCP.py",
    "pdf": PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py",
}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _start(server: Path):
    params = StdioServerParams(
        command=sys.executable,
        args=[str(server), "-d", str(PROJECT_ROOT), "--project-root", str(PROJECT_ROOT)],
        cwd=str(PROJECT_ROOT),
        env={"PYTHONUNBUFFERED": "1"},
        read_timeout_seconds=60.0,
    )
    return asyncio.run(mcp_server_tools(params))


def test_mermaid_server_exposes_tools():
    tools = _start(SERVERS["mermaid"])
    names = {t.name for t in tools}
    assert {"clean_mermaid", "render_mermaid_png", "check_mermaid"} <= names


def test_pdf_server_exposes_tools():
    tools = _start(SERVERS["pdf"])
    names = {t.name for t in tools}
    assert {"format_spec", "format_and_export"} <= names


def test_mermaid_cleaning_strips_code_fences():
    mermaid = _load_module(SERVERS["mermaid"], "mermaid_mcp")
    raw = "```mermaid\nflowchart TD\n  A-->B\n```\n"
    cleaned, report = mermaid.clean_mermaid_text(raw)
    assert cleaned.strip().startswith("flowchart TD")
    assert any(issue["code"] == "FENCE_DETECTED" for issue in report["issues"])
    assert report["detected_type"] == "flowchart"


def test_spec_formatter_builds_requirements_table(tmp_path):
    """format_document must produce a formatted spec even without a diagram."""
    pdf_server = _load_module(SERVERS["pdf"], "pdf_mcp")
    session_dir = tmp_path / "sess-test"
    session_dir.mkdir()
    (session_dir / "functional_specification.md").write_text(
        "# Project\n\n## Functional Requirements\n1. Login\n2. Export reports\n\n"
        "## Glossary\n**BA**: Business Analyst\n",
        encoding="utf-8",
    )
    result = pdf_server.format_document(
        session_dir, "functional_specification.md", "process_diagram.png", "formatted.md"
    )
    formatted = (session_dir / "formatted.md").read_text(encoding="utf-8")
    assert "Functional Requirements" in formatted
    assert isinstance(result, dict)


def test_mermaid_check_falls_back_when_agent_invents_a_path(tmp_path):
    """The diagram text lives in TextCanvasMemory, so the reviewer often calls
    check_mermaid on a path that does not exist (e.g. canvas_diagram.md). It
    must recover from the real diagram file instead of crashing the tool call."""
    mermaid = _load_module(SERVERS["mermaid"], "mermaid_mcp")
    session = tmp_path / "sess-fallback"
    session.mkdir()
    (session / "process_diagram.mmd").write_text(
        "flowchart TD\n  A[Check in]-->B[Print QR]\n", encoding="utf-8"
    )
    raw = mermaid.read_mermaid_source(session / "canvas_diagram.md")
    report = mermaid.check_mermaid_text(raw)
    assert report["detected_type"] == "flowchart", report


def test_mermaid_check_reports_available_files_when_no_diagram_exists(tmp_path):
    mermaid = _load_module(SERVERS["mermaid"], "mermaid_mcp")
    session = tmp_path / "sess-empty"
    session.mkdir()
    (session / "notes.txt").write_text("no diagram here", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as exc:
        mermaid.read_mermaid_source(session / "nope.mmd")
    msg = str(exc.value)
    assert "canvas" in msg.lower(), msg
    assert "notes.txt" in msg, msg


def test_mmdc_extracts_one_diagram_from_a_multi_diagram_markdown(tmp_path):
    """The diagram creator writes a Markdown doc with several fenced blocks, but
    mmdc renders one diagram per call; passing the whole file fails with
    UnknownDiagramError and the terminate stage loses the PNG."""
    if shutil.which("mmdc") is None and shutil.which("mmdc.cmd") is None:
        pytest.skip("mermaid-cli (mmdc) is not installed")
    mermaid = _load_module(SERVERS["mermaid"], "mermaid_mcp")
    src = tmp_path / "multi.mmd"
    src.write_text(
        "%% Diagrams: 1) lifecycle 2) state machine\n\n"
        "## 1. Lifecycle\n\n```mermaid\nflowchart TD\n  A[Check in]-->B[Print QR]\n```\n\n"
        "## 2. State machine\n\n```mermaid\nstateDiagram-v2\n  a --> b\n```\n",
        encoding="utf-8",
    )
    out = tmp_path / "multi.png"
    mermaid.run_mmdc(src, out, "png", theme="forest")
    assert out.exists() and out.stat().st_size > 1000


def test_mermaid_rendering_when_mmdc_is_available(tmp_path):
    """Only runs if the mermaid-cli binary is installed."""
    if shutil.which("mmdc") is None and shutil.which("mmdc.cmd") is None:
        pytest.skip("mermaid-cli (mmdc) is not installed")
    mermaid = _load_module(SERVERS["mermaid"], "mermaid_mcp")
    src = tmp_path / "diagram.mmd"
    src.write_text("flowchart TD\n  A[Start]-->B[Review]\n", encoding="utf-8")
    out = tmp_path / "diagram.png"
    mermaid.run_mmdc(src, out, "png", theme="forest")
    assert out.exists() and out.stat().st_size > 1000

    # mermaid-cli 12 removed -w/-H; passing width/height must still render
    # (it used to fail with "error: unknown option '-w'").
    out_sized = tmp_path / "diagram_sized.png"
    mermaid.run_mmdc(src, out_sized, "png", theme="forest", width=1400, height=1000)
    assert out_sized.exists() and out_sized.stat().st_size > 1000


def test_pdf_export_html_tool_is_callable_through_the_server(tmp_path):
    """`export_html` is both a module function and an MCP tool name.

    Inside create_server the tool def binds the name locally, so a tool body
    that called `export_html(...)` resolved to the decorated FunctionTool and
    died with "TypeError: 'FunctionTool' object is not callable" - the agent
    saw the tool in its list and every call errored. Drive it through the
    client so that wiring is checked, not just the function.
    """
    from fastmcp import Client

    pdf_server = _load_module(SERVERS["pdf"], "pdf_mcp")
    session = tmp_path / "sess-html-tool"
    session.mkdir()
    (session / "functional_specification.md").write_text(
        "# Test Spec\n\n## 1. Overview\nSome content.\n\n## Process Diagram\n\n",
        encoding="utf-8",
    )

    server = pdf_server.create_server([session], project_root=session)

    async def call():
        async with Client(server) as client:
            names = {t.name for t in await client.list_tools()}
            result = await client.call_tool(
                "export_html", {"session_dir": str(session)}
            )
            return names, result

    names, result = asyncio.run(call())
    assert "export_html" in names
    assert not result.is_error
    data = result.data if isinstance(result.data, dict) else result.content[0].text
    assert isinstance(data, dict), data
    out = Path(data["html"])
    assert out.name == "functional_specification.html" and out.is_file()
    body = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in body and "</html>" in body

"""Check that the bundled MCP servers start and expose the tools the
terminate_agent expects (Mermaid + PDF deliverable pipeline).

Run with:  python -m pytest -q tests/test_mcp_servers.py
"""

import asyncio
import importlib.util
import shutil
import sys
from pathlib import Path

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


def test_mermaid_rendering_when_mmdc_is_available(tmp_path):
    """Only runs if the mermaid-cli binary is installed."""
    if shutil.which("mmdc") is None:
        print("SKIP: mermaid-cli (mmdc) is not installed")
        return
    mermaid = _load_module(SERVERS["mermaid"], "mermaid_mcp")
    src = tmp_path / "diagram.mmd"
    src.write_text("flowchart TD\n  A[Start]-->B[Review]\n", encoding="utf-8")
    out = tmp_path / "diagram.png"
    mermaid.run_mmdc(src, out, "png", theme="forest")
    assert out.exists() and out.stat().st_size > 1000

"""Boot the bundled MCP servers used by the terminate agent.

Each helper starts a stdio MCP server that lives in mcp_servers/ and is
scoped to the project root, so no absolute machine paths are hard-coded.
"""

import sys
from pathlib import Path
from typing import List

from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _python_cmd(project_root: Path) -> str:
    """Prefer the interpreter that is actually running the app."""
    candidates = [
        sys.executable,
        project_root / ".venv_win" / "Scripts" / "python.exe",
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
    ]
    return next(str(p) for p in candidates if Path(p).exists())


def _server_tools(server_script: Path, project_root: Path) -> StdioServerParams:
    if not server_script.exists():
        raise FileNotFoundError(f"MCP server not found: {server_script}")

    params = StdioServerParams(
        command=_python_cmd(project_root),
        args=[
            str(server_script),
            "-d", str(project_root),
            "--project-root", str(project_root),
        ],
        # Keep the server CWD at the project root so relative paths behave.
        cwd=str(project_root),
        env={"PYTHONUNBUFFERED": "1"},
        read_timeout_seconds=60.0,
    )
    return params


async def mermaid_tools(project_root: str | None = None) -> list:
    """Mermaid clean/render tools (requires the `mmdc` mermaid-cli binary)."""
    pr = Path(project_root) if project_root else PROJECT_ROOT
    params = _server_tools(pr / "mcp_servers" / "Mermaid-MCP" / "Mermaid-MCP.py", pr)
    return await mcp_server_tools(params)


async def pdf_format_tools(project_root: str | None = None) -> list:
    """Spec formatting + PDF export tools (PDF needs pandoc + a LaTeX engine)."""
    pr = Path(project_root) if project_root else PROJECT_ROOT
    params = _server_tools(pr / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py", pr)
    return await mcp_server_tools(params)

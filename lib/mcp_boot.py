# mcp_boot.py
import os
import sys
from pathlib import Path
from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools

# Optional: import sys to locate python exe if needed
# import sys


async def fs_tools(project_root: str) -> list:
    pr = Path(project_root)

    # Try common venv locations first; fall back to current python
    candidates = [
        pr / ".venv" / "bin" / "python",
        pr / "venv"  / "bin" / "python",
        pr / ".venv" / "Scripts" / "python.exe",   # Windows
        pr / "venv"  / "Scripts" / "python.exe",   # Windows
    ]
    python_cmd = next((str(p) for p in candidates if p.exists()), sys.executable)

    params = StdioServerParams(
        command=python_cmd,
        args=[
            str(pr / "mcp_servers" / "PyMCP-FS" / "main.py"),   # adjust to your server entrypoint
            "-d", project_root,
            "-d", "/tmp",
            "--project-root", project_root,
            "--log-level", "DEBUG",
            "--log-file",   str(pr / "mcp_debug.log"),
        ],
        # keep the server’s CWD stable so relative paths don’t pick up the notebook folder
        cwd=str(pr),          # if your StdioServerParams uses `cwd`
        # working_dir=str(pr), # if your version uses `working_dir` instead of `cwd`
        env={"PYTHONUNBUFFERED": "1"},
        read_timeout_seconds=60.0,
    )
    return await mcp_server_tools(params)

async def mermaid_tools(project_root: str) -> list:
    pr = Path(project_root)

    # Try common venv locations first; fall back to current python
    candidates = [
        pr / ".venv" / "bin" / "python",
        pr / "venv"  / "bin" / "python",
        pr / ".venv" / "Scripts" / "python.exe",   # Windows
        pr / "venv"  / "Scripts" / "python.exe",   # Windows
    ]
    python_cmd = next((str(p) for p in candidates if p.exists()), sys.executable)

    params = StdioServerParams(
        command=python_cmd,
        args=[
            str(pr / "mcp_servers" / "Mermaid-MCP" / "Mermaid-MCP.py"),   # adjust to your server entrypoint
            "-d", project_root,
            "-d", "/tmp",
            "--project-root", project_root,
        ],
        # keep the server’s CWD stable so relative paths don’t pick up the notebook folder
        cwd=str(pr),          # if your StdioServerParams uses `cwd`
        # working_dir=str(pr), # if your version uses `working_dir` instead of `cwd`
        env={"PYTHONUNBUFFERED": "1"},
        read_timeout_seconds=60.0,
    )
    return await mcp_server_tools(params)

async def pdf_format_tools(project_root: str) -> list:
    pr = Path(project_root)

    # Try common venv locations first; fall back to current python
    candidates = [
        pr / ".venv" / "bin" / "python",
        pr / "venv"  / "bin" / "python",
        pr / ".venv" / "Scripts" / "python.exe",   # Windows
        pr / "venv"  / "Scripts" / "python.exe",   # Windows
    ]
    python_cmd = next((str(p) for p in candidates if p.exists()), sys.executable)

    params = StdioServerParams(
        command=python_cmd,
        args=[
            str(pr / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py"),   # adjust to your server entrypoint
            "-d", project_root,
            "-d", "/tmp",
            "--project-root", project_root,
        ],
        # keep the server’s CWD stable so relative paths don’t pick up the notebook folder
        cwd=str(pr),          # if your StdioServerParams uses `cwd`
        # working_dir=str(pr), # if your version uses `working_dir` instead of `cwd`
        env={"PYTHONUNBUFFERED": "1"},
        read_timeout_seconds=60.0,
    )
    return await mcp_server_tools(params)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import agents_tools_helpers as h


def test_relative_conversation():
    p = h._normalize_project_relative("../conversation/functional_specification.md")
    assert p.name == "functional_specification.md"
    assert "conversation" in str(p)


def test_windows_absolute_path_on_any_host():
    # Copied from a Windows machine while running under Linux.
    p = h._normalize_project_relative(r"D:\Code\Ba_gpt\TFM_BA_GPT\conversation\functional_specification.md")
    assert p.name == "functional_specification.md"
    assert str(p).endswith("conversation/functional_specification.md") or str(p).endswith("conversation\\functional_specification.md")


def test_project_root_prefix():
    p = h._normalize_project_relative("project_root/conversation/process_diagram.mmd")
    assert p.name == "process_diagram.mmd"
    assert "conversation" in str(p)


def test_session_scoping():
    h.set_session("sess-abc123")
    p = h._normalize_project_relative("conversation/functional_specification.md")
    assert "sess-abc123" in str(p)
    assert h.default_spec_path().endswith("sess-abc123/functional_specification.md") or h.default_spec_path().endswith("sess-abc123\\functional_specification.md")
    # Already session-scoped path stays as-is.
    p2 = h._normalize_project_relative("conversation/sess-abc123/functional_specification.md")
    assert "sess-abc123" in str(p2)
    h._ACTIVE_SESSION = None


def test_session_scoped_path_is_not_nested():
    # The terminate agent feeds get_session_dir_tool()'s own path back into
    # ensure_dir_tool/write_mermaid_to_file_tool. Redirecting that onto
    # _session_dir() produced conversation/<ID>/<ID>/ and orphaned files.
    h._ACTIVE_SESSION = "sess-nest"
    for candidate in (
        f"conversation/sess-nest/process_diagram.mmd",
        f"D:\\Code\\Ba_gpt\\TFM_BA_GPT\\conversation\\sess-nest",
        "sess-nest/final_summary.md",
    ):
        p = h._normalize_project_relative(candidate)
        assert h._session_dir() / "x" != p, p
        assert "sess-nest/sess-nest" not in str(p).replace("\\", "/"), p
    h._ACTIVE_SESSION = None


def test_canvas_writes_are_mirrored_to_disk():
    # TextCanvasMemory is in-memory only, so `canvas_diagram.md` never existed on
    # disk and the Mermaid MCP tools raised FileNotFoundError on it.
    import asyncio

    from autogen_ext.memory.canvas import TextCanvasMemory
    from autogen_ext.memory.canvas._canvas_writer import UpdateFileArgs

    h.set_session("sess-mirror")
    try:
        tool = h.mirror_canvas_to_disk(TextCanvasMemory().get_update_file_tool())
        asyncio.run(
            tool.run(UpdateFileArgs(filename="canvas_diagram.md", new_content="flowchart TD\n  A-->B\n"))
        )
        mirrored = h._session_dir() / "canvas_diagram.md"
        assert mirrored.exists(), "canvas write was not mirrored to the session folder"
        assert "flowchart TD" in mirrored.read_text(encoding="utf-8")

        # And the MCP reader now finds it instead of crashing.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "mermaid_mcp",
            Path(__file__).resolve().parent.parent
            / "mcp_servers" / "Mermaid-MCP" / "Mermaid-MCP.py",
        )
        mermaid = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mermaid)
        report = mermaid.check_mermaid_text(mermaid.read_mermaid_source(mirrored))
        assert report["detected_type"] == "flowchart"
    finally:
        import shutil

        shutil.rmtree(h._session_dir(), ignore_errors=True)
        h._ACTIVE_SESSION = None


def test_append_dedup(tmp_path=None):
    h._ACTIVE_SESSION = "sess-dedup"
    sess = h._session_dir()
    sess.mkdir(parents=True, exist_ok=True)
    r1 = h.write_md_file_tool("## 1. Title\n")
    r2 = h.append_md_file_tool("## 4. Functional Requirements\nFR-01 content\n")
    r3 = h.append_md_file_tool("## 4. Functional Requirements\nFR-01 content again\n")  # dup -> skipped
    text = h.read_md_file_tool()
    assert "Skipped duplicate" in r3
    assert text.count("## 4. Functional Requirements") == 1
    # cleanup
    import shutil
    shutil.rmtree(sess, ignore_errors=True)
    h._ACTIVE_SESSION = None

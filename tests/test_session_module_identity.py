"""Guard against the double-import bug that silently broke session scoping.

The pipeline must bind its agent tools through `lib.agents_tools_helpers`, the
same module object `set_session()` mutates. Importing the helpers bare
(`from agents_tools_helpers import ...`) executes a *second* module object with
its own `_ACTIVE_SESSION` global: the session gets set on one copy and read by
the other, so every deliverable lands flat in `conversation/` instead of
`conversation/<SESSION_ID>/` while the code looks correct.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_pipeline_tools_share_the_session_module():
    import lib.pipeline as pipeline
    from lib import agents_tools_helpers

    # The tools the agents are wired to must be the very functions whose
    # default paths consult the module that set_session() mutates.
    for name in (
        "write_md_file_tool",
        "append_md_file_tool",
        "read_md_file_tool",
        "write_mermaid_to_file_tool",
        "get_session_dir_tool",
        "selector_func",
    ):
        bound = getattr(pipeline, name)
        module_fn = getattr(agents_tools_helpers, name)
        assert bound is module_fn, f"pipeline.{name} is a different copy than lib.agents_tools_helpers.{name}"


def test_set_session_is_visible_to_bound_tools():
    import lib.pipeline as pipeline
    from lib import agents_tools_helpers

    agents_tools_helpers.set_session("sess-lane-test")
    try:
        # get_session_dir_tool reads _session_dir(); a stale second copy would
        # return the flat conversation/ folder instead of the session dir.
        d = pipeline.get_session_dir_tool()
        assert "sess-lane-test" in str(d), f"tool resolved to {d}, not the active session"
    finally:
        agents_tools_helpers._ACTIVE_SESSION = None


def test_no_duplicate_module_in_sys_path_shadowing():
    # If `lib/` is on sys.path, a bare `import agents_tools_helpers` creates a
    # second, independent module. app2 must not do that.
    src = (ROOT / "lib" / "pipeline.py").read_text(encoding="utf-8")
    import re

    offenders = [
        line.strip()
        for line in src.splitlines()
        if re.match(r"^\s*(from|import)\s+agents_tools_helpers\b", line)
    ]
    assert not offenders, (
        "pipeline.py must import the helpers as lib.agents_tools_helpers so "
        f"set_session() and the tools share one module object (found: {offenders})"
    )


def test_find_latest_session_dir_prefers_the_active_session(tmp_path, monkeypatch):
    """A stale fixture folder must not masquerade as the current run.

    `test_terminate_pipeline.py` leaves `conversation/sess-term-test/` behind with
    a stub spec. When the real run's session had no spec yet, `_find_latest_session_dir()`
    returned that fixture and the checker reported 426 chars from another run.
    """
    import time

    import app2
    from lib import agents_tools_helpers

    conv = tmp_path / "conversation"
    stale = conv / "sess-old-run"
    active = conv / "sess-current"
    stale.mkdir(parents=True)
    active.mkdir(parents=True)
    (stale / "functional_specification.md").write_text("# old\n", encoding="utf-8")
    time.sleep(0.05)
    (active / "functional_specification.md").write_text("# current\n", encoding="utf-8")

    monkeypatch.setattr(app2, "PROJECT_ROOT", str(tmp_path))
    agents_tools_helpers.set_session("sess-current")
    try:
        found = app2._find_latest_session_dir()
        assert found is not None and Path(found).name == "sess-current", found
        # Even when the active session has no spec yet, the fallback still works.
        (active / "functional_specification.md").unlink()
        found = app2._find_latest_session_dir()
        assert found is not None and Path(found).name == "sess-old-run", found
    finally:
        agents_tools_helpers._ACTIVE_SESSION = None

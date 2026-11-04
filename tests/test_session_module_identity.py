"""Guard against the double-import bug that silently broke session scoping.

`app2.py` bound its agent tools via `from agents_tools_helpers import ...` while
calling `set_session()` on `lib.agents_tools_helpers`. Because `lib/` is also on
`sys.path`, those are two *different* module objects with independent
`_ACTIVE_SESSION` globals: the session was set on one and read by the other, so
every deliverable landed flat in `conversation/` instead of
`conversation/<SESSION_ID>/` while the code looked correct.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_app2_tools_share_the_session_module():
    import app2
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
        bound = getattr(app2, name)
        module_fn = getattr(agents_tools_helpers, name)
        assert bound is module_fn, f"app2.{name} is a different copy than lib.agents_tools_helpers.{name}"


def test_set_session_is_visible_to_bound_tools():
    import app2
    from lib import agents_tools_helpers

    agents_tools_helpers.set_session("sess-lane-test")
    try:
        # get_session_dir_tool reads _session_dir(); a stale second copy would
        # return the flat conversation/ folder instead of the session dir.
        d = app2.get_session_dir_tool()
        assert "sess-lane-test" in str(d), f"tool resolved to {d}, not the active session"
    finally:
        agents_tools_helpers._ACTIVE_SESSION = None


def test_no_duplicate_module_in_sys_path_shadowing():
    # If `lib/` is on sys.path, a bare `import agents_tools_helpers` creates a
    # second, independent module. app2 must not do that.
    src = (ROOT / "app2.py").read_text(encoding="utf-8")
    import re

    offenders = [
        line.strip()
        for line in src.splitlines()
        if re.match(r"^\s*(from|import)\s+agents_tools_helpers\b", line)
    ]
    assert not offenders, (
        "app2.py must import the helpers as lib.agents_tools_helpers so "
        f"set_session() and the tools share one module object (found: {offenders})"
    )

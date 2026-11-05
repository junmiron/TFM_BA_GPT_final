#!/usr/bin/env python3
"""Install the pinned Typst + pandoc portable binaries for the PDF renderer.

Run once after cloning the repo (CI runs it before the test suites):

    python scripts/install_render_tools.py

The binaries land in mcp_servers/Final_deliverable_MCP_server/vendor/bin (gitignored).
If this fails or is skipped, deliverable rendering silently falls back to the
pure-Python PyMuPDF path - nothing breaks, the PDF just loses the cover page,
linked contents and running header/footer.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RENDERER = _ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "typst_render.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("typst_render", _RENDERER)
    if not spec or not spec.loader:
        print(f"ERROR: cannot load {_RENDERER}", file=sys.stderr)
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    status = module.binary_status()
    missing = [name for name, info in status.items() if not info["path"]]
    print(json.dumps(status, indent=2))
    if missing:
        print(f"WARNING: could not install {', '.join(missing)}; "
              "PDF export will use the PyMuPDF fallback.", file=sys.stderr)
        return 1
    print("Typst/pandoc ready for deliverable rendering.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

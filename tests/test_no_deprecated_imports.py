"""`fitz` is the deprecated PyMuPDF alias: importing it emits a FutureWarning and
PyMuPDF says it will be removed. The codebase previously imported it in seven places,
which is where the test-suite warning noise came from. This guards against reintroducing it.
"""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CHECKED = [
    "app2.py",
    "lib/agents_tools_helpers.py",
    "scripts/smoke_check.py",
    "mcp_servers/Final_deliverable_MCP_server/PDF_format_mcp_server.py",
    "test/e2e_real_pipeline.py",
    "test/roleplay_e2e.py",
    "test/test_terminate_pipeline.py",
    "tests/test_pdf_export.py",
    "tests/test_finalize_deliverables.py",
]


@pytest.mark.parametrize("rel", CHECKED)
def test_no_deprecated_fitz_alias(rel):
    text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
    assert "import fitz" not in text, f"{rel} still imports the deprecated `fitz` alias"
    assert 'importorskip("fitz")' not in text, f"{rel} still probes the deprecated `fitz` module"

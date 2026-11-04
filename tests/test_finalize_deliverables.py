"""Deterministic deliverable completion (lib/agents_tools_helpers.finalize_deliverables).

The terminate agent is a local model and can stop before calling the render/export
tools, so the pipeline must still end with process_diagram.png and deliverable.pdf.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import shutil
import pytest

import agents_tools_helpers as helpers

SPEC = """# Functional Specification — Test App

## 1. Overview
Statuses: Received -> In Cleaning -> Quality Check -> Ready for Pickup -> Picked Up.
"""


@pytest.fixture()
def session(tmp_path):
    sd = tmp_path / "conversation" / "sess-test"
    sd.mkdir(parents=True)
    (sd / "functional_specification.md").write_text(SPEC, encoding="utf-8")
    return sd


def test_diagram_source_is_derived_from_the_spec(session):
    mmd = helpers.ensure_diagram_source(session)
    assert mmd and mmd.exists()
    text = mmd.read_text(encoding="utf-8")
    assert text.startswith("%% Auto-derived")
    assert "flowchart TD" in text
    assert "A[Received]" in text and "D --> E" in text


def test_existing_diagram_source_is_not_overwritten(session):
    (session / "process_diagram.mmd").write_text("flowchart TD\n  X[Start] --> Y[End]\n",
                                                 encoding="utf-8")
    mmd = helpers.ensure_diagram_source(session)
    assert mmd.read_text(encoding="utf-8").startswith("flowchart TD")


def test_finalize_produces_png_and_pdf(session):
    if not helpers.render_diagram_png(session):
        pytest.skip("mmdc (mermaid-cli) is not installed on this machine")
    result = helpers.finalize_deliverables(str(session))
    assert result["diagram_png"] and Path(result["diagram_png"]).is_file()
    pdf = Path(result["pdf"])
    assert pdf.is_file()
    fitz = pytest.importorskip("pymupdf", reason="PyMuPDF is required for the PDF fallback")
    doc = fitz.open(str(pdf))
    try:
        assert doc.page_count >= 1
        # The derived diagram must be embedded, not just referenced.
        assert sum(len(page.get_images()) for page in doc) >= 1
    finally:
        doc.close()


def test_finalize_without_spec_returns_nothing(session):
    empty = session.parent / "sess-empty"
    empty.mkdir()
    result = helpers.finalize_deliverables(str(empty))
    assert result["diagram_png"] is None and result["pdf"] is None


def test_stale_pdf_is_regenerated_when_the_spec_changes(session):
    """A deliverable from a previous run must not satisfy the current one.

    The gate used to return any existing PDF that embedded an image, so a run
    that rewrote the spec still "passed" against a PDF from hours earlier.
    """
    fitz = pytest.importorskip("pymupdf", reason="PyMuPDF is required for the PDF fallback")
    helpers.finalize_deliverables(str(session))

    spec = session / "functional_specification.md"
    spec.write_text(
        SPEC + "\n\n## 2. Newly Added Section\nMore detail added after the first export.\n",
        encoding="utf-8",
    )

    helpers.finalize_deliverables(str(session))

    doc = fitz.open(str(session / "deliverable.pdf"))
    titles = {t for _, t, _ in doc.get_toc()}
    # PDF text extraction returns typographic ligatures (ﬁ, ﬀ), so a literal
    # substring test against the source markdown reports false negatives.
    text = "".join(page.get_text() for page in doc).replace("ﬁ", "fi").replace("ﬀ", "ff")
    doc.close()
    assert "2. Newly Added Section" in titles, titles
    assert "More detail added after the first export." in text


def test_finalize_regenerates_a_pdf_that_has_no_outline(session):
    """A PDF with the diagram but no bookmarks is not complete.

    The early-return gate used to accept any PDF that embedded an image, which
    let a deliverable ship with a rendered "Contents" paragraph but an empty
    outline - the reader's sidebar has nothing to click.
    """
    fitz = pytest.importorskip("pymupdf", reason="PyMuPDF is required for the PDF fallback")

    doc = fitz.open()
    page = doc.new_page()
    probe = fitz.open()
    probe.new_page(width=400, height=300)
    probe[0].get_pixmap().save(session / "process_diagram.png")
    probe.close()
    page.insert_image(page.rect, filename=str(session / "process_diagram.png"))
    doc.save(str(session / "deliverable.pdf"))
    doc.close()

    doc = fitz.open(str(session / "deliverable.pdf"))
    assert sum(len(p.get_images()) for p in doc) >= 1
    assert doc.get_toc() == []
    doc.close()

    helpers.finalize_deliverables(str(session))

    doc = fitz.open(str(session / "deliverable.pdf"))
    toc = doc.get_toc()
    doc.close()
    assert toc, "finalize_deliverables left a PDF with no bookmarks"
    assert any("1. Overview" in title for _, title, _ in toc), toc

def test_render_diagram_png_uses_the_ci_puppeteer_config(monkeypatch, tmp_path):
    """The helper that writes process_diagram.png must hand mmdc the bundled
    no-sandbox config in CI, otherwise Chrome fails on GitHub runners and the
    deliverable silently loses its diagram.

    CI skips the real render test (mmdc cannot run there), so this pins the
    command instead.
    """
    import subprocess

    if not (helpers._PROJECT_ROOT / "mcp_servers" / "Mermaid-MCP" / "puppeteer-ci.json").exists():
        pytest.skip("bundled puppeteer-ci.json is missing")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_bytes(b"\x89PNG")
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/mmdc")
    monkeypatch.setenv("CI", "true")

    session = tmp_path
    (session / "process_diagram.mmd").write_text("flowchart TD\n  A[Start]-->B[End]\n", encoding="utf-8")

    png = helpers.render_diagram_png(session)
    assert png and png.is_file()
    assert "-p" in calls[0], calls[0]
    assert calls[0][calls[0].index("-p") + 1].endswith("puppeteer-ci.json")

    # Locally (no CI env) mmdc keeps its default sandbox behaviour.
    monkeypatch.delenv("CI")
    calls.clear()
    png.unlink()
    helpers.render_diagram_png(session)
    assert "-p" not in calls[0], calls[0]

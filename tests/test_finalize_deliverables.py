"""Deterministic deliverable completion (lib/agents_tools_helpers.finalize_deliverables).

The terminate agent is a local model and can stop before calling the render/export
tools, so the pipeline must still end with process_diagram.png and functional_specification.pdf.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import re
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

    doc = fitz.open(str(session / "functional_specification.pdf"))
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
    doc.save(str(session / "functional_specification.pdf"))
    doc.close()

    doc = fitz.open(str(session / "functional_specification.pdf"))
    assert sum(len(p.get_images()) for p in doc) >= 1
    assert doc.get_toc() == []
    doc.close()

    helpers.finalize_deliverables(str(session))

    doc = fitz.open(str(session / "functional_specification.pdf"))
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


def test_markdown_deliverable_carries_the_diagram_and_its_source(session):
    """The .md is a deliverable too, so it must show the diagram, not just name it."""
    if not helpers.render_diagram_png(session):
        pytest.skip("mmdc (mermaid-cli) is not installed on this machine")
    helpers.finalize_deliverables(str(session))
    md = (session / "functional_specification.md").read_text(encoding="utf-8")
    assert "![Process Diagram](process_diagram.png)" in md
    assert "```mermaid" in md, "the Markdown deliverable lost the Mermaid source fence"
    assert "flowchart TD" in md


def test_diagram_embedding_is_idempotent(session):
    (session / "process_diagram.mmd").write_text("flowchart TD\n  A[Start]-->B[End]\n", encoding="utf-8")
    for _ in range(3):
        assert helpers.embed_diagram_in_markdown(session)
    md = (session / "functional_specification.md").read_text(encoding="utf-8")
    assert md.count("![Process Diagram]") == 1
    assert md.count("```mermaid") == 1


def test_finalize_produces_a_self_contained_html(session):
    if not helpers.render_diagram_png(session):
        pytest.skip("mmdc (mermaid-cli) is not installed on this machine")
    result = helpers.finalize_deliverables(str(session))
    html_path = Path(result["html"])
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    # The PNG is inlined, so the file opens correctly when moved or emailed
    # without the diagram sitting next to it.
    assert "data:image/png;base64," in html
    assert '<nav class="toc">' in html
    assert "Diagram source (Mermaid)" in html
    # Every TOC link resolves to a real heading anchor.
    anchors = set(re.findall(r'<h[1-3] id="([^"]+)"', html))
    for link in re.findall(r'<a href="#([^"]+)">', html):
        assert link in anchors, f"TOC link #{link} has no heading"

def test_legacy_deliverable_pdf_is_renamed_not_duplicated(tmp_path):
    """A pre-v1.1 session folder must not end up with two PDFs."""
    sd = tmp_path / "sess-old"
    sd.mkdir()
    (sd / "functional_specification.md").write_text(SPEC, encoding="utf-8")
    (sd / "deliverable.pdf").write_text("old pdf", encoding="utf-8")
    (sd / "deliverable.html").write_text("<html>old</html>", encoding="utf-8")

    renamed = helpers.migrate_legacy_deliverable_names(sd)
    assert sorted(renamed) == ["deliverable.html -> functional_specification.html",
                               "deliverable.pdf -> functional_specification.pdf"]
    assert not (sd / "deliverable.pdf").exists()
    assert (sd / "functional_specification.pdf").read_text(encoding="utf-8") == "old pdf"

    # Running again is a no-op: the new name already exists.
    assert helpers.migrate_legacy_deliverable_names(sd) == []


def test_rename_does_not_overwrite_an_existing_deliverable(tmp_path):
    sd = tmp_path / "sess-both"
    sd.mkdir()
    (sd / "deliverable.pdf").write_text("old", encoding="utf-8")
    (sd / "functional_specification.pdf").write_text("new", encoding="utf-8")
    assert helpers.migrate_legacy_deliverable_names(sd) == []
    assert (sd / "deliverable.pdf").read_text(encoding="utf-8") == "old"

CANVAS = """%% Two diagrams, one canvas document.

## 1. Order Flow
```mermaid
flowchart TD
    A[Order] --> B[Shipped]
```

## 2. Return Flow
```mermaid
flowchart LR
    C[Return] --> D[Refund]
```
"""


def test_every_diagram_in_the_canvas_is_rendered_and_embedded(session):
    """A canvas holding several diagrams must produce several diagrams, not one
    rendered image plus raw Mermaid source printed as text further down.

    mmdc renders one diagram per invocation, and the reviewer keeps the canvas as
    a Markdown document with a heading and a fence per diagram - wrapping that
    whole document in a single fence nests the inner fences and the source leaks
    into the PDF.
    """
    if not shutil.which("mmdc"):
        pytest.skip("mmdc (mermaid-cli) is not installed on this machine")
    (session / "process_diagram.mmd").write_text(CANVAS, encoding="utf-8")

    pngs = helpers.render_diagram_pngs(session)
    assert len(pngs) == 2, pngs
    assert all(Path(p).is_file() for p in pngs)

    result = helpers.finalize_deliverables(str(session))
    md = (session / "functional_specification.md").read_text(encoding="utf-8")
    assert md.count("```mermaid") == 2, md.count("```mermaid")
    assert "![Process Diagram](process_diagram.png)" in md
    assert "![Return Flow](process_diagram_2.png)" in md

    fitz = pytest.importorskip("pymupdf", reason="PyMuPDF is required for the PDF fallback")
    doc = fitz.open(result["pdf"])
    try:
        images = sum(len(page.get_images(full=True)) for page in doc)
        text = "".join(page.get_text() for page in doc)
    finally:
        doc.close()
    assert images == 2, images
    for marker in ("flowchart TD", "flowchart LR", "```mermaid"):
        assert marker not in text, f"raw Mermaid source reached the PDF: {marker!r}"


def test_embed_diagram_repairs_a_canvas_nested_in_one_fence(session):
    """The pre-fix embedder wrapped a multi-diagram canvas in a single fence.

    Re-running the embedder must collapse that into one diagram per rendered PNG
    instead of leaving the headings and fences behind as plain text.
    """
    nested = (
        "## Process Diagram\n\n"
        "![Process Diagram](process_diagram.png)\n\n"
        "```mermaid\n"
        "%% canvas\n\n"
        "## 1. Order Flow\n"
        "```mermaid\nflowchart TD\n  A-->B\n```\n"
        "## 2. Return Flow\n"
        "```mermaid\nflowchart LR\n  C-->D\n```\n"
        "```\n\n\n## 10. Glossary\n\nA glossary entry.\n"
    )
    (session / "functional_specification.md").write_text(nested, encoding="utf-8")

    module = helpers._pdf_server_module()
    embedded = module.embed_diagram(nested, ["process_diagram.png", "process_diagram_2.png"], CANVAS)

    assert embedded.count("```mermaid") == 2, embedded.count("```mermaid")
    assert embedded.count("![Process Diagram](process_diagram.png)") == 1
    assert "![Return Flow](process_diagram_2.png)" in embedded
    assert "Order Flow" in embedded
    assert "## 10. Glossary" in embedded
    assert "A glossary entry." in embedded
    # Re-running must not grow the section.
    again = module.embed_diagram(embedded, ["process_diagram.png", "process_diagram_2.png"], CANVAS)
    assert again.count("```mermaid") == 2
    assert again.count("![Process Diagram]") == 1


def test_strip_mermaid_fences_survives_nested_fences():
    """A fence opened with a language closes only on a bare ``` line."""
    module = helpers._pdf_server_module()
    nested = (
        "```mermaid\nflowchart TD\n  A-->B\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n"
        "## Real Heading\n\nProse that must survive.\n"
    )
    stripped = module._strip_mermaid_fences(nested)
    assert "flowchart TD" not in stripped
    assert "sequenceDiagram" not in stripped
    assert "Prose that must survive." in stripped


"""The deliverable PDF fallback: PyMuPDF replaces pandoc/LaTeX when neither is
installed, and must still embed the process diagram and a table of contents.

Run with:  python -m pytest -q tests/test_pdf_export.py
"""

import importlib.util
import re
from pathlib import Path

import pytest

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF is required for the PDF fallback")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_SERVER = PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py"

SPEC = """# Laundry Shop Staff App v1

## 1. Product Overview
A staff app for laundry shops that tracks orders end to end.

## 2. In-Scope Business Requirements
1. Order tracking: QR tag per order; status visible to staff.
2. Customer notifications: SMS when an order is ready.

## 4. Functional Requirements
1. Scan QR at check-in.
2. Update status through cleaning stages.

## 9. Glossary
| Term | Definition |
|---|---|
| QR | Quick Response |
"""


def _load_pdf_module():
    spec = importlib.util.spec_from_file_location("pdf_format_mcp_server", PDF_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_title_uses_project_not_title_page(tmp_path):
    """The browser tab and PDF metadata must never read "Title Page"."""
    pdf = _load_pdf_module()
    md = tmp_path / "functional_specification.md"
    md.write_text(
        "# Title Page\n\n**Project:** WashLoop v1  \n**Document:** Functional Specification Document  \n\n## 1. Scope\n",
        encoding="utf-8",
    )
    assert pdf._extract_title(md) == "WashLoop v1 - Functional Specification Document"

    # No Project metadata: fall through to the first real heading.
    md.write_text("# Title Page\n\n**Version:** 1.0\n\n## 2. Functional Requirements\n", encoding="utf-8")
    assert pdf._extract_title(md) == "2. Functional Requirements"


def _make_session(tmp_path: Path) -> Path:
    session = tmp_path / "sess-test"
    session.mkdir(parents=True, exist_ok=True)
    (session / "functional_specification.md").write_text(SPEC, encoding="utf-8")

    # A real PNG with an alpha channel, same shape the Mermaid renderer produces.
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.draw_rect((50, 50, 550, 350), color=(0, 0, 0), fill=(0.9, 0.95, 1.0))
    page.insert_text((80, 80), "Check-In -> Cleaning -> Ready -> Pickup")
    page.get_pixmap().save(session / "process_diagram.png")
    doc.close()
    return session


def test_format_document_adds_diagram_section(tmp_path):
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)
    fmt = pdf.format_document(session, "functional_specification.md",
                              "process_diagram.png", "functional_specification.formatted.md")
    formatted = Path(fmt["written_to"]).read_text(encoding="utf-8")
    assert "Process Diagram" in formatted
    assert "process_diagram.png" in formatted
    assert fmt["business_requirements"] >= 1


def test_pymupdf_fallback_embeds_diagram_and_toc(tmp_path):
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)
    pdf.format_document(session, "functional_specification.md",
                        "process_diagram.png", "functional_specification.formatted.md")

    result = pdf._pymupdf_export(
        session / "functional_specification.formatted.md",
        session / "process_diagram.png",
        session / "functional_specification.pdf",
        title="Laundry Shop Staff App v1",
        toc=True,
        toc_depth=2,
    )
    assert result["status"] == "ok", result.get("message")
    assert Path(result["pdf"]).is_file()

    doc = fitz.open(result["pdf"])
    text = "".join(page.get_text() for page in doc)
    doc.close()

    assert result["pages"] >= 1
    assert result["images"] >= 1, "the process diagram must be embedded, not a placeholder"
    assert "Contents" in text
    assert "Product Overview" in text
    assert "[image]" not in text, "pandoc image syntax leaked into the PDF as text"
    assert "width=95%" not in text


def test_pymupdf_fallback_without_toc(tmp_path):
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)
    pdf.format_document(session, "functional_specification.md",
                        "process_diagram.png", "functional_specification.formatted.md")
    result = pdf._pymupdf_export(
        session / "functional_specification.formatted.md",
        session / "process_diagram.png",
        session / "functional_specification.pdf",
        title="Laundry Shop Staff App v1",
        toc=False,
    )
    assert result["status"] == "ok", result.get("message")
    assert result["pages"] >= 1 and result["images"] >= 1


def test_missing_diagram_still_produces_a_pdf(tmp_path):
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)
    pdf.format_document(session, "functional_specification.md",
                        "process_diagram.png", "functional_specification.formatted.md")
    result = pdf._pymupdf_export(
        session / "functional_specification.formatted.md",
        session / "does_not_exist.png",
        session / "functional_specification.pdf",
        title="No diagram",
        toc=True,
    )
    assert result["status"] == "ok", result.get("message")
    assert result["pages"] >= 1


def test_subsection_requirements_are_extracted(tmp_path):
    """Groq writes section 4 as `### 4.1 ...` bullets, not a numbered list.

    parse_requirements used to return nothing for that shape, so the FR mapping
    table was silently empty in the deliverable.
    """
    pdf = _load_pdf_module()
    spec = """# Laundry Shop Staff App v1

## 2. In-Scope Business Requirements
- Order tracking end to end
- Shelf location tracking

## 4. Functional Requirements

### 4.1 Order Registration
- Staff creates a new order.
- System calculates the total price.

### 4.2 QR Tag Scanning
- Staff scans the QR tag.

## 9. Glossary
| Term | Definition |
|---|---|
| QR | Quick Response |
"""
    items = pdf.parse_requirements("### 4.1 Order Registration\n- a\n\n### 4.2 QR\n- b\n")
    assert len(items) == 2, items
    assert items[0]["title"] == "Order Registration"
    assert items[0]["bullets"] == ["a"]

    session = tmp_path / "sess"
    session.mkdir(parents=True)
    (session / "functional_specification.md").write_text(spec, encoding="utf-8")
    fmt = pdf.format_document(session, "functional_specification.md",
                              "process_diagram.png", "functional_specification.formatted.md")
    assert fmt["functional_requirements"] == 2, fmt
    assert fmt["business_requirements"] >= 2, fmt
    formatted = Path(fmt["written_to"]).read_text(encoding="utf-8")
    assert "| Business Requirement ID | Functional Requirement ID | Description |" in formatted


def test_scope_section_named_without_in_prefix(tmp_path):
    """`## 2. Purpose and Scope` is as common as `## In-Scope`."""
    pdf = _load_pdf_module()
    spec = """# Laundry Shop Staff App v1

## 2. Purpose and Scope
The purpose is to define requirements for the app, focusing on:
- Automating order intake via QR tags.
- Managing garment lifecycle statuses.
- Tracking shelf locations.

## 4. Functional Requirements
1. Scan QR at check-in.
2. Update status through cleaning stages.
"""
    session = tmp_path / "sess"
    session.mkdir(parents=True)
    (session / "functional_specification.md").write_text(spec, encoding="utf-8")
    fmt = pdf.format_document(session, "functional_specification.md",
                              "process_diagram.png", "functional_specification.formatted.md")
    assert fmt["business_requirements"] >= 3, fmt
    assert fmt["functional_requirements"] == 2, fmt
    formatted = Path(fmt["written_to"]).read_text(encoding="utf-8")
    assert "BR1" in formatted and "FR1" in formatted


def test_tall_diagram_is_scaled_into_the_page(tmp_path):
    """A diagram taller than the page used to hang PyMuPDF's Story layout."""
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)

    doc = fitz.open()
    page = doc.new_page(width=784, height=1966)  # taller than A4 (842 pt)
    page.draw_line((400, 100), (400, 1860))
    page.get_pixmap().save(session / "process_diagram.png")
    doc.close()

    tag = pdf._img_tag("process_diagram.png", "Process Diagram", session)
    # The cap is below the full content height: Story drops an <img> that
    # cannot fit in the space left on the page, so the heading above a diagram
    # has to leave room for it.
    assert f'height="{pdf._IMAGE_MAX_H}"' in tag, tag
    assert pdf._IMAGE_MAX_H < pdf._CONTENT_H
    assert 'width="' in tag

    pdf.format_document(session, "functional_specification.md",
                        "process_diagram.png", "functional_specification.formatted.md")
    result = pdf._pymupdf_export(
        session / "functional_specification.formatted.md",
        session / "process_diagram.png",
        session / "functional_specification.pdf",
        title="Tall diagram",
        toc=True,
    )
    assert result["status"] == "ok", result.get("message")
    assert result["images"] >= 1


def test_duplicate_subsection_numbers_are_fixed():
    """The writer appends sections out of order and reuses a stale number, which
    otherwise lands in the TOC and the PDF as `8.4` twice."""
    pdf = _load_pdf_module()
    md = (
        "## 8. Use Cases\n\n"
        "### 8.1 UC-1\n"
        "### 8.2 UC-2\n"
        "### 8.4 UC-4\n"
        "### 8.13 UC-13\n"
        "### 8.4 End-to-End Lifecycle Sequence\n\n"
        "## 9. Glossary\n\n"
        "### 9.1 Terms\n"
    )
    fixed, fixes = pdf.normalize_heading_numbering(md)
    assert fixes == ["### 8.4 -> ### 8.14"], fixes
    assert "### 8.14 End-to-End Lifecycle Sequence" in fixed
    assert "### 8.4 End-to-End" not in fixed


def test_legitimate_numbering_gaps_are_preserved():
    """Renumbering every heading would break body cross-references such as
    "see Section 4.2", so only duplicates may be touched."""
    pdf = _load_pdf_module()
    md = (
        "## 4. Functional Requirements\n\n"
        "### 4.1 Intake\n"
        "### 4.3 Pricing\n\n"
        "## 5. Non-Functional Requirements\n\n"
        "### 5.1 Availability\n"
    )
    fixed, fixes = pdf.normalize_heading_numbering(md)
    assert fixes == []
    assert fixed == md


def test_heading_after_a_table_is_not_swallowed_into_a_cell(tmp_path):
    """A heading with no blank line after a table becomes a table cell.

    Markdown's `tables` extension keeps consuming non-blank lines, so
    `| BR1 | FR1 | x |` followed directly by `## 4. Non-Functional
    Requirements` renders the heading as `<td>## 4. ...</td>` - the section
    vanishes from the document and from the outline.
    """
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)
    spec = (
        "# Table Adjacency Test\n\n"
        "## 1. Requirements\n\n"
        "| BR | FR | Description |\n| --- | --- | --- |\n| BR1 | FR1 | tracked |\n"
        "## 2. Non-Functional Requirements\n\n" + "text\n" * 40 + "\n"
        "## 3. Glossary\n\n" + "terms\n" * 40 + "\n"
    )
    (session / "functional_specification.md").write_text(spec, encoding="utf-8")

    html = pdf._markdown_to_html(spec, session)
    assert not re.search(r"<td>#{1,6}\s", html), html[html.find("<td>##"):][:200]

    result = pdf._pymupdf_export(
        session / "functional_specification.md", None, session / "adjacency.pdf",
        title="Adjacency", toc=True,
    )
    assert result["status"] == "ok", result.get("message")
    doc = fitz.open(session / "adjacency.pdf")
    titles = {t for _, t, _ in doc.get_toc()}
    doc.close()
    assert "2. Non-Functional Requirements" in titles, titles
    assert "3. Glossary" in titles, titles


def test_paragraph_after_a_table_is_not_folded_into_the_last_row():
    """The mapping table swallowed FR-31..FR-36 into a single cell."""
    pdf = _load_pdf_module()
    md = (
        "## 3. Functional Requirements\n\n"
        "| BR | FR | Description |\n| --- | --- | --- |\n| BR1 | FR1 | tracked |\n"
        "**FR-31: Superseded status labels**\n"
        "The original status names are superseded for v1.\n\n"
        "## 4. Non-Functional Requirements\n"
    )
    html = pdf.ensure_blank_line_before_headings(md)
    assert "|\n\n**FR-31" in html, html
    assert "<strong>FR-31" in pdf._markdown_to_html(md, Path(".")), \
        pdf._markdown_to_html(md, Path("."))


def test_code_fence_headings_are_not_altered():
    pdf = _load_pdf_module()
    md = "# Title\n\n```\n## inside the fence\n```\n## Real heading\n"
    fixed = pdf.ensure_blank_line_before_headings(md)
    assert "```\n## inside the fence\n```" in fixed, fixed
    assert "\n\n## Real heading" in fixed, fixed


def test_pdf_has_a_real_outline_not_just_contents_text(tmp_path):
    """`toc=True` must produce PDF bookmarks, not only a visible Contents block.

    A rendered Contents list is plain text: a reader's sidebar stays empty and
    `doc.get_toc()` returns [], so the deliverable is not navigable.
    """
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)
    spec = (
        "# Nested Outline Test\n\n"
        "## 1. Introduction\n\n" + "intro text\n" * 40 + "\n"
        "### 1.1 Overview\n\n" + "overview text\n" * 40 + "\n"
        "## 2. Requirements\n\n" + "requirement text\n" * 40 + "\n"
        "### 2.1 Functional\n\n" + "functional text\n" * 40 + "\n"
    )
    (session / "functional_specification.md").write_text(spec, encoding="utf-8")

    result = pdf._pymupdf_export(
        session / "functional_specification.md",
        None,
        session / "outline.pdf",
        title="Outline test",
        toc=True,
        toc_depth=3,
    )
    assert result["status"] == "ok", result.get("message")
    assert result["toc_entries"] > 0, result

    doc = fitz.open(session / "outline.pdf")
    toc = doc.get_toc()

    levels = {title: level for level, title, _ in toc}
    assert levels.get("1. Introduction") == 2, toc
    assert levels.get("1.1 Overview") == 3, toc
    assert levels.get("2.1 Functional") == 3, toc

    # Every bookmark must land on a page that actually contains its heading.
    for level, title, page in toc:
        assert 1 <= page <= doc.page_count, (title, page)
        assert title in doc[page - 1].get_text(), (title, page)
    doc.close()

    # toc_depth=2 must stop at level 2 and drop the h3 entries.
    shallow = pdf._pymupdf_export(
        session / "functional_specification.md",
        None,
        session / "outline2.pdf",
        title="Shallow outline",
        toc=True,
        toc_depth=2,
    )
    doc2 = fitz.open(session / "outline2.pdf")
    toc2 = doc2.get_toc()
    doc2.close()
    assert "1.1 Overview" not in {t for _, t, _ in toc2}, toc2
    assert "1. Introduction" in {t for _, t, _ in toc2}, toc2

def test_every_diagram_in_a_multi_diagram_story_survives(tmp_path):
    """Story silently drops an image that does not fit the remaining page space.

    With ten full-height diagrams in one document, the tenth never made it into
    the PDF; the height cap in _img_tag is what keeps them all.
    """
    pdf = _load_pdf_module()
    session = _make_session(tmp_path)

    doc = fitz.open()
    for i in range(10):
        page = doc.new_page(width=700, height=1800)  # taller than the A4 page
        page.draw_line((300, 100), (300, 1700))
        page.get_pixmap().save(session / f"process_diagram_{i + 1}.png")
    doc.close()

    md = "# Multi diagram\n\n## Process Diagram\n\n" + "\n\n".join(
        f"![Diagram {i + 1}](process_diagram_{i + 1}.png){{ width=95% }}" for i in range(10)
    )
    (session / "functional_specification.formatted.md").write_text(md, encoding="utf-8")

    result = pdf._pymupdf_export(
        session / "functional_specification.formatted.md",
        session / "process_diagram.png",
        session / "functional_specification.pdf",
        title="Multi diagram",
        toc=False,
    )
    assert result["status"] == "ok", result.get("message")
    assert result["images"] == 10, result

CANVAS = """## System Context
```mermaid
flowchart LR
    A[Shop PC] --> B[Android app]
```

### End-to-End Workflow
```mermaid
flowchart TD
    B --> C[Ready for pickup]
```

### Bag Status Lifecycle
```mermaid
stateDiagram-v2
    [*] --> Received
```

### Derived Order Rules
```mermaid
flowchart TD
    C --> D[Collected]
```

### QR Scanning Fallback
```mermaid
sequenceDiagram
    S->>PC: Open bag record; same actions as after a scan
```

### Domain Model
```mermaid
flowchart TD
    D --> E[Audit trail]
```
"""


def _gap_session(tmp_path):
    session = tmp_path / "sess-gap"
    session.mkdir(parents=True, exist_ok=True)
    for name in ("process_diagram.png", "process_diagram_2.png", "process_diagram_4.png",
                 "process_diagram_6.png"):
        (session / name).write_bytes(b"\x89PNG")
    return session


def test_diagram_png_names_is_positional_across_a_missing_render(tmp_path):
    pdf = _load_pdf_module()
    session = _gap_session(tmp_path)
    assert pdf._diagram_png_names(session) == [
        "process_diagram.png",
        "process_diagram_2.png",
        None,
        "process_diagram_4.png",
        None,
        "process_diagram_6.png",
    ]


def test_a_failed_diagram_render_does_not_truncate_the_rest(tmp_path):
    pdf = _load_pdf_module()
    session = _gap_session(tmp_path)
    names = pdf._diagram_png_names(session, "process_diagram.png")
    md = "# Laundry Shop\n\n## Process Diagram\n\nplaceholder\n"
    out = pdf.embed_diagram(md, names, CANVAS)

    assert out.count("```mermaid") == 6, "every canvas diagram keeps its source"
    assert out.count("![") == 4, "only the four diagrams that rendered get an image"
    for png in ("process_diagram.png", "process_diagram_2.png", "process_diagram_4.png",
                "process_diagram_6.png"):
        assert f"({png})" in out, f"{png} was dropped from the deliverable"

    lines = out.splitlines()
    qr = next(i for i, line in enumerate(lines) if "QR Scanning Fallback" in line)
    nearby = [line for line in lines[qr:qr + 4] if line.startswith("![")]
    assert not nearby, "the sixth PNG was attached to the fifth diagram after the gap"


def test_split_glued_headings_recovers_a_missing_section():
    pdf = _load_pdf_module()
    md = (
        "# Spec\n\n"
        "## 3. Objectives\n"
        "Keep records current.## 4. Functional Requirements\n"
        "### 4.1 Order management\n"
        "Text ends.## 6. Use Cases\n"
        "### UC-01: Create an order\n"
    )
    fixed, splits = pdf.split_glued_headings(md)
    assert splits == 2
    headings = [l for l in fixed.splitlines() if l.startswith("#")]
    assert "## 4. Functional Requirements" in headings
    assert "## 6. Use Cases" in headings
    # table rows, code fences and inline code spans are never split
    untouched = pdf.split_glued_headings(
        "| id | # label |\n```\ninline ## not a heading\n```\n"
        "See the `## literal` marker in the notes.\n"
    )[0]
    assert untouched.count("\n##") == 0

def test_story_write_bounds_a_runaway_mu_pdf_layout(tmp_path):
    """A table row taller than the content box makes MuPDF place() never return
    more=False. The writer must stop and say so instead of hanging finalize."""
    pdf = _load_pdf_module()
    md = "# Stall probe\n\n" + "\n".join(
        f"## Section {i}\n\n| A | B |\n|---|---|\n"
        + "".join(f"| {'word ' * 1200} | row {j} |\n" for j in range(6))
        for i in range(6)
    )
    spec = tmp_path / "spec.md"
    spec.write_text(md, encoding="utf-8")
    body = pdf._markdown_to_html(md, tmp_path)
    rectfn = lambda n, f: ((0, 0, pdf._PAGE_W, pdf._PAGE_H),
                           (pdf._MARGIN, pdf._MARGIN,
                            pdf._PAGE_W - pdf._MARGIN, pdf._PAGE_H - pdf._MARGIN), None)
    with pytest.raises(RuntimeError) as exc:
        pdf._story_write(fitz.Story(f"<body>{body}</body>"), None, rectfn)
    assert "MuPDF Story" in str(exc.value)


def test_flatten_tables_keeps_every_cell_text():
    pdf = _load_pdf_module()
    html = ("<table><tr><th>Requirement</th><th>Description</th></tr>"
            "<tr><td>FR-001</td><td>Scan the QR tag at check-in.</td></tr>"
            "<tr><td>FR-002</td><td>Notify R&amp;D staff by SMS.</td></tr></table>")
    flat = pdf._flatten_tables(html)
    assert "<table" not in flat
    for fragment in ("FR-001", "Scan the QR tag at check-in.",
                     "FR-002", "Notify R&amp;D staff by SMS.", "Requirement"):
        assert fragment in flat, f"{fragment} lost while flattening"
    assert "R&amp;amp;D" not in flat

    split = pdf._split_long_table_rows(
        "<table><tr><th>Requirement</th><th>Description</th></tr>"
        "<tr><td>FR-003</td><td>R&amp;D " + ("word " * 150) + "</td></tr></table>"
    )
    assert "FR-003" in split and "R&amp;D" in split
    assert "R&amp;amp;D" not in split


def test_pdf_export_survives_a_table_mu_pdf_cannot_paginate(tmp_path):
    """The pathological table still produces a deliverable: tables fall back to
    paragraph layout rather than the export failing or hanging."""
    pdf = _load_pdf_module()
    md = ("# Stall probe\n\n## 1. Functional Requirements\n\n"
          "| Requirement | Description |\n|---|---|\n"
          + "".join(f"| FR-{i:03d} | {'word ' * 900}|\n" for i in range(8))
          + "\n## 2. Glossary\n\n| Term | Definition |\n|---|---|\n| QR | Quick Response |\n")
    spec = tmp_path / "spec.md"
    spec.write_text(md, encoding="utf-8")
    result = pdf._pymupdf_export(spec, None, tmp_path / "out.pdf", title="Stall probe")
    assert result["status"] == "ok", result
    doc = fitz.open(tmp_path / "out.pdf")
    text = "".join(page.get_text() for page in doc)
    pages = doc.page_count
    doc.close()
    assert pages > 1
    assert "FR-000" in text and "Quick Response" in text, "table content was dropped"

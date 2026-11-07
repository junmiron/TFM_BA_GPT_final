"""The Typst deliverable renderer: cover page, linked Contents, proportional
table columns, bundled Inter font - and the PyMuPDF fallback when the Typst
toolchain is not installed.

Run with:  python -m pytest -q tests/test_typst_render.py
"""

import importlib.util
import re
from pathlib import Path

import pytest

fitz = pytest.importorskip("pymupdf", reason="PyMuPDF is required for PDF QA and the fallback")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_SERVER = PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py"
TYPST_RENDER = PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "typst_render.py"

SPEC = """# Laundry Shop Staff App v1 — Functional Requirements Specification

## 1. Title Page / Document Information

**Project Name:** Laundry Shop Staff App v1
**Version:** 1.0
**Date:** 2026-11-05
**Document Status:** Draft Functional Specification
**Prepared By:** Business Analysis Team

## 2. Functional Requirements

| ID | Requirement | Description | Acceptance criteria | Priority |
|---|---|---|---|---|
| FR-01.1 | Check-in | Each bag gets a unique QR tag attached at check-in; the app records the staff ID, timestamp and bag count so the queue is visible from the first scan. | The tag ID appears in the bag list within 5 seconds of the scan. | Must |
| FR-01.2 | Stage scan | Staff scan the tag at every stage transition (washing, drying, folding, ready). | Each scan updates the stage and the alert list within 5 seconds. | Must |

## 3. Process Diagram

![Process Diagram](process_diagram.png){ width=95% }

```mermaid
flowchart TD
  A[Check-In] --> B[In Cleaning]
  B --> C[Ready for Pickup]
```
"""


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_session(tmp_path: Path) -> Path:
    session = tmp_path / "sess-typst"
    session.mkdir(parents=True, exist_ok=True)
    (session / "functional_specification.formatted.md").write_text(SPEC, encoding="utf-8")
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.draw_rect((50, 50, 550, 350), color=(0, 0, 0), fill=(0.9, 0.95, 1.0))
    page.get_pixmap().save(session / "process_diagram.png")
    doc.close()
    return session


def test_metadata_extracted_from_title_page():
    mod = _load("typst_render", TYPST_RENDER)
    meta = mod.extract_metadata(SPEC, "Fallback Title")
    assert meta["title"] == "Laundry Shop Staff App v1"
    assert meta["version"] == "1.0"
    assert meta["date"] == "2026-11-05"
    assert meta["status"] == "Draft Functional Specification"
    assert meta["author"] == "Business Analysis Team"


def test_mermaid_fences_are_stripped():
    mod = _load("typst_render", TYPST_RENDER)
    cleaned = mod.strip_mermaid_fences(SPEC)
    assert "flowchart TD" not in cleaned
    assert "![Process Diagram](process_diagram.png)" in cleaned


def test_equal_columns_are_replaced_with_proportional_ones():
    """pandoc gives every column of a 5-column FR table 20%, which wraps the
    long description cell every two or three words. The post-processor must
    make the columns proportional to their content and keep them summing to
    100%."""
    mod = _load("typst_render", TYPST_RENDER)
    typst = (
        "#table(\n"
        "  columns: (20%, 20%, 20%, 20%, 20%),\n"
        "  table.header([ID], [Requirement], [Description], [Acceptance criteria], [Priority],),\n"
        "  [FR-01.1], [Check-in], [Each bag gets a unique QR tag attached at check-in; "
        "the app records the staff ID, timestamp and bag count so the queue is visible "
        "from the first scan.], [Tag appears in the list within 5 seconds.], [Must],\n"
        ")\n"
    )
    fixed = mod.fix_table_columns(typst)
    widths = [int(w) for w in re.findall(r"(\d+)%", fixed)]
    assert len(widths) == 5
    assert sum(widths) == 100
    assert widths[2] > widths[4]  # description wider than priority
    assert 'fill: (x, y) =>' in fixed
    assert "fill: white" in fixed  # header text readable on the dark row
    assert "columns: (20%, 20%, 20%, 20%, 20%)" not in fixed


def test_markdown_tables_are_chunked_to_page_size():
    """pandoc wraps every table in an atomic Typst figure, so a table taller
    than one page overflows past the bottom margin and loses rows. The
    Markdown pre-pass must split long tables into page-sized chunks, each with
    its own header, without dropping any row."""
    mod = _load("typst_render", TYPST_RENDER)
    rows = [
        f"| FR-02.{i} | If the scanned tag does not match the bag the staff "
        f"member intends to update, the app warns the user and requires "
        f"confirmation before any status change is saved. | Must | "
        f"Adopted default | Risk R-{i} mitigation |"
        for i in range(1, 25)
    ]
    md = "### 4.2 FR-02\n\n| ID | Requirement | Priority | Status | Source |\n" \
         "|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    chunked = mod._split_markdown_tables(md)
    tables = chunked.count("| ID | Requirement | Priority | Status | Source |")
    assert tables >= 2
    kept = sum(1 for line in chunked.split("\n") if line.startswith("| FR-02."))
    assert kept == 24
    for line in chunked.split("\n"):
        if line.startswith("| FR-02."):
            assert line.count("|") == 6


def test_standalone_hr_lines_are_normalized_for_pandoc():
    """pandoc reads a standalone `---` following a pipe table as the separator
    of a headerless simple table and swallows everything up to the next `---`
    into a single column - headings, quotes and real tables alike. Standalone
    rules must become `***`; table separators and setext underlines stay
    untouched."""
    mod = _load("typst_render_hr", TYPST_RENDER)
    md = (
        "| System | Type |\n|---|---|\n| iOS | Native |\n\n\n---\n"
        "# 3. Functional Requirements\n\nHeading text\n---\n"
    )
    fixed = mod.normalize_horizontal_rules(md)
    assert fixed.count("***") == 1          # the lone section rule only
    assert "|---|---|" in fixed            # pipe-table separator untouched
    assert "Heading text\n---" in fixed    # setext underline untouched


HR_SPEC = """# WashLoop — Functional Requirements Specification

**Project Name:** WashLoop
**Version:** 1.0

## 2.3 Systems & Platforms

| System | Type | Notes |
|---|---|---|
| iOS app | Native | App Store distribution |
| Existing POS | External system | Pricing sync |

---
# 3. Functional Requirements

> **Priority scheme:** MoSCoW.

## 3.1 Ordering

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | The system shall accept orders. | Must |
| FR-02 | The system shall confirm pickup windows. | Should |

---
# 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | Response time under 2 s |
"""


@pytest.mark.skipif(not _load("typst_render_hr2", TYPST_RENDER).engines_available(),
                    reason="typst/pandoc not installed (run scripts/install_render_tools.py)")
def test_hr_separated_sections_stay_headings_not_table_cells(tmp_path):
    """Regression: pandoc folded everything between two `---` rules into one
    headerless 1-column table, shredding the sections and ballooning the page
    count. Headings must stay headings and the rules must stay dividers."""
    mod = _load("typst_render_hr3", TYPST_RENDER)
    session = tmp_path / "sess-hr"
    session.mkdir()
    (session / "spec.md").write_text(HR_SPEC, encoding="utf-8")
    result = mod.render(session / "spec.md", session / "spec.pdf")
    assert result["status"] == "ok", result.get("message")
    assert result["pages"] <= 8
    body = mod._markdown_to_typst(
        mod.normalize_horizontal_rules(HR_SPEC), session, mod.find_binary("pandoc")
    )
    assert "\\# 3. Functional" not in body
    assert re.search(r"(?m)^= 3\. Functional Requirements", body)
    assert "#divider()" in body


def test_priority_is_not_wider_than_status_and_source():
    """The FR tables' Priority column only ever holds Must/Should. Content
    max-lengths once made it wider than Status/Source, leaving big whitespace
    next to 'Must' while 'Confirmed' hyphen-wrapped into slivers. Priority
    must stay the narrow column and Status/Source must get readable room."""
    mod = _load("typst_render", TYPST_RENDER)
    typst = (
        "#table(\n"
        "  columns: (20%, 20%, 20%, 20%, 20%),\n"
        "  table.header([ID], [Requirement], [Priority], [Status], [Source],),\n"
        "  table.hline(),\n"
        + "".join(
            "    [FR-03.%d], [Bags belonging to the same customer may hold "
            "different statuses at the same time, for example one Ready for "
            "Pickup while another is Washing and a third is Drying.], [Must], "
            "[Adopted default (R-7)], [Blocked Decisions],\n" % i
            for i in range(1, 6)
        )
        + ")\n"
    )
    fixed = mod.fix_table_columns(typst)
    widths = [int(w) for w in re.findall(r"(\d+)%", fixed)]
    assert len(widths) == 5 and sum(widths) == 100
    assert widths[2] <= widths[3] <= widths[1]   # priority < status < requirement
    assert widths[2] <= widths[4]                # priority not wider than source
    assert widths[3] >= 12 and widths[4] >= 12   # status/source stay readable
    # each column must fit its longest single word without hyphenating
    longest = [7, 11, 6, 9, 10]  # FR-03.1 / different / Must / Confirmed / Decisions
    for w, word in zip(widths, longest):
        assert w * _chars_per_100(mod) >= word


def _chars_per_100(mod):
    """Chars that fit in 1% of the content width (the renderer's own metric)."""
    return (mod._CONTENT_WIDTH_PT / 100 - mod._CELL_PAD_PT / 100) / mod._GLYPH_ADVANCE_PT


def test_table_figures_are_unwrapped_and_styled():
    """Every pandoc table figure must be unwrapped into a bare #table so Typst
    can split it at row boundaries with the header repeated, instead of
    clipping an atomic figure past the bottom margin."""
    mod = _load("typst_render", TYPST_RENDER)
    short = (
        "#figure(\n"
        "  align(center)[#table(\n"
        "    columns: (20%, 20%, 20%, 20%, 20%),\n"
        "    table.header([ID], [Requirement], [Priority], [Status], [Source],),\n"
        "    table.hline(),\n"
        "    [FR-02.1], [Staff can scan a bag's QR tag.], [Must], [Confirmed], [Overview],\n"
        "  )]\n"
        "  , kind: table\n"
        ")\n"
    )
    fixed = mod.fix_table_columns(short)
    assert "#figure(" not in fixed
    assert "table(" in fixed and "table.header(" in fixed
    assert "set text(hyphenate: false)" in fixed  # no mid-word splits in cells
    widths = [int(w) for w in re.findall(r"(\d+)%", fixed)]
    assert len(widths) == 5 and sum(widths) == 100

    tall = (
        "#figure(\n"
        "  align(center)[#table(\n"
        "    columns: (20%, 20%, 20%, 20%, 20%),\n"
        "    table.header([ID], [Requirement], [Priority], [Status], [Source],),\n"
        "    table.hline(),\n"
        + "".join(
            "    [FR-02.%d], [If the scanned tag does not match the bag the staff "
            "member intends to update, the app warns the user and requires "
            "confirmation before any status change is saved.], [Must], "
            "[Adopted default], [Risk R-%d mitigation],\n" % (i, i)
            for i in range(1, 31)
        )
        + "  )]\n"
        "  , kind: table\n"
        ")\n"
    )
    fixed = mod.fix_table_columns(tall)
    assert "#figure(" not in fixed
    assert "table.header(" in fixed
    assert "[FR-02.30]" in fixed


@pytest.mark.skipif(not _load("typst_render", TYPST_RENDER).engines_available(),
                    reason="typst/pandoc not installed (run scripts/install_render_tools.py)")
def test_typst_render_produces_cover_toc_and_linked_body(tmp_path):
    mod = _load("typst_render", TYPST_RENDER)
    session = _make_session(tmp_path)
    result = mod.render(session / "functional_specification.formatted.md",
                        session / "functional_specification.pdf")
    assert result["status"] == "ok", result.get("message")
    assert result["engine"] == "typst"
    assert result["pages"] >= 3
    assert result["images"] >= 1
    assert result["toc_entries"] >= 4
    assert result["raw_mermaid"] == 0
    assert any("Inter" in font for font in result["fonts"])

    doc = fitz.open(str(session / "functional_specification.pdf"))
    try:
        cover = doc[0].get_text()
        assert "BUSINESS ANALYSIS" in cover
        assert "Laundry Shop Staff App v1" in cover
        assert "Contents" in doc[1].get_text()
        assert "Page 3 of" in doc[2].get_text()  # running footer past the cover
        # The body headings are real PDF bookmarks (Typst's outline links).
        assert any("Functional Requirements" in entry[1] for entry in doc.get_toc())
    finally:
        doc.close()

    # The intermediate Typst files must not linger in the session folder.
    assert not (session / "__tfm_main.typ").exists()
    assert not (session / "__tfm_body.typ").exists()
    assert not (session / "__tfm_body.md").exists()


def test_render_pdf_deliverable_falls_back_when_binaries_missing(tmp_path, monkeypatch):
    """On a machine without typst/pandoc the deliverable must still be produced
    by the PyMuPDF Story renderer rather than failing the terminate stage."""
    pdf_mod = _load("pdf_format_mcp_server", PDF_SERVER)
    monkeypatch.setattr(pdf_mod, "_typst_render_module", lambda: None)
    session = _make_session(tmp_path)
    result = pdf_mod.render_pdf_deliverable(session, "functional_specification.formatted.md",
                                           "functional_specification.pdf")
    assert result["status"] == "ok"
    assert result["engine"] == "pymupdf"
    assert "fallback" in result.get("note", "").lower()
    assert (session / "functional_specification.pdf").is_file()


def test_html_deliverable_has_sidebar_cover_and_dark_table_headers(tmp_path):
    pdf_mod = _load("pdf_format_mcp_server", PDF_SERVER)
    session = _make_session(tmp_path)
    result = pdf_mod.build_html_deliverable(session, "functional_specification.formatted.md",
                                           "functional_specification.html")
    assert result["status"] == "ok"
    body = (session / "functional_specification.html").read_text(encoding="utf-8")
    assert '<aside class="toc" aria-label="Document contents">' in body
    assert '<div class="cover">' in body
    assert "sticky" in body and "thead th" in body  # dark repeating table headers
    assert "@media print" in body and "aside.toc { display: none; }" in body
    assert "IntersectionObserver" in body  # scroll-spy highlight
    assert result["toc_entries"] >= 3
    # The H1 title lives in the cover header, not twice in the document.
    assert body.count('<h1 id=') <= 1
    assert "<details>" in body  # Mermaid source kept collapsed for the web version


def _tall_diagram_png(session: Path) -> Path:
    from PIL import Image
    png = session / "process_diagram.png"
    Image.new("RGB", (511, 2096), "white").save(png)
    return png


def test_tall_diagram_is_split_into_page_sized_bands(tmp_path):
    mod = _load("typst_render_unit", TYPST_RENDER)
    session = tmp_path / "sess-bands"
    session.mkdir()
    _tall_diagram_png(session)
    md = "## 3. Process Diagram\n\n![Process Diagram](process_diagram.png){ width=95% }\n"

    fixed = mod._fit_diagram_images(md, session)
    band_names = re.findall(r"\((process_diagram_band\d+\.png)\)", fixed)
    assert band_names, "tall diagram was not split into bands"
    assert "(part 1 of " in fixed
    for name in band_names:
        from PIL import Image
        with Image.open(session / name) as img:
            w, h = img.size
        rendered_pt = h * (469.0 * 95 / 100) / w
        assert rendered_pt <= 706.0 - 40.0, f"band {name} still exceeds the page box"
    # bands must cover the whole original height (overlap allowed, gaps not)
    heights = []
    from PIL import Image
    for name in band_names:
        with Image.open(session / name) as img:
            heights.append(img.size[1])
    assert sum(heights) >= 2096


def test_diagram_that_fits_one_page_is_left_alone(tmp_path):
    mod = _load("typst_render_unit2", TYPST_RENDER)
    session = tmp_path / "sess-fit"
    session.mkdir()
    from PIL import Image
    Image.new("RGB", (600, 400), "white").save(session / "process_diagram.png")
    md = "![Process Diagram](process_diagram.png){ width=95% }"
    assert mod._fit_diagram_images(md, session) == md


def test_rendered_pdf_has_no_clipped_diagram_images(tmp_path):
    session = _make_session(tmp_path)
    _tall_diagram_png(session)  # replace the small fixture diagram with a tall one
    result = _load("typst_render_it", TYPST_RENDER).render(
        session / "functional_specification.formatted.md",
        session / "functional_specification.pdf",
        title="Laundry Shop Staff App v1",
    )
    if result.get("status") != "ok":
        pytest.skip(f"typst toolchain unavailable: {result.get('message')}")
    assert result["oversized_images"] == 0, f"images taller than the page box: {result['oversized_images']}"
    assert result["images"] >= 1

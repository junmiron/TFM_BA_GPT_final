#!/usr/bin/env python3
"""
Final Deliverable MCP Server (FastMCP) — patched
- Formats the spec (tables + diagram section)
- Exports to PDF with:
  * Pandoc Markdown + attributes + raw_tex
  * resource-path + cwd=session_dir (so relative images resolve)
  * Preprocessing to turn standalone hrules into \newpage
  * Inject \tableofcontents + \newpage at top (instead of --toc)
  * Page break before "## Process Diagram"

Tools:
  - format_spec(session_dir, md, diagram, out)
  - export_pdf(session_dir, md, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)
  - format_and_export(session_dir, md, diagram, md_out, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)
"""

from __future__ import annotations
import os
import threading 
import datetime

import argparse
import io
from html import escape as _html_escape, unescape as _html_unescape
import re
import shlex
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Dict
from fastmcp import FastMCP

# Session experience indexing lives in lib/experience_indexer.py; this server
# deliberately carries no chromadb or embedding-model code (the old
# save_experience_chroma tool indexed every session with sentence_transformers
# and timed out in finalize).

# ------------------------------ path guard ------------------------------
def resolve_under_allowed(path: str | Path, allowed: List[Path], project_root: Path | None = None) -> Path:
    raw = str(path)
    # Support alias and relatives against project_root
    if project_root:
        if raw.startswith("project_root/"):
            raw = raw.split("project_root/", 1)[1]
        if not os.path.isabs(raw):
            p = (project_root / raw).expanduser().resolve()
        else:
            p = Path(raw).expanduser().resolve()
    else:
        p = Path(raw).expanduser().resolve()
    # Allow either any explicit allowed dir OR the project_root itself
    candidates = allowed + ([project_root] if project_root and project_root not in allowed else [])
    for root in candidates:
        try:
            p.relative_to(root)
            return p
        except Exception:
            continue
    raise ValueError(f"Path not in allowed directories: {p}")

# ------------------------------ helpers ------------------------------

def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def find_section(md: str, heading_regex: str, stop_at_level: int = 3) -> tuple[int, int]:
    """Find a section by heading regex. Return (start_idx, end_idx) in chars.
    stop_at_level controls the next heading level (##/###) that ends the section.
    If not found, return (-1, -1).

    Real specs number their headings ("### 3.1 In Scope") and sometimes bold
    them ("### **In-Scope Functionality:**"), so the optional number/bold prefix
    is part of the match - without it the section is never found and the BR/FR
    tables are silently skipped.
    """
    m = re.search(
        rf"(?im)^(?P<hashes>#+)\s*(?:\d+[.)]?\s+)?\**\s*(?:{heading_regex})\s*\**\s*$",
        md,
    )
    if not m:
        return -1, -1
    start = m.end()
    level = len(m.group("hashes"))
    # A section runs to the next heading of the SAME level or higher. Using
    # stop_at_level alone made a "## 3. Functional Requirements" section end at
    # its first "### 3.1" subsection, so the tables below it were never seen.
    stop = max(1, min(level, stop_at_level))
    pat = rf"(?im)^#{{1,{stop}}}\s+"
    n = re.search(pat, md[start:])
    end = start + n.start() if n else len(md)
    return start, end

def parse_numbered_list(block: str) -> list[dict]:
    """Parse a numbered list into [{'title': str, 'bullets': [str, ...]}, ...]."""
    lines = block.splitlines()
    items = []
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*\d+[\.)]\s+(.*)$", lines[i])
        if m:
            title = m.group(1).rstrip().rstrip(":")
            sub = []
            i += 1
            while i < len(lines):
                if re.match(r"^\s*\d+[\.)]\s+", lines[i]) or re.match(r"^\s*#", lines[i]):
                    break
                sb = re.match(r"^\s*[-*+]\s+(.*)$", lines[i])
                if sb:
                    sub.append(sb.group(1).strip())
                elif lines[i].strip():
                    if sub:
                        sub[-1] += " " + lines[i].strip()
                    else:
                        title += " " + lines[i].strip()
                i += 1
            items.append({"title": title, "bullets": sub})
        else:
            i += 1
    return items

def build_requirements_table(items: list[dict], id_prefix: str = "BR") -> str:
    rows = [
        "| Business Requirement ID | Description |",
        "| --- | --- |",
    ]
    for idx, it in enumerate(items, 1):
        br_id = f"{id_prefix}{idx}"
        desc = it["title"]
        if it["bullets"]:
            desc = desc.rstrip(":") + ": " + "; ".join(it["bullets"])
        desc = desc.replace("|", "\\|")
        rows.append(f"| {br_id} | {desc} |")
    return "\n".join(rows) + "\n"


_ID_CELL_RE = re.compile(r"^[A-Za-z]{1,4}[-_. ]?\d+(?:[-.]\d+)*$")


def parse_markdown_table(block: str) -> list[dict]:
    """Extract requirement rows from Markdown tables in *block*.

    Specs written as tables ("| FR-1.1 | Staff must create an order |") are as
    common as numbered lists; without this the BR/FR tables come out empty.
    Each table's header row is dropped (it is the line just above the
    separator), and a leading ID cell is dropped so the description is not
    duplicated.
    """
    rows: list[dict] = []
    prev_was_row = False
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            prev_was_row = False
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line):  # separator: the row above is a header
            if prev_was_row:
                rows.pop()
            prev_was_row = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
        if not cells:
            prev_was_row = False
            continue
        if len(cells) > 1 and _ID_CELL_RE.match(cells[0]):
            title, extra = cells[1], cells[2:]
        else:
            title, extra = cells[0], cells[1:]
        rows.append({"title": title, "bullets": extra})
        prev_was_row = True
    return rows


def parse_subsection_list(block: str) -> list[dict]:
    """Parse `### Heading` subsections, or a plain bullet list, into items.

    Specs that use numbered lists or tables are handled by the other parsers.
    A writer that structures a section as `### 4.1 Order Registration` with
    bullet details, or simply as a flat list of bullets, yields nothing to those
    parsers, so the BR/FR tables silently come out empty. Each `###` heading
    becomes one item with its bullets as details; a bullet at the top level with
    no heading becomes an item of its own.
    """
    lines = block.splitlines()
    items: list[dict] = []
    current: dict | None = None
    for line in lines:
        if re.match(r"^\s*#{3,6}\s+", line):
            if current and (current["title"] or current["bullets"]):
                items.append(current)
            title = re.sub(r"^\s*#+\s*(?:\d+(?:\.\d+)*[.)]?\s+)?", "", line).strip().strip("*").strip()
            current = {"title": title, "bullets": []}
            continue
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if bullet:
            text = bullet.group(2).strip()
            if current is not None:
                current["bullets"].append(text)
            else:
                items.append({"title": text, "bullets": []})
        elif current is not None and line.strip() and not re.match(r"^\s*\|", line):
            if current["bullets"]:
                current["bullets"][-1] += " " + line.strip()
            else:
                current["title"] += " " + line.strip()
    if current and (current["title"] or current["bullets"]):
        items.append(current)
    return items


def parse_requirements(block: str) -> list[dict]:
    """Numbered list first, Markdown table as fallback, then `###` subsections."""
    items = parse_numbered_list(block)
    if not items:
        items = parse_markdown_table(block)
    if not items:
        items = parse_subsection_list(block)
    return items

def ensure_in_scope_requirements_table(md: str) -> tuple[str, int]:
    # Specs name this section "In-Scope", "Scope", or "Purpose & Scope" — the
    # old regex only matched the first, so business requirements came out empty.
    start, end = find_section(md, r".*\b(?:In-?Scope|Purpose and Scope|Scope)\b.*", stop_at_level=3)
    if start == -1:
        return md, 0
    block = md[start:end]
    items = parse_requirements(block)
    if not items:
        return md, 0
    table = "\n### Business Requirements\n\n" + build_requirements_table(items) + "\n"
    updated = md[:end] + table + md[end:]
    return updated, len(items)


# -------- Functional Requirements mapping (FR -> BR) --------

def _extract_br_ids_from_in_scope(md: str) -> list[str]:
    # Same broad heading match as ensure_in_scope_requirements_table: without
    # it, a "Purpose and Scope" section yields no BR ids and the FR mapping
    # table's Business Requirement column comes out blank.
    start, end = find_section(md, r".*\b(?:In-?Scope|Purpose and Scope|Scope)\b.*", stop_at_level=3)
    if start == -1:
        return []
    items = parse_requirements(md[start:end])
    return [f"BR{i}" for i in range(1, len(items) + 1)]

def _strip_inline_br_tags(text: str) -> tuple[str, str | None]:
    """Return (clean_text, br_id_or_none). Detects forms like [BR1] or (BR: BR1)."""
    m = re.search(r"\(\s*BR\s*:\s*(BR\d+)(?:\s*,\s*BR\d+)*\s*\)", text)
    if m:
        br = m.group(1)
        clean = text.replace(m.group(0), "").strip()
        return clean, br
    m = re.search(r"\[(BR\d+)\]", text)
    if m:
        br = m.group(1)
        clean = re.sub(r"\[(BR\d+)\]", "", text).strip()
        return clean, br
    m = re.search(r"\b(BR\d+)\b", text)
    if m:
        br = m.group(1)
        clean = re.sub(r"\bBR\d+\b", "", text).strip()
        return clean, br
    return text, None

def build_fr_table(md: str, fr_items: list[dict]) -> tuple[str, int]:
    """Build the FR mapping table using inline BR tags when present,
    otherwise map FRi -> BRi by position. Returns (table_md, n_rows)."""
    br_ids = _extract_br_ids_from_in_scope(md)
    rows = [
        "| Business Requirement ID | Functional Requirement ID | Description |",
        "| --- | --- | --- |",
    ]
    count = 0
    for idx, it in enumerate(fr_items, 1):
        fr_id = f"FR{idx}"
        desc, inline = _strip_inline_br_tags(it["title"])
        br_id = inline if inline else (br_ids[idx - 1] if idx - 1 < len(br_ids) else "")
        desc = desc.replace("|", "\\|")
        rows.append(f"| {br_id} | {fr_id} | {desc} |")
        count += 1
    return "\n".join(rows) + "\n", count

def ensure_functional_requirements_table(md: str) -> tuple[str, int]:
    """Find '## Functional Requirements' and append a mapping table below it.
    If a table with the right header already exists in that section, do nothing."""
    start, end = find_section(md, r"Functional Requirements", stop_at_level=3)
    if start == -1:
        return md, 0
    section = md[start:end]
    if "| Business Requirement ID | Functional Requirement ID | Description |" in section:
        return md, 0
    fr_items = parse_requirements(section)
    if not fr_items:
        return md, 0
    table, n = build_fr_table(md, fr_items)
    updated = md[:end] + "\n### Functional Requirements Mapping\n\n" + table + md[end:]
    return updated, n

# ------------------------------ formatting core ------------------------------

def split_glued_headings(md: str) -> tuple[str, int]:
    """Break section headings the writer glued onto the end of a paragraph.

    The spec writer sometimes appends a heading straight after the previous
    sentence with no newline - "...basic reporting.## 4. Functional Requirements" -
    so Markdown never sees a heading and the whole section vanishes from the
    outline, the TOC and the PDF (its subsections then look orphaned).
    Lines inside fenced code blocks, table rows and inline code spans are left
    alone.
    """
    out: list[str] = []
    splits = 0
    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or line.lstrip().startswith("|"):
            out.append(line)
            continue
        rest, pieces = line, []
        while True:
            # A run of `#` is a heading only where it starts: `## 4.` inside
            # "text.## 4." qualifies, the second `#` of "## 4." does not.
            match = re.search(r"(?<!#)(?<=\S)#{1,6}\s+\S", rest)
            if not match:
                break
            if rest[:match.start()].count("`") % 2:   # inside an inline code span
                break
            pieces.append(rest[:match.start()])
            rest = rest[match.start():]
            splits += 1
        pieces.append(rest)
        out.extend(pieces)
    return "\n".join(out) + ("\n" if md.endswith("\n") else ""), splits


def ensure_blank_line_before_headings(md: str) -> str:
    """Separate blocks that Markdown's table extension would otherwise merge.

    The `tables` extension keeps consuming lines while they are non-blank, so:
    - a heading written directly after a table row becomes another cell: `## 4.
      Non-Functional Requirements` renders as `<td>## 4. ...</td>` and the section
      disappears from the document and the outline;
    - a paragraph after a table gets folded into the last row, which is how
      `FR-31`..`FR-36` ended up stuffed inside one mapping-table cell.

    Insert a blank line before a heading, and after a table block when the next
    line is not itself a table row. Lines inside fenced code blocks are untouched.
    """
    out: list[str] = []
    in_fence = False
    prev_is_table = False
    for line in md.splitlines():
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fence = not in_fence
        is_table = (not in_fence) and line.lstrip().startswith("|")
        if out and out[-1].strip():
            if not in_fence and re.match(r"^#{1,6}\s", line):
                out.append("")
            elif prev_is_table and not is_table:
                out.append("")
        out.append(line)
        prev_is_table = is_table
    return "\n".join(out) + ("\n" if md.endswith("\n") else "")


def normalize_heading_numbering(md: str) -> tuple[str, list[str]]:
    """Fix duplicated heading numbers without renumbering the whole document.

    The spec writer appends sections out of order and reuses a stale subsection
    number - e.g. emitting `### 8.4 End-to-End Lifecycle Sequence` as the 14th
    item of section 8 - which leaks into the TOC and the rendered PDF. Only a
    heading whose number has already been used in that section is renumbered, to
    the next free number. Deliberate gaps are left alone so cross-references in
    the body ("see Section 4.2") stay valid.
    """
    out: list[str] = []
    fixes: list[str] = []
    top = 0
    seen_subs: dict[int, set[int]] = {}

    for line in md.splitlines():
        m2 = re.match(r"^##\s+(\d+)(\.)?\s+(.*)$", line)
        m3 = re.match(r"^###\s+(\d+)\.(\d+)\s+(.*)$", line)
        if m2:
            number = int(m2.group(1))
            if number in seen_subs and number == top:
                # Duplicate top-level section heading: give it the next number.
                top = max(seen_subs) + 1
                seen_subs.setdefault(top, set())
                fixes.append(f"## {number}. -> ## {top}.")
                line = f"## {top}. {m2.group(3)}"
            else:
                top = number
                seen_subs.setdefault(top, set())
            out.append(line)
        elif m3:
            parent, number = int(m3.group(1)), int(m3.group(2))
            if parent != top:
                # Subsection attached to a section it is not under: re-parent it.
                seen_subs.setdefault(top, set())
                next_num = max(seen_subs[top], default=0) + 1
                seen_subs[top].add(next_num)
                fixes.append(f"### {parent}.{number} -> ### {top}.{next_num}")
                line = f"### {top}.{next_num} {m3.group(3)}"
            elif number in seen_subs[parent]:
                next_num = max(seen_subs[parent], default=0) + 1
                seen_subs[parent].add(next_num)
                fixes.append(f"### {parent}.{number} -> ### {parent}.{next_num}")
                line = f"### {parent}.{next_num} {m3.group(3)}"
            else:
                seen_subs[parent].add(number)
            out.append(line)
        else:
            out.append(line)

    text = "\n".join(out) + ("\n" if md.endswith("\n") else "")
    return text, fixes


def format_document(session_dir: Path, md_file: str, diagram_file: str, out_file: str) -> dict:
    md_path = (session_dir / md_file).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Missing: {md_path}")

    md = load_text(md_path)

    # Build tables
    md, n_br = ensure_in_scope_requirements_table(md)
    md, n_fr = ensure_functional_requirements_table(md)

    # A heading glued to the end of the previous paragraph ("...reporting.## 4.
    # Functional Requirements") is not a heading at all, and the section then
    # disappears from the outline, the TOC and the PDF.
    md, glued = split_glued_headings(md)

    # The writer can emit stale/duplicated subsection numbers, which leak into
    # the TOC and the rendered PDF.
    md, numbering_fixes = normalize_heading_numbering(md)

    # Ensure diagram section. The Mermaid source is kept so the .md/.html
    # deliverables carry the diagram and the code that generated it; the PDF
    # exporter strips the fence because it already embeds the rendered PNG.
    mermaid_source = None
    for candidate in ("process_diagram.mmd", "process_diagram.derived.mmd"):
        source = session_dir / candidate
        if source.exists():
            mermaid_source = load_text(source)
            break
    md = ensure_diagram_section(md, _diagram_png_names(session_dir, diagram_file), mermaid_source)

    out_path = (session_dir / out_file).resolve()
    save_text(out_path, md)
    return {
        "written_to": str(out_path),
        "business_requirements": n_br,
        "functional_requirements": n_fr,
        "glued_headings_split": glued,
        "diagram": diagram_file,
        "numbering_fixes": numbering_fixes,
    }

# ------------------------------ Preprocess for PDF ------------------------------

def _hr_to_newpage(md_text: str) -> str:
    """Convert standalone horizontal rules (---, ***, ___) into \\newpage."""
    out, prev_blank = [], True
    for line in md_text.splitlines():
        stripped = line.strip()
        if prev_blank and stripped in ("---", "***", "___"):
            out.append(r"\newpage")
            out.append("")  # blank line after page break
            prev_blank = True
            continue
        out.append(line)
        prev_blank = (stripped == "")
    return "\n".join(out) + "\n"

def _inject_toc_top(md_text: str, enable: bool) -> str:
    """Insert a TOC at the very top and a page break after it (if enabled)."""
    if not enable:
        return md_text
    if r"\tableofcontents" in md_text:
        return md_text
    return "\\tableofcontents\n\\newpage\n\n" + md_text

def _pagebreak_before_heading(md_text: str, heading_regex: str) -> str:
    """Insert a page break immediately before the first matching heading."""
    return re.sub(rf"(?im)^\s*({heading_regex}\s*)$", r"\\newpage\n\n\1", md_text, count=1)

# ------------------------------ pandoc export ------------------------------

def have_pandoc() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       stdin=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def _extract_title(md_path: Path) -> str:
    """Return the first Markdown heading (or the filename stem) as a PDF title."""
    try:
        for line in md_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip()
    except Exception:
        pass
    return md_path.stem


# --------------------------- Typst render bridge ---------------------------
# The deliverable PDF is typeset with Typst (cover page, linked contents,
# running header/footer, repeating table headers, bundled Inter font) when the
# typst + pandoc binaries are installed; see typst_render.py for the pipeline
# and scripts/install_render_tools.py for the pinned portable binaries. When
# they are missing, every caller falls back to the pure-Python PyMuPDF Story
# renderer below, so the pipeline never depends on external tools.

_TYPST_RENDER_CACHE: Dict[str, Any] = {}


def _typst_render_module():
    """Load the sibling typst_render.py as a library (cached, like _pdf_server_module)."""
    if "module" in _TYPST_RENDER_CACHE:
        return _TYPST_RENDER_CACHE["module"]
    import importlib.util
    path = Path(__file__).with_name("typst_render.py")
    spec = importlib.util.spec_from_file_location("typst_render", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    _TYPST_RENDER_CACHE["module"] = module
    return module


def render_pdf_deliverable(session_dir: Path, md_file: str, pdf_out: str,
                           toc: bool = True, toc_depth: int = 3) -> dict:
    """Render the specification PDF: Typst when available, PyMuPDF otherwise.

    Returns the same result shape as _pymupdf_export (status, engine, pdf,
    pages, images, toc_entries) plus Typst QA fields (fonts, raw_mermaid).
    """
    session_dir = Path(session_dir)
    md_path = (session_dir / md_file).resolve()
    pdf_path = (session_dir / pdf_out).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Missing markdown file: {md_path}")
    title = _extract_title(md_path)

    module = _typst_render_module()
    if module is None:
        pdf = _pymupdf_export(md_path, None, pdf_path, title=title, toc=toc, toc_depth=toc_depth)
        return {**pdf, "note": "typst renderer module unavailable; used PyMuPDF fallback."}
    try:
        if module.engines_available():
            result = module.render(md_path, pdf_path, title=title)
            if result.get("status") == "ok":
                return result
            note = result.get("message") or "Typst render failed"
        else:
            note = "typst/pandoc not installed; used PyMuPDF fallback."
    except Exception as exc:
        note = f"Typst render error ({exc}); used PyMuPDF fallback."
    pdf = _pymupdf_export(md_path, None, pdf_path, title=title, toc=toc, toc_depth=toc_depth)
    return {**pdf, "note": note}


# Pandoc-style image syntax emitted by ensure_diagram_section:
#   ![Process Diagram](process_diagram.png){ width=95% }
# MuPDF's Story has no notion of pandoc attributes, so the "{ width=95% }" tail
# would otherwise be printed as literal text next to an unrendered [image].
_IMG_MD_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)(?:\s*\{[^}]*\})?")

_PAGE_W, _PAGE_H = 595, 842          # A4 in points
_MARGIN = 36
_CONTENT_W = _PAGE_W - 2 * _MARGIN
_CONTENT_H = _PAGE_H - 2 * _MARGIN
# Story silently drops an <img> that cannot fit in the space left on the page,
# so a diagram is capped below the full content height to leave room for the
# heading that precedes it. At exactly _CONTENT_H the tenth diagram in a
# multi-diagram spec disappeared from the PDF.
_IMAGE_MAX_H = _CONTENT_H - 60


def _resolve_image_src(src: str, session_dir: Path) -> Optional[str]:
    """Return a Story-resolvable image name (relative to the archive dir).

    PyMuPDF Story only embeds images that the supplied Archive can find, and an
    absolute Windows path is not resolvable there, so every image is rewritten
    to a path relative to `session_dir`.
    """
    for candidate in (session_dir / src, Path(src)):
        p = candidate.resolve()
        if p.is_file():
            try:
                return p.relative_to(session_dir.resolve()).as_posix()
            except ValueError:
                return p.as_posix()
    return None


def _img_tag(src: str, alt: str, session_dir: Path) -> str:
    """Build an <img> tag with real pixel dimensions (Story scales poorly).

    PyMuPDF's Story hangs when an image is taller than the page content area,
    so the image is scaled to fit within the page box.
    """
    name = _resolve_image_src(src, session_dir)
    if not name:
        return f"<p>[missing image: {src}]</p>"
    try:
        import pymupdf as fitz
        pix = fitz.Pixmap(str(session_dir / name) if not Path(name).is_absolute() else name)
        w, h = pix.width, pix.height
        pix = None
        scale = min(_CONTENT_W / w, _IMAGE_MAX_H / h, 1.0)
        w = max(1, int(w * scale))
        h = max(1, int(h * scale))
        return f'<img src="{name}" width="{w}" height="{h}" alt="{alt}"/>'
    except Exception:
        return f'<img src="{name}" width="{_CONTENT_W}" height="{_CONTENT_H}" alt="{alt}"/>'


def _strip_mermaid_fences(md_text: str) -> str:
    """Drop ```mermaid fences before PDF rendering.

    A Mermaid block is source code: PyMuPDF Story would lay it out as a wall of
    monospaced text, and the rendered PNG is already embedded next to it. The
    HTML deliverable keeps the fence, the PDF does not.

    A line with a language on it opens a fence; only a bare ``` closes one. That
    detail matters when a multi-diagram canvas is nested inside a single fence -
    treating the inner ```mermaid lines as closers mis-pairs the fences and the
    diagram source leaks into the PDF as prose.
    """
    out, in_fence, fence_lang = [], False, ""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence, fence_lang = True, stripped[3:].strip().lower()
            elif not stripped[3:].strip():
                in_fence = False
            continue
        if in_fence and fence_lang == "mermaid":
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if md_text.endswith("\n") else "")


def _normalise_title(title: str) -> str:
    """A heading compared without its leading section number."""
    return re.sub(r"^\d+[a-z]?\.\s*", "", (title or "").strip()).lower()


_FENCE_OPEN_RE = re.compile(r"^[ \t]*`{3,}[ \t]*([A-Za-z0-9_-]*)[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*`{3,}[ \t]*$")
_HEADING_RE = re.compile(r"^[ \t]*(#{1,6})[ \t]+(.*)$", re.M)
_DIAGRAM_KEYWORDS = (
    "graph", "flowchart", "sequenceDiagram", "classDiagram", "stateDiagram",
    "stateDiagram-v2", "erDiagram", "journey", "gantt", "pie", "mindmap",
    "sankey-beta", "xychart-beta", "block-beta", "quadrantChart", "requirementDiagram",
)


def canvas_diagrams(source: str) -> List[Dict[str, str]]:
    """Split a Mermaid canvas into [{"title": ..., "source": ...}, ...].

    The diagram reviewer keeps the canvas as a Markdown document: a heading, then
    a ```mermaid fence, per diagram. mmdc renders exactly one diagram per
    invocation, and wrapping the whole document in one fence nests the inner
    fences - which is what made the PDF print raw Mermaid source as text.
    """
    diagrams: List[Dict[str, str]] = []
    title = ""
    lines = (source or "").splitlines()
    i = 0
    while i < len(lines):
        opener = _FENCE_OPEN_RE.match(lines[i].strip())
        if opener:
            language = opener.group(1).lower()
            body: List[str] = []
            i += 1
            while i < len(lines) and not _FENCE_CLOSE_RE.match(lines[i].strip()):
                body.append(lines[i])
                i += 1
            i += 1  # consume the closing fence
            text = "\n".join(body).strip()
            is_diagram = language == "mermaid" or any(
                re.match(rf"(?im)^\s*{kw}\b", text) for kw in _DIAGRAM_KEYWORDS
            )
            if text and is_diagram:
                diagrams.append({"title": title, "source": text})
            continue
        heading = _HEADING_RE.match(lines[i])
        if heading:
            title = re.sub(r"^\d+[a-z]?\.\s*", "", heading.group(2).strip())
        i += 1
    if diagrams:
        return diagrams
    body = (source or "").strip()
    return [{"title": title or "Process Diagram", "source": body}] if body else []


def _canvas_heading_titles(source: str) -> set:
    """Every heading title in the canvas document, normalised.

    The canvas carries its own title and a Notes block as well as the diagram
    headings. Those are canvas chrome, not spec content, and they are what the
    reader sees as stray "diagrams as code" once a canvas is pasted into the
    document.
    """
    return {_normalise_title(m.group(2)) for m in _HEADING_RE.finditer(source or "")}


def _canvas_dump_region_end(md: str, start: int, canvas_titles: set) -> int:
    """End of a contiguous canvas dump beginning at `start`.

    Walks heading sections forward while each heading belongs to the canvas
    document, stopping at the first heading the canvas did not produce.
    """
    headings = list(_HEADING_RE.finditer(md, start))
    for index, match in enumerate(headings):
        if _normalise_title(match.group(2)) not in canvas_titles:
            return match.start()
    return len(md)


def _diagram_block(diagrams: List[Dict[str, str]], png_names: List[str]) -> str:
    """One Markdown block per diagram: the rendered PNG, then its Mermaid source.

    The first diagram keeps the plain "Process Diagram" caption; later ones get a
    subheading so the .md, .html and the PDF bookmark tree name each diagram.
    """
    if not diagrams:
        png = png_names[0] if png_names else "process_diagram.png"
        return f"![Process Diagram]({png}){{ width=95% }}\n"

    parts: List[str] = []
    for index, diagram in enumerate(diagrams):
        title = diagram.get("title") or "Process Diagram"
        if title and title != "Process Diagram":
            parts.append(f"### {title}")
        png = png_names[index] if index < len(png_names) else None
        if png:
            alt = "Process Diagram" if index == 0 else title
            parts.append(f"![{alt}]({png}){{ width=95% }}")
        source = diagram.get("source", "").strip()
        if source:
            parts.append("```mermaid\n" + source + "\n```")
    return "\n\n".join(parts) + "\n"


def _drop_duplicate_diagram_sections(md: str, titles: List[str]) -> str:
    """Remove headings that only exist because a canvas got pasted into the spec.

    The Mermaid canvas is itself a Markdown document with a heading per diagram.
    When it was embedded whole, every diagram became its own `## N. Title` section
    with a fence and no rendered image - the "mermaid showing as code" the reader
    sees below the real diagram. Those sections are redundant once the Process
    Diagram section carries each diagram itself.
    """
    wanted = {re.sub(r"^\d+[a-z]?\.\s*", "", t).strip().lower() for t in titles if t}
    if not wanted:
        return md

    headings = list(re.finditer(r"^[ \t]*(#{1,6})[ \t]+(.*)$", md, re.M))
    cuts: List[tuple] = []
    for index, match in enumerate(headings):
        title = re.sub(r"^\d+[a-z]?\.\s*", "", match.group(2).strip()).lower()
        if title not in wanted:
            continue
        level = len(match.group(1))
        end = len(md)
        for nxt in headings[index + 1:]:
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
        body = md[match.end():end]
        has_fence = "```mermaid" in body
        has_image = bool(re.search(r"!\[[^\]]*\]\([^)]*process_diagram", body, re.I))
        if has_fence and not has_image:
            cuts.append((match.start(), end))

    if not cuts:
        return md
    parts, cursor = [], 0
    for start, end in cuts:
        parts.append(md[cursor:start])
        cursor = end
    parts.append(md[cursor:])
    return "".join(parts)


def _section_prose(section: str, drop_titles: Optional[List[str]] = None) -> str:
    """A section's prose with diagram images, fences and diagram headings removed,
    so re-embedding never duplicates them and never loses the writer's own text."""
    wanted = {_normalise_title(t) for t in (drop_titles or []) if t}
    out, in_fence = [], False
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
            elif not stripped[3:].strip():
                in_fence = False
            continue
        if in_fence:
            continue
        if re.match(r"^!\[[^\]]*\]\([^)]*process_diagram[^)]*\)", stripped):
            continue
        if stripped.startswith("%%"):  # Mermaid comment lines are canvas chrome
            continue
        heading = _HEADING_RE.match(line)
        if heading and _normalise_title(heading.group(2)) in wanted:
            continue
        out.append(line)
    return "\n".join(out).strip()


def _diagram_png_names(session_dir: Path, fallback: Optional[str] = None) -> List[Optional[str]]:
    """Every rendered diagram PNG, one slot per canvas diagram, in canvas order.

    `process_diagram.png` is canvas diagram 1, `process_diagram_2.png` is diagram
    2, and so on. The list is positional on purpose: if diagram 5 fails to render
    the slot is `None` rather than absent. Compacting the list would attach
    `process_diagram_6.png` to the fifth diagram and, worse, the old
    walk-until-a-gap loop truncated every diagram after the first failure - a
    ten-diagram canvas ended up with four images in the PDF and HTML.
    """
    session_dir = Path(session_dir)
    highest = 1 if (session_dir / "process_diagram.png").is_file() else 0
    for png in session_dir.glob("process_diagram_*.png"):
        match = re.fullmatch(r"process_diagram_(\d+)\.png", png.name)
        if match:
            highest = max(highest, int(match.group(1)))
    names: List[Optional[str]] = []
    for index in range(1, highest + 1):
        name = "process_diagram.png" if index == 1 else f"process_diagram_{index}.png"
        names.append(name if (session_dir / name).is_file() else None)
    if not any(names) and fallback:
        names = [fallback]
    return names


def embed_diagram(md: str, diagram_names, mermaid_source: Optional[str] = None) -> str:
    """Insert every rendered diagram (and its Mermaid source) into a Markdown document.

    Idempotent and non-destructive: the "Process Diagram" section is rebuilt from
    the canvas each run, so a diagram is never duplicated and a canvas that grew
    extra diagrams shows up in the deliverable. This is what makes the .md
    self-explanatory - the reader sees the PNG and the source that produced it.
    """
    if isinstance(diagram_names, str):
        diagram_names = [diagram_names]
    diagrams = canvas_diagrams(mermaid_source or "")
    block = _diagram_block(diagrams, list(diagram_names))
    canvas_titles = _canvas_heading_titles(mermaid_source or "") | {
        _normalise_title(d["title"]) for d in diagrams
    }

    md = _drop_duplicate_diagram_sections(md, canvas_titles)

    start, end = find_section(md, "Process Diagram", stop_at_level=2)
    if start != -1:
        region_end = _canvas_dump_region_end(md, start, canvas_titles)
        prose = _section_prose(md[start:region_end], canvas_titles)
        section = block + ("\n\n### Diagram notes\n\n" + prose if prose else "")
        return md[:start] + "\n" + section + "\n" + md[region_end:]

    return md.rstrip() + "\n\n## Process Diagram\n\n" + block


def ensure_diagram_section(md: str, diagram_names, mermaid_source: Optional[str] = None) -> str:
    """Same as embed_diagram: one rendered image plus fence per canvas diagram."""
    return embed_diagram(md, diagram_names, mermaid_source)


def _markdown_to_html(md_text: str, session_dir: Path, keep_mermaid: bool = False,
                      img_tag=None) -> str:
    """Markdown -> HTML fragment, with pandoc image attributes turned into tags.

    Mermaid fences are stripped by default: the rendered PNG is already in the
    document and raw diagram source would bloat the PDF. The HTML deliverable
    passes keep_mermaid=True so the source survives as a code block.
    """
    img_tag = img_tag or _img_tag
    md_text = ensure_blank_line_before_headings(md_text)
    if not keep_mermaid:
        md_text = _strip_mermaid_fences(md_text)
    md_text = _IMG_MD_RE.sub(lambda m: img_tag(m.group("src"), m.group("alt"), session_dir), md_text)
    try:
        import markdown as mdlib
        try:
            return mdlib.markdown(md_text, extensions=["tables", "fenced_code", "toc"])
        except Exception:
            return mdlib.markdown(md_text)
    except Exception:
        import html as htmlmod
        return "<pre>" + htmlmod.escape(md_text) + "</pre>"


_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml", ".gif": "image/gif", ".webp": "image/webp"}


def _svg_sibling(path: Path) -> Optional[str]:
    """Inline vector markup when mmdc produced a .svg next to the PNG.

    mmdc scopes its CSS to id="my-svg"; a page with several diagrams would share
    one id, so each figure gets a unique id. The hard-coded max-width from the
    render viewport is dropped - the figure CSS sizes the drawing instead.
    """
    svg = path.with_suffix(".svg")
    if not svg.is_file():
        return None
    try:
        text = svg.read_text(encoding="utf-8")
    except Exception:
        return None
    if "<svg" not in text:
        return None
    uid = "tfm-" + re.sub(r"[^A-Za-z0-9_-]+", "-", path.stem).strip("-")
    text = text.replace("my-svg", uid)
    text = re.sub(r'(?i)\s*style="max-width:[^"]*"', "", text)
    return text


def _inline_img_tag(src: str, alt: str, session_dir: Path) -> str:
    """Embed the diagram in the HTML so the file stands alone.

    Vector SVG (when Mermaid rendered one) beats the raster PNG: labels stay
    crisp at any zoom and browsers print them at full detail. The PDF keeps
    using the PNG unchanged.
    """
    name = _resolve_image_src(src, session_dir)
    if not name:
        return f"<p>[missing image: {src}]</p>"
    path = Path(name) if Path(name).is_absolute() else session_dir / name
    svg = _svg_sibling(path)
    if svg:
        # Scrollable figure: a flowchart can be several thousand pixels tall.
        return f'<figure class="diagram">{svg}</figure>'
    try:
        import base64
        raw = path.read_bytes()
        mime = _MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
        # A flowchart can be several thousand pixels tall. Wrapping it in a
        # scrollable figure keeps the page readable instead of dumping a
        # 3700-pixel image into the middle of the document.
        return (f'<figure class="diagram"><img src="data:{mime};base64,{base64.b64encode(raw).decode()}" '
                f'alt="{alt}"/></figure>')
    except Exception:
        return f'<img src="{name}" alt="{alt}"/>'


_HTML_CSS = """
:root {
  --accent: #2563eb; --accent-soft: #eff6ff; --ink: #111827; --sub: #374151;
  --faint: #9ca3af; --line: #e5e7eb; --bg: #ffffff; --bg-soft: #f9fafb;
  --code-bg: #f3f4f6; --sidebar-w: 22rem;
  --font: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 1.5rem; }
body { margin: 0; font-family: var(--font); font-size: 16px; line-height: 1.65;
       color: var(--ink); background: var(--bg); -webkit-font-smoothing: antialiased; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------- two-column layout with sticky contents sidebar ---------- */
.layout { display: grid; grid-template-columns: var(--sidebar-w) minmax(0, 1fr); min-height: 100vh; }
aside.toc { position: sticky; top: 0; align-self: start; height: 100vh; overflow-y: auto;
            width: var(--sidebar-w); border-right: 1px solid var(--line);
            background: var(--bg-soft); padding: 1.5rem 1.25rem 3rem; }
aside.toc .toc-title { font-size: 0.8rem; font-weight: 700; letter-spacing: 0.06em;
                       text-transform: uppercase; color: var(--faint); margin: 0 0 0.75rem; }
aside.toc ul { list-style: none; margin: 0; padding: 0; }
aside.toc li a { display: block; padding: 0.28rem 0.5rem; border-radius: 6px;
                 color: var(--sub); font-size: 0.9rem; line-height: 1.35;
                 border-left: 2px solid transparent; }
aside.toc li a:hover { background: #eef2ff; color: var(--accent); text-decoration: none; }
aside.toc li a.active { background: var(--accent-soft); color: var(--accent);
                        border-left-color: var(--accent); font-weight: 600; }
aside.toc li.lvl0 a { font-weight: 700; color: var(--ink); margin-top: 0.4rem; }
aside.toc li.lvl1 a { padding-left: 1rem; }
aside.toc li.lvl2 a { padding-left: 2rem; font-size: 0.85rem; }
main { padding: 2.5rem 3rem 5rem; min-width: 0; }

/* ---------- cover header ---------- */
.cover { border-bottom: 3px solid var(--accent); padding-bottom: 1.75rem; margin-bottom: 2.25rem; }
.cover .kicker { font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em;
                 text-transform: uppercase; color: var(--accent); margin: 0 0 0.5rem; }
.cover h1 { font-size: 2.1rem; line-height: 1.15; margin: 0 0 0.35rem; font-weight: 800; }
.cover .subtitle { font-size: 1.15rem; color: var(--sub); margin: 0 0 1.1rem; }
.meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.6rem 1.25rem; margin: 0; }
.meta div { font-size: 0.85rem; }
.meta dt { color: var(--faint); font-size: 0.72rem; text-transform: uppercase;
          letter-spacing: 0.05em; font-weight: 600; }
.meta dd { margin: 0.1rem 0 0; color: var(--ink); font-weight: 500; }
.badge { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px;
         font-size: 0.72rem; font-weight: 700; letter-spacing: 0.02em;
         background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }

/* ---------- prose ---------- */
article h1 { font-size: 1.7rem; font-weight: 800; margin: 2.5rem 0 1rem;
             padding-bottom: 0.4rem; border-bottom: 1px solid var(--line); }
article h2 { font-size: 1.4rem; font-weight: 700; margin: 2.2rem 0 0.8rem; }
article h3 { font-size: 1.15rem; font-weight: 700; margin: 1.7rem 0 0.6rem; color: var(--sub); }
article h4 { font-size: 1rem; font-weight: 700; margin: 1.3rem 0 0.5rem; }
article p { margin: 0.85rem 0; }
article ul, article ol { padding-left: 1.4rem; }
article li { margin: 0.3rem 0; }
article hr { border: none; border-top: 1px solid var(--line); margin: 2rem 0; }
article code { font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
               font-size: 0.86em; background: var(--code-bg); padding: 0.1rem 0.35rem; border-radius: 4px; }
article pre { background: var(--code-bg); border: 1px solid var(--line); border-radius: 8px;
              padding: 0.9rem 1rem; overflow-x: auto; }
article pre code { background: none; padding: 0; }
article img { max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; }
article blockquote { border-left: 3px solid var(--accent); margin: 1rem 0;
                      padding: 0.35rem 1rem; background: var(--accent-soft); color: var(--sub); }
figure.diagram { max-height: 760px; overflow: auto; border: 1px solid var(--line);
                 border-radius: 8px; padding: 12px; margin: 16px 0; }
figure.diagram img { border: none; }
figure.diagram svg { max-width: 100%; height: auto; border: none; }

/* ---------- tables: dark sticky header, zebra rows ---------- */
article table { border-collapse: collapse; width: 100%; font-size: 0.9rem; line-height: 1.5; margin: 1.1rem 0; }
article thead th { position: sticky; top: 0; background: var(--ink); color: #fff;
                    text-align: left; font-weight: 600; padding: 0.55rem 0.7rem; }
article tbody td { padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--line); vertical-align: top; }
article tbody tr:nth-child(even) { background: var(--bg-soft); }
article tbody tr:hover { background: var(--accent-soft); }

details { margin: 1rem 0; }
summary { cursor: pointer; color: var(--accent); font-weight: 600; }

@media print {
  .layout { display: block; }
  aside.toc { display: none; }
  main { padding: 0; }
  article thead th { position: static; background: #eef2f7; color: #111;
                     -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  a { color: inherit; }
  figure.diagram { max-height: none; overflow: visible; }
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  aside.toc { position: static; height: auto; width: auto; border-right: none;
              border-bottom: 1px solid var(--line); }
  main { padding: 1.5rem 1.25rem 3rem; }
  .meta { grid-template-columns: 1fr 1fr; }
}
"""

# Scroll-spy: highlight the sidebar entry for the heading currently in view.
_HTML_JS = """
(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc a'));
  if (!links.length) return;
  var byId = {};
  links.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });
  var headings = document.querySelectorAll('article h1, article h2, article h3, article h4');
  if (!headings.length) return;
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var a = byId[entry.target.id];
      if (!a) return;
      links.forEach(function (l) { l.classList.remove('active'); });
      a.classList.add('active');
    });
  }, { rootMargin: '0px 0px -70% 0px', threshold: 0.1 });
  headings.forEach(function (h) { if (h.id) observer.observe(h); });
})();
"""


def _html_toc(body_html: str, depth: int = 4) -> str:
    """Build sidebar <li> items from the headings the toc extension numbered."""
    items = re.findall(rf'<h([1-{depth}]) id="([^"]+)"[^>]*>(.*?)</h\1>', body_html)
    out = []
    for level, anchor, text in items:
        level = int(level)
        text = re.sub(r"<[^>]+>", "", text).strip()
        if not text or text.lower() == "contents":
            continue
        out.append(f'<li class="lvl{min(level - 1, 2)}"><a href="#{anchor}">{_html_escape(text)}</a></li>')
    return "".join(out)


_META_FIELDS = (
    ("Project Name", "title"),
    ("Version", "version"),
    ("Date", "date"),
    ("Document Status", "status"),
    ("Prepared By", "author"),
)


def _doc_metadata(md_text: str, title: str) -> dict:
    """Cover-header fields parsed from the Title Page section, with defaults."""
    meta = {
        "title": title,
        "subtitle": "Functional Requirements Specification",
        "version": "1.0",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "status": "Draft",
        "author": "Business Analysis Team",
    }
    for label, key in _META_FIELDS:
        match = re.search(rf"\*\*{label}:\*\*\s*(.+)", md_text)
        if match:
            meta[key] = match.group(1).strip().rstrip()
    return meta


def build_html_deliverable(session_dir: Path, md_file: str, out_file: str,
                         diagram_file: Optional[str] = None,
                         title: Optional[str] = None) -> dict:
    """Write a self-contained HTML deliverable from the (formatted) Markdown.

    Layout: sticky Contents sidebar with scroll-spy highlighting, a cover header
    carrying the Title Page metadata, and tables with dark sticky headers. The
    document title from the Markdown H1 is not duplicated in the body - the cover
    header already shows it.
    """
    session_dir = Path(session_dir)
    md_path = (session_dir / md_file).resolve()
    if not md_path.exists() and md_file == "functional_specification.formatted.md":
        # An agent can call export_html without having run format_spec first.
        # Build the formatted doc rather than failing the tool call.
        raw = session_dir / "functional_specification.md"
        if raw.exists():
            format_document(session_dir, "functional_specification.md",
                            diagram_file or "process_diagram.png",
                            "functional_specification.formatted.md")
            md_path = (session_dir / md_file).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Missing: {md_path}")

    md_text = load_text(md_path)
    title = title or _extract_title(md_path)
    body_md = re.sub(r"^\s*#\s+[^\n]*\n", "", md_text, count=1)
    body = _markdown_to_html(body_md, session_dir, keep_mermaid=True, img_tag=_inline_img_tag)
    # Mermaid source reads better collapsed than as a wall of monospaced text.
    body = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<details><summary>Diagram source (Mermaid)</summary><pre>{m.group(1)}</pre></details>',
        body,
        flags=re.S,
    )
    meta = _doc_metadata(md_text, title)
    toc = _html_toc(body)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cover = (
        f'<div class="cover">'
        f'<p class="kicker">Business analysis</p>'
        f'<h1>{_html_escape(meta["title"])}</h1>'
        f'<p class="subtitle">{_html_escape(meta["subtitle"])}</p>'
        f'<dl class="meta">'
        f'<div><dt>Version</dt><dd>{_html_escape(meta["version"])}</dd></div>'
        f'<div><dt>Date</dt><dd>{_html_escape(meta["date"])}</dd></div>'
        f'<div><dt>Status</dt><dd><span class="badge">{_html_escape(meta["status"])}</span></dd></div>'
        f'<div><dt>Prepared by</dt><dd>{_html_escape(meta["author"])}</dd></div>'
        f'<div><dt>Generated</dt><dd>{generated}</dd></div>'
        f'</dl></div>'
    )
    html = (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{_html_escape(title)}</title>'
        f'<meta name="generator" content="TFM_BA_GPT deliverable pipeline">'
        f"<style>{_HTML_CSS}</style></head>"
        f'<body><div class="layout">'
        f'<aside class="toc" aria-label="Document contents">'
        f'<p class="toc-title">Contents</p><ul>{toc}</ul></aside>'
        f'<main>{cover}<article>{body}</article></main>'
        f'</div><script>{_HTML_JS}</script></body></html>'
    )
    out_path = (session_dir / out_file).resolve()
    save_text(out_path, html)
    return {
        "status": "ok",
        "html": str(out_path),
        "bytes": out_path.stat().st_size,
        "toc_entries": toc.count("<li"),
        "images": body.count("<img"),
    }


def _flatten_tables(html: str) -> str:
    """Turn every <table> into label: value paragraphs.

    MuPDF's Story can only lay out a table row that fits inside one page rect.
    A generated requirements table with a 1000-character description cell does
    not fit, and place() then re-emits the same block forever. Rendering the
    same content as paragraphs always paginates, so this is the last-resort
    layout: the words survive, the grid does not.
    """
    out = html
    for table in re.findall(r"<table>.*?</table>", out, flags=re.S):
        rows = re.findall(r"<tr>(.*?)</tr>", table, flags=re.S)
        header = [_html_unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in
                  re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], flags=re.S)] if rows else []
        parts = []
        for row in rows[1:]:
            cells = [_html_unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in
                     re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S)]
            if len(cells) == 1:
                parts.append(f"<p>{_html_escape(cells[0])}</p>")
                continue
            first, rest = cells[0], cells[1:]
            label = header[0] if header else first
            detail = "; ".join(x for x in rest if x)
            parts.append(f"<p><strong>{_html_escape(first)}</strong> "
                         f"{_html_escape(label)}: {_html_escape(detail)}</p>")
        out = out.replace(table, "".join(parts), 1)
    return out


def _split_long_table_rows(html: str, chunk: int = 700) -> str:
    """Break a table row whose text will not fit on one page into several rows.

    MuPDF's Story cannot split a row across pages: it either re-emits the same
    block forever or silently discards it. Writer-generated requirement tables
    regularly put a 1000-character description in one cell, so every long cell is
    chopped into page-sized pieces and the row label is repeated on each piece.
    """
    out = html
    for table in re.findall(r"<table>.*?</table>", out, flags=re.S):
        rows = re.findall(r"<tr>.*?</tr>", table, flags=re.S)
        rebuilt = []
        for index, row in enumerate(rows):
            cells = [_html_unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in
                     re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S)]
            longest = max((len(c) for c in cells), default=0)
            if index == 0 or longest <= chunk:
                rebuilt.append(row)
                continue
            label = cells[0] if len(cells[0]) <= chunk else cells[0][:chunk]
            pieces = []
            for start in range(0, longest, chunk):
                parts = []
                for position, cell in enumerate(cells):
                    piece = label if position == 0 else cell[start:start + chunk]
                    parts.append(f"<td>{_html_escape(piece)}</td>")
                pieces.append("<tr>" + "".join(parts) + "</tr>")
            rebuilt.append("".join(pieces))
        new_table = table
        for old_row, new_row in zip(rows, rebuilt):
            if new_row != old_row:
                new_table = new_table.replace(old_row, new_row, 1)
        out = out.replace(table, new_table, 1)
    return out


def _story_write(story, writer, rectfn, positionfn=None, max_pages=400):
    """Story.write with a hard page cap and a stall guard.

    MuPDF's Story.place() reports more=True with an unchanged filled rect when a
    table row does not fit inside the content rect: it re-emits the same block
    page after page and the built-in write() loop never returns. A 15-section
    spec with 31 tables hung finalize for the whole 600s timeout. Bound the loop
    and raise on a stall so the caller can retry with a layout MuPDF can break.
    """
    dev = None
    page_num = 0
    rect_num = 0
    filled = (0, 0, 0, 0)
    seen_pages = set()
    while page_num < max_pages:
        mediabox, rect, ctm = rectfn(rect_num, filled)
        rect_num += 1
        if mediabox:
            page_num += 1
        more, filled = story.place(rect)
        page_layout = []

        def on_position(position):
            position.page_num = page_num
            # PyMuPDF hands back a Rect for most elements but a bare tuple for
            # table cells, so normalise before hashing.
            page_layout.append((tuple(round(v, 1) for v in position.rect),
                               (position.text or "")[:60]))
            if positionfn:
                positionfn(position)

        story.element_positions(on_position)
        if writer:
            if mediabox:
                if dev:
                    writer.end_page()
                dev = writer.begin_page(mediabox)
            story.draw(dev, ctm)
            if not more:
                writer.end_page()
                dev = None
                break
        else:
            story.draw(None, ctm)
            if not more:
                break

        # MuPDF re-emits the overflowing block forever. Tables are not reported
        # as element positions, so the only reliable signal is a page whose
        # heading layout is identical to one already drawn.
        key = tuple(page_layout)
        if key and key in seen_pages:
            raise RuntimeError(
                f"MuPDF Story repeated a page at {page_num}: a table row is taller "
                f"than the {_CONTENT_H}pt content box"
            )
        seen_pages.add(key)
    else:
        raise RuntimeError(f"MuPDF Story exceeded the {max_pages} page limit")
    return page_num


def _pymupdf_export(md_path: Path, diagram_path: Optional[Path], pdf_path: Path,
                    title: str, toc: bool = True, toc_depth: int = 2) -> dict:
    """
    Pure-Python PDF generation via PyMuPDF (no pandoc/LaTeX required).

    Markdown is converted to HTML and laid out with PyMuPDF's Story engine,
    which paginates automatically and renders tables and embedded images. The
    diagram is embedded through an Archive rooted at the session folder; when
    `toc` is set the page numbers are stabilised with write_stabilized().
    """
    try:
        import pymupdf as fitz  # PyMuPDF
    except Exception as e:
        return {"status": "error", "engine": "pymupdf", "message": f"PyMuPDF not available: {e}"}

    session_dir = md_path.parent
    try:
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        body_html = _markdown_to_html(md_text, session_dir)
    except Exception as e:
        return {"status": "error", "engine": "pymupdf", "message": f"Markdown read failed: {e}"}

    if not re.search(r"^\s*#", md_text, re.M):
        body_html = f"<h1>{title}</h1>\n" + body_html

    # MuPDF's Story cannot break a table row that is taller than the content
    # rect: it either re-emits the block forever (the finalize hang) or silently
    # drops it (a PDF missing whole requirement tables). Long rows are split into
    # page-sized pieces, and _story_write bounds the layout loop so a stall raises
    # instead of hanging the MCP call.
    _PDF_CSS_SAFE = (
        "body{font-family:Helvetica,Arial,sans-serif;font-size:11px;}"
        "table{border-collapse:collapse;width:100%;}"
        "th,td{border:1px solid #888;padding:3px;vertical-align:top;}"
        "h1{font-size:20px;}h2{font-size:16px;}h3{font-size:13px;}"
    )

    def rectfn(rect_num, filled):
        return (0, 0, _PAGE_W, _PAGE_H), (_MARGIN, _MARGIN, _PAGE_W - _MARGIN, _PAGE_H - _MARGIN), None

    def toc_body(positions, content_html):
        entries = [
            p for p in positions
            if p.heading and 1 <= p.heading <= toc_depth and (p.open_close & 1)
            and p.text and p.text.strip().lower() != "contents"
        ]
        if not entries:
            return content_html
        items = "".join(
            f'<li style="margin-left:{(p.heading - 1) * 12}px">'
            f"{_html_escape(p.text)} — p.{p.page_num}</li>"
            for p in entries
        )
        return f"<h2>Contents</h2><ul>{items}</ul>" + content_html

    def render(css: str, content_html: str):
        """Lay out one body; raises RuntimeError if MuPDF stalls."""
        head = f'<head><meta charset="utf-8"><style>{css}</style></head>'

        def wrap(body: str) -> str:
            return f'<!DOCTYPE html><html>{head}<body>{body}</body></html>'

        html = wrap(content_html)
        buf = io.BytesIO()
        writer = fitz.DocumentWriter(buf)
        outline: list[list] = []
        try:
            if toc:
                # Bounded stabilisation loop. fitz.Story.write_stabilized iterates
                # until the content stops changing, with no cap: when the TOC
                # itself shifts page counts the loop can re-render a 15-page
                # document for minutes and the MCP call times out. Each pass is a
                # layout-only write (null writer), then the final content renders
                # once.
                content = content_html
                for _ in range(4):
                    positions = []
                    _story_write(fitz.Story(wrap(content), archive=str(session_dir)),
                                 None, rectfn, positionfn=lambda p: positions.append(p))
                    new_content = toc_body(positions, content_html)
                    if new_content == content:
                        break
                    content = new_content
                # The final render also collects heading positions, so the bookmark
                # page numbers match the pages the reader actually sees - the TOC
                # block itself adds pages and shifts everything after it.
                final_positions = []
                _story_write(fitz.Story(wrap(content), archive=str(session_dir)),
                            writer, rectfn, positionfn=lambda p: final_positions.append(p))
                for p in final_positions:
                    # `p.heading` is the h-level (1 for <h1>, 2 for <h2>, ...), not a
                    # boolean; `p.depth` is DOM nesting depth and is always 1 for a
                    # flat body, so it cannot be used for the outline level.
                    level = p.heading or 0
                    # p.text is None for non-heading layout items.
                    if not (1 <= level <= toc_depth and (p.open_close & 1)):
                        continue
                    text = " ".join((p.text or "").split())
                    if text and text.lower() != "contents":
                        outline.append([level, text, p.page_num])

                # doc.set_toc rejects a level that jumps more than one below the
                # previous entry, so shift the shallowest used level to 1 and clamp
                # any skip.
                if outline:
                    # Story can return a wrapped h1 with the line break swallowed
                    # ("FunctionalSpecification"). Take the top-level heading from
                    # the markdown source instead, with whitespace normalised.
                    h1 = next(
                        (" ".join(m.group(1).split())
                         for m in (re.match(r"^#\s+(.*)$", ln) for ln in md_text.splitlines())
                         if m),
                        None,
                    )
                    if outline[0][0] == 1 and h1:
                        outline[0][1] = h1
                    shift = min(entry[0] for entry in outline) - 1
                    prev = 0
                    for entry in outline:
                        entry[0] = max(1, entry[0] - shift)
                        if entry[0] > prev + 1:
                            entry[0] = prev + 1
                        prev = entry[0]
            else:
                _story_write(fitz.Story(html=html, archive=str(session_dir)), writer, rectfn)
            writer.close()
        except Exception:
            try:
                writer.close()
            except Exception:
                pass
            raise
        return buf, outline

    # MuPDF stalls on a table row taller than the page box. Try the normal
    # layout first; if the story cannot paginate, render the tables as
    # paragraphs so the deliverable is still produced instead of hanging.
    buf = outline = None
    last_error = None
    # MuPDF clips any row taller than the page, so the PDF layout always uses
    # the split rows; the HTML deliverable keeps real tables for the browser.
    pdf_body = _split_long_table_rows(body_html)
    for layout in (pdf_body, _flatten_tables(pdf_body)):
        try:
            buf, outline = render(_PDF_CSS_SAFE, layout)
            break
        except Exception as e:
            last_error = e
    if buf is None:
        return {"status": "error", "engine": "pymupdf", "message": f"PDF export failed: {last_error}"}


    try:
        doc = fitz.open("pdf", buf)
        pages = doc.page_count
        images = sum(len(p.get_images()) for p in doc)
        doc.set_metadata({"title": title, "creator": "TFM_BA_GPT deliverable pipeline"})
        # A visible "Contents" list is not a PDF outline: without set_toc the
        # file has no bookmarks, so the sidebar/reader navigation is empty.
        if outline:
            try:
                doc.set_toc(outline)
            except Exception:
                pass
        doc.save(str(pdf_path), garbage=4, deflate=True)
        doc.close()
    except Exception as e:
        return {"status": "error", "engine": "pymupdf", "message": f"PDF metadata step failed: {e}"}

    return {
        "status": "ok",
        "engine": "pymupdf",
        "pdf": str(pdf_path),
        "pages": pages,
        "images": images,
        "toc_entries": len(outline),
    }

def export_to_pdf(session_dir: Path, md_file: str, pdf_out: str, engine: str = "xelatex",
                  toc: bool = True, toc_depth: int = 2, margin: str = "1in",
                  mainfont: Optional[str] = None, monofont: Optional[str] = None) -> dict:
    md_path = (session_dir / md_file).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Missing markdown file: {md_path}")
    pdf_path = (session_dir / pdf_out).resolve()

    # Preprocess the MD
    md_src = load_text(md_path)
    md_prepped = _hr_to_newpage(md_src)
    md_prepped = _inject_toc_top(md_prepped, enable=toc)
    md_prepped = _pagebreak_before_heading(md_prepped, r"##\s*Process Diagram")

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
        tf.write(md_prepped)
        prepped_path = Path(tf.name)

    cmd = [
        "pandoc", str(prepped_path), "-o", str(pdf_path),
        "--from", "markdown+link_attributes+bracketed_spans+implicit_figures+raw_tex",
        "--pdf-engine", engine,
        "--resource-path", str(session_dir),
        "-V", f"geometry:margin={margin}",
    ]
    # We inject our own TOC, so do NOT pass --toc
    if mainfont:
        cmd += ["-V", f"mainfont={mainfont}"]
    if monofont:
        cmd += ["-V", f"monofont={monofont}"]

    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(session_dir),
                          stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(
            "Pandoc failed (exit %d): %s\nSTDOUT:\n%s\nSTDERR:\n%s" % (
                proc.returncode, " ".join(shlex.quote(c) for c in cmd),
                proc.stdout[-4000:], proc.stderr[-4000:]
            )
        )

    return {"written_to": str(pdf_path), "stdout": proc.stdout[-2000:]}

# ------------------------------ MCP server ------------------------------
def create_server(allowed_dirs: List[Path], project_root: Optional[Path] = None) -> FastMCP:
    mcp = FastMCP("final-deliverable-mcp")

    # `export_html` is local to create_server (the tool def binds the name), so the
    # tool has to call the module-level builder by its own name - otherwise the call
    # resolves to the decorated FunctionTool and raises
    # "TypeError: 'FunctionTool' object is not callable".

    @mcp.tool()
    def export_html(
        session_dir: str,
        md: str = "functional_specification.formatted.md",
        html_out: str = "functional_specification.html",
        diagram: str = "process_diagram.png",
    ) -> dict:
        """Export the specification to a self-contained functional_specification.html (diagram inlined)."""
        sd = resolve_under_allowed(session_dir, allowed_dirs, project_root)
        return build_html_deliverable(sd, md, html_out, diagram, title=_extract_title((sd / md).resolve()))

    @mcp.tool()
    def format_spec(
        session_dir: str,
        md: str = "functional_specification.md",
        diagram: str = "process_diagram.svg",
        out: str = "functional_specification.formatted.md",
    ) -> dict:
        """Format the functional specification for PDF: build BR/FR tables and add the diagram section."""
        sd = resolve_under_allowed(session_dir, allowed_dirs, project_root)
        return format_document(sd, md, diagram, out)

    @mcp.tool()
    def export_pdf(
        session_dir: str,
        md: str = "functional_specification.formatted.md",
        pdf_out: str = "functional_specification.pdf",
        engine: str = "typst",
        toc: bool = True,
        toc_depth: int = 3,
        margin: str = "1in",
        mainfont: Optional[str] = None,
        monofont: Optional[str] = None,
    ) -> dict:
        """Export a (formatted) Markdown file to PDF.

        engine "typst" (default) typesets with Typst + pandoc - cover page, linked
        contents, running header/footer - and falls back to the PyMuPDF renderer
        when those binaries are not installed. engine "pymupdf" forces the
        pure-Python path; "xelatex"/"weasyprint" use pandoc with that engine.
        """
        sd = resolve_under_allowed(session_dir, allowed_dirs, project_root)
        if engine in ("typst", "auto"):
            return render_pdf_deliverable(sd, md, pdf_out, toc=toc, toc_depth=toc_depth)
        if engine == "pymupdf" or not have_pandoc():
            md_path = (sd / md).resolve()
            if not md_path.exists():
                raise RuntimeError(f"Missing: {md_path}")
            diagram = next((p for p in (sd / "process_diagram.png", sd / "process_diagram.svg",
                                        sd / "process_diagram.jpg") if p.exists()), None)
            pdf = _pymupdf_export(md_path, diagram, (sd / pdf_out).resolve(),
                                  title=_extract_title(md_path), toc=toc, toc_depth=toc_depth)
            return {**pdf, "note": "used the PyMuPDF renderer."}
        return export_to_pdf(sd, md, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)

    @mcp.tool()
    def format_and_export(
        session_dir: str,
        md: str = "functional_specification.md",
        diagram: str = "process_diagram.svg",
        md_out: str = "functional_specification.formatted.md",
        pdf_out: str = "functional_specification.pdf",
        engine: str = "typst",
        toc: bool = True,
        toc_depth: int = 3,
        margin: str = "1in",
        mainfont: Optional[str] = None,
        monofont: Optional[str] = None,
    ) -> dict:
        """Run formatting then export to PDF in one call."""
        sd = resolve_under_allowed(session_dir, allowed_dirs, project_root)
        fmt = format_document(sd, md, diagram, md_out)
        pdf = render_pdf_deliverable(sd, md_out, pdf_out, toc=toc, toc_depth=toc_depth)
        return {**fmt, "pdf": pdf}


    return mcp

# ------------------------------ entrypoint ------------------------------

def main():
    parser = argparse.ArgumentParser(description="Final Deliverable MCP stdio server")
    parser.add_argument("-d", "--dir", dest="dirs", action="append", required=True,
                        help="Allowed directory (can be passed multiple times)")
    parser.add_argument("--project-root", dest="project_root", default=None,
                        help="Default root for resolving relative or 'project_root/...' paths")
    args = parser.parse_args()

    allowed_dirs: List[Path] = []
    for d in args.dirs:
        dp = Path(d).expanduser().resolve()
        allowed_dirs.append(dp)
        if not dp.exists():
            print(f"[WARN] allowed dir does not exist yet: {dp}", file=sys.stderr)

    print(f"[INFO] Allowed roots: {', '.join(map(str, allowed_dirs))}", file=sys.stderr)

    allowed_dirs = [Path(d).expanduser().resolve() for d in args.dirs]
    pr = Path(args.project_root).expanduser().resolve() if args.project_root else None
    if pr and pr not in allowed_dirs:
        allowed_dirs.append(pr)
    mcp = create_server(allowed_dirs, project_root=pr)
    if hasattr(mcp, "run_stdio"):
        mcp.run_stdio()
    else:
        mcp.run()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import sys, traceback
        print("[FATAL] MCP server crashed:\n" + traceback.format_exc(), file=sys.stderr, flush=True)
        sys.exit(1)

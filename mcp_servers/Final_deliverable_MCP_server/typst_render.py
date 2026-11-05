"""Typst + pandoc renderer for the functional-specification PDF deliverable.

Why Typst: it gives the deliverable a real cover page, a linked Contents page with
dotted leaders, a running header/footer with page numbers, table headers repeated
across page breaks, and a bundled Inter font - all from one small static binary.
Pandoc converts the formatted Markdown to Typst; a post-processing pass sizes each
table's columns to their content because pandoc's default equal-width columns wrap
requirement text every two or three words and nearly double the page count.

Binary discovery order (first hit wins):
  1. TYPST_BIN / PANDOC_BIN environment variables
  2. PATH
  3. mcp_servers/Final_deliverable_MCP_server/vendor/bin (created by
     scripts/install_render_tools.py, pinned typst 0.15.1 / pandoc 3.13)
If typst or pandoc cannot be found (or the download fails), the caller falls back
to the PyMuPDF Story renderer in PDF_format_mcp_server, so the pipeline never
depends on these tools being installed. PyMuPDF is also used to QA every Typst
render (page count, bookmarks, embedded fonts, raw-mermaid check).

Fonts: Inter 4.1, SIL Open Font License 1.1 (see fonts/LICENSE-Inter.txt),
bundled so the PDF looks identical on Windows and Linux CI.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

TYPST_VERSION = "0.15.1"
PANDOC_VERSION = "3.13"

_MODULE_DIR = Path(__file__).resolve().parent
FONT_DIR = _MODULE_DIR / "fonts"
VENDOR_DIR = _MODULE_DIR / "vendor" / "bin"

_DOWNLOADS = {
    "typst": {
        "windows": (
            f"https://github.com/typst/typst/releases/download/v{TYPST_VERSION}/"
            "typst-x86_64-pc-windows-msvc.zip"
        ),
        "linux": (
            f"https://github.com/typst/typst/releases/download/v{TYPST_VERSION}/"
            "typst-x86_64-unknown-linux-musl.tar.xz"
        ),
    },
    "pandoc": {
        "windows": (
            f"https://github.com/jgm/pandoc/releases/download/{PANDOC_VERSION}/"
            f"pandoc-{PANDOC_VERSION}-windows-x86_64.zip"
        ),
        "linux": (
            f"https://github.com/jgm/pandoc/releases/download/{PANDOC_VERSION}/"
            f"pandoc-{PANDOC_VERSION}-linux-amd64.tar.gz"
        ),
    },
}

# Cover-page metadata parsed from the "Title Page" section of the Markdown.
_META_PATTERNS = (
    ("title", r"\*\*Project Name:\*\*\s*(.+)"),
    ("version", r"\*\*Version:\*\*\s*(.+)"),
    ("date", r"\*\*Date:\*\*\s*(.+)"),
    ("status", r"\*\*Document Status:\*\*\s*(.+)"),
    ("author", r"\*\*Prepared By:\*\*\s*(.+)"),
    ("number", r"\*\*Document Number:\*\*\s*(.+)"),
)

_MERMAID_FENCE_RE = re.compile(r"```mermaid.*?```", re.S)

# A4 page minus the template margins: content box is 469 x 706 pt.
_CONTENT_WIDTH_PT = 469.0
_CONTENT_HEIGHT_PT = 706.0
# Typst figures are atomic, so any #figure(table) taller than the content box
# spills past the bottom margin and its rows are clipped. Keep table chunks
# under this height; rows are estimated with a deliberately conservative glyph
# advance so real render heights stay inside the box.
_MAX_TABLE_CHUNK_PT = 520.0
_GLYPH_ADVANCE_PT = 6.5
_CELL_PAD_PT = 10.0  # typst default column spacing per cell side
_LINE_PITCH_PT = 16.0
_ROW_PAD_PT = 12.0

# Typst styling injected into every table pandoc emits: dark header row with
# white text plus light zebra stripes. Verified against typst 0.15 (the fill
# function takes (x, y); typst has no % operator, so even rows are detected
# with integer division).
_TABLE_FILL = 'fill: (x, y) => if y == 0 { rgb("#111827") } else if y / 2 * 2 == 0 { rgb("#f6f8fa") },'

_TEMPLATE = r"""#set document(title: "__TITLE__")
#let doc-title = "__TITLE__"
#let doc-subtitle = "__SUBTITLE__"
#let doc-version = "__VERSION__"
#let doc-date = "__DATE__"
#let doc-status = "__STATUS__"
#let doc-author = "__AUTHOR__"
#let accent = rgb("#2563eb")
#let ink = rgb("#111827")
#let sub = rgb("#374151")
#let faint = rgb("#9ca3af")
#let labelc = rgb("#6b7280")

#set page(
  paper: "a4",
  margin: (top: 2.4cm, bottom: 2.4cm, left: 2.2cm, right: 2.2cm),
  header: context {
    if counter(page).get().first() > 1 {
      text(doc-title + " — " + doc-subtitle, size: 8.5pt, fill: faint)
    }
  },
  footer: context {
    if counter(page).get().first() > 1 {
      align(right, text(doc-version + "  ·  " + doc-date + "      Page " + counter(page).display() + " of " + str(counter(page).final().first()), size: 8.5pt, fill: faint))
    }
  },
)
#set text(size: 10pt, lang: "en", font: "__FONT__")
#set par(justify: true, leading: 0.9em)
#set heading(numbering: none)
#show heading.where(level: 1): set text(size: 17pt, weight: "bold", fill: ink)
#show heading.where(level: 2): set text(size: 15pt, weight: "bold", fill: ink)
#show heading.where(level: 3): set text(size: 12.5pt, weight: "bold", fill: ink)
#show heading.where(level: 4): set text(size: 11pt, weight: "bold", fill: rgb("#1f2937"))

#let info-row = (label, value) => table(
  columns: (26%, 74%),
  column-gutter: 10pt,
  fill: none,
  stroke: none,
  inset: (x: 0pt, y: 4pt),
  text(label, size: 9.5pt, weight: "bold", fill: labelc),
  text(value, size: 10.5pt),
)

// ---------- cover ----------
#align(top + left, {
  v(5cm)
  text("BUSINESS ANALYSIS", size: 12pt, weight: "semibold", fill: accent)
  v(0.7cm)
  text(doc-title, size: 30pt, weight: "bold")
  v(0.4cm)
  text(doc-subtitle, size: 17pt, fill: sub)
  v(1cm)
  block(width: 6cm, height: 2.5pt, fill: accent)
  v(2cm)
  info-row("Version", doc-version)
  info-row("Date", doc-date)
  info-row("Status", doc-status)
  info-row("Prepared by", doc-author)
  v(4cm)
  text("Generated by the TFM business analysis pipeline", size: 9pt, fill: faint)
})

#pagebreak()

// ---------- contents on its own page, linked, with leaders ----------
#outline(title: [Contents], depth: 3, indent: 0.6em)
#pagebreak()

// ---------- body (sections flow packed; no forced chapter breaks) ----------
#include "__tfm_body.typ"
"""


def _typst_string(value: str) -> str:
    """Escape a plain value for a Typst double-quoted string."""
    return (value or "").strip().replace("\\", "\\\\").replace('"', '\\"')


def find_binary(name: str) -> Optional[str]:
    """Resolve the typst/pandoc executable, downloading the pinned portable
    build into vendor/bin if neither the environment nor PATH has one."""
    env = os.environ.get(f"{name.upper()}_BIN")
    if env and Path(env).is_file():
        return env
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if os.name == "nt" else "")
    cached = VENDOR_DIR / exe
    if cached.is_file():
        return str(cached)
    try:
        return _download_binary(name)
    except Exception:
        return None


def engines_available() -> bool:
    return bool(find_binary("typst") and find_binary("pandoc"))


def _download_binary(name: str) -> Optional[str]:
    """Fetch the pinned portable binary and extract the executable to vendor/bin."""
    key = "windows" if os.name == "nt" else "linux"
    url = _DOWNLOADS[name][key]
    exe = name + (".exe" if os.name == "nt" else "")
    dest = VENDOR_DIR / exe
    if dest.is_file():
        return str(dest)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".zip" if key == "windows" else ".tar", delete=False) as tmp:
        urllib.request.urlretrieve(url, tmp.name)
        tmp_path = tmp.name
    try:
        if key == "windows":
            with zipfile.ZipFile(tmp_path) as zf:
                members = [m for m in zf.namelist()
                           if os.path.basename(m).lower() == exe]
                if not members:
                    raise RuntimeError(f"{exe} not found in {url}")
                with zf.open(members[0]) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        else:
            with tarfile.open(tmp_path) as tf:
                target = None
                for member in tf.getmembers():
                    if os.path.basename(member.name) == exe and member.isfile():
                        target = member
                        break
                if target is None:
                    raise RuntimeError(f"{exe} not found in {url}")
                extracted = tf.extractfile(target)
                if extracted is None:
                    raise RuntimeError(f"cannot read {exe} from {url}")
                dest.write_bytes(extracted.read())
        dest.chmod(0o755)
    finally:
        os.unlink(tmp_path)
    return str(dest)


def binary_status() -> Dict[str, Optional[str]]:
    """Path and reported version of each renderer, for logs and the install script."""
    status = {}
    for name in ("typst", "pandoc"):
        path = find_binary(name)
        version = None
        if path:
            try:
                proc = subprocess.run([path, "--version"], capture_output=True,
                                      text=True, timeout=30, stdin=subprocess.DEVNULL)
                version = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else None
            except Exception:
                version = None
        status[name] = {"path": path, "version": version}
    return status


def extract_metadata(md_text: str, fallback_title: str = "") -> Dict[str, str]:
    """Pull cover-page fields from the Title Page section, with sane defaults."""
    meta = {
        "title": fallback_title,
        "subtitle": "Functional Requirements Specification",
        "version": "1.0",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "status": "Draft",
        "author": "Business Analysis Team",
        "number": "",
    }
    for key, pattern in _META_PATTERNS:
        match = re.search(pattern, md_text)
        if match:
            meta[key] = match.group(1).strip().rstrip()
    if not meta["title"]:
        heading = re.search(r"^#\s+(.*)$", md_text, re.M)
        meta["title"] = heading.group(1).strip() if heading else "Functional Specification"
    return meta


def strip_mermaid_fences(md_text: str) -> str:
    """Drop raw Mermaid fences from the PDF body: the rendered PNG is already
    embedded in the Markdown, and pandoc would typeset the source as code."""
    return _MERMAID_FENCE_RE.sub("", md_text)


def _header_line_cells(header_text: str) -> List[str]:
    return re.findall(r"\[([^\[\]]*)\]", header_text)


def _style_table_block(block: List[str]) -> List[str]:
    """Rewrite one pandoc #table(...) block: proportional column widths, a
    dark white-text header row, and hyphenation off so narrow columns wrap at
    word boundaries instead of splitting "Confirmed" into "Con-firmed"."""
    columns_index = None
    for index, line in enumerate(block):
        match = re.match(r"\s*columns:\s*\((.*)\),?\s*$", line)
        if match:
            columns_index = index
            break
    header_index = next((i for i, line in enumerate(block) if "table.header(" in line), None)
    if columns_index is None or header_index is None:
        return block

    columns = [c.strip() for c in re.split(r",", block[columns_index].split(":", 1)[1]) if c.strip()]
    ncols = len(columns)
    if ncols < 2:
        return block

    rows = _block_rows(block)
    if len(rows) < 2:
        return block
    widths = _column_widths(rows)

    styled = ["#{", "  set text(hyphenate: false)", "  table(", "  " + _TABLE_FILL]
    for index, line in enumerate(block[1:]):
        if index + 1 == header_index:
            wrapped = re.sub(r"\[([^\[\]]*)\]", r"text([\1], fill: white)", line)
            styled.append(wrapped)
        elif index + 1 == columns_index:
            styled.append("  columns: (" + ", ".join(f"{w}%" for w in widths) + "),")
        else:
            styled.append(line)
    styled.append("}")
    return styled


def _table_cells(line: str) -> List[str]:
    """Extract the plain-text cells of one Markdown table row."""
    return [c.strip() for c in line.split("|")[1:-1]]


def _block_rows(block: List[str]) -> List[List[str]]:
    """Header and body rows of a pandoc Typst table block as cell lists.

    pandoc wraps long cells over several lines; the bracket regex runs over the
    joined block so a wrapped cell still counts as one cell in its own column.
    """
    header_start = next((i for i, line in enumerate(block) if "table.header(" in line), None)
    if header_start is None:
        return []
    hline = next((i for i, line in enumerate(block) if "table.hline()" in line), header_start + 1)
    header_cells = re.findall(r"\[([^\[\]]*)\]", "\n".join(block[header_start:hline]), re.S)
    body_cells = re.findall(r"\[([^\[\]]*)\]", "\n".join(block[hline:]), re.S)
    ncols = len(header_cells)
    if ncols < 2:
        return []
    rows = [header_cells]
    for i in range(0, len(body_cells), ncols):
        row = body_cells[i:i + ncols]
        if len(row) == ncols:
            rows.append(row)
    return rows


def _column_widths(rows: List[List[str]]) -> List[int]:
    """Typst column widths in %.

    Each column gets at least the width of its longest single word, so no cell
    hyphen-breaks in the middle of a term; the remaining page width is shared
    in proportion to each column's total content. This keeps short value
    columns (ID, Priority) narrow and gives Status/Source enough room to read.
    """
    cols = list(zip(*rows))
    mins, weights = [], []
    for col in cols:
        words = [len(w) for cell in col for w in cell.replace("<br/>", " ").split()]
        longest_word = max(words) if words else 4
        mins.append((longest_word + 1) * _GLYPH_ADVANCE_PT + _CELL_PAD_PT)
        weights.append(sum(len(cell) for cell in col) or 1)
    total_min = sum(mins)
    if total_min >= _CONTENT_WIDTH_PT:
        fracs = [m / total_min * 100 for m in mins]
    else:
        spare = _CONTENT_WIDTH_PT - total_min
        fracs = [(m + spare * w / sum(weights)) / _CONTENT_WIDTH_PT * 100
                 for m, w in zip(mins, weights)]
    widths = [max(6, min(70, round(f))) for f in fracs]
    widths[widths.index(max(widths))] += 100 - sum(widths)
    return widths


def _chunked_table(table_lines: List[str]) -> List[str]:
    """Split one Markdown table into chunks that each fit on a single page.

    Pandoc wraps every table in an atomic Typst figure; Typst only repeats
    table.header for blocks Typst itself can split. Chunking at row boundaries
    keeps every table short enough to stay unbroken, so no row is ever cut.
    """
    if len(table_lines) < 4:
        return table_lines
    header, sep, rows = table_lines[0], table_lines[1], table_lines[2:]
    cells = [_table_cells(line) for line in table_lines if "|" in line]
    widths = _column_widths(cells)
    chars_per_line = [(_CONTENT_WIDTH_PT * w / 100 - _CELL_PAD_PT) / _GLYPH_ADVANCE_PT
                      for w in widths]

    def row_height(cells: List[str]) -> float:
        nlines = max(
            math.ceil(max(len(c), 1) / chars_per_line[k]) if k < len(chars_per_line) else 1
            for k, c in enumerate(cells)
        )
        return nlines * _LINE_PITCH_PT + _ROW_PAD_PT

    header_h = row_height(_table_cells(header)) + 2
    chunks: List[List[str]] = []
    current: List[str] = []
    used = 0.0
    for row in rows:
        height = row_height(_table_cells(row))
        if current and used + height > _MAX_TABLE_CHUNK_PT - header_h:
            chunks.append(current)
            current, used = [], 0.0
        current.append(row)
        used += height
    if current:
        chunks.append(current)
    if len(chunks) == 1:
        return table_lines
    out: List[str] = []
    for chunk in chunks:
        out.extend([header, sep] + chunk)
        out.append("")
    return out


def _split_markdown_tables(md_text: str) -> str:
    """Apply _chunked_table to every Markdown table in the document."""
    lines = md_text.split("\n")
    out: List[str] = []
    index = 0
    separator = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")
    while index < len(lines):
        if (lines[index].lstrip().startswith("|") and index + 1 < len(lines)
                and separator.match(lines[index + 1])):
            end = index + 1
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
            out.extend(_chunked_table(lines[index:end]))
            index = end
        else:
            out.append(lines[index])
            index += 1
    return "\n".join(out)


def fix_table_columns(typst_text: str) -> str:
    """Style every pandoc #table block (proportional columns, dark header).

    Pandoc wraps tables in #figure(..., kind: table). Typst figures are atomic:
    a figure taller than the page is not split - it overflows past the bottom
    margin and its rows are clipped off the page. Every table figure is
    unwrapped into a bare #table, which Typst splits at row boundaries with
    table.header repeated on each page. The Markdown chunker keeps most tables
    short enough to fit a page, so splits are rare and never lose a row.
    """
    lines = typst_text.splitlines()
    out: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        wrapped = (line.strip() == "#figure(" and index + 1 < len(lines)
                   and lines[index + 1].strip().startswith("align(center)[#table("))
        if wrapped:
            close = index + 2
            while close < len(lines) and lines[close].strip() != ")]":
                close += 1
            if close < len(lines) and close + 1 < len(lines) \
                    and lines[close + 1].strip().startswith(", kind: table"):
                out.extend(_style_table_block(["#table("] + lines[index + 2:close] + [")"]))
                index = close + 3
                continue
        if line.strip() == "#table(":
            end = index + 1
            while end < len(lines) and lines[end].strip() != ")":
                end += 1
            if end >= len(lines):
                out.append(line)
                index += 1
                continue
            out.extend(_style_table_block(lines[index:end + 1]))
            index = end + 1
        else:
            out.append(line)
            index += 1
    return "\n".join(out)


def _markdown_to_typst(md_text: str, session_dir: Path, pandoc_bin: str) -> str:
    body_md = session_dir / "__tfm_body.md"
    body_md.write_text(md_text, encoding="utf-8")
    proc = subprocess.run(
        [pandoc_bin, str(body_md), "-f", "markdown+link_attributes", "-t", "typst",
         "-o", "__tfm_body.typ"],
        capture_output=True, text=True, cwd=str(session_dir),
        stdin=subprocess.DEVNULL, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc markdown->typst failed: {proc.stderr[-1500:]}")
    return (session_dir / "__tfm_body.typ").read_text(encoding="utf-8")


def qa_pdf(pdf_path: Path) -> Dict[str, object]:
    """Read the finished PDF back with PyMuPDF: pages, images, bookmarks,
    embedded font names, and a raw-Mermaid leak check."""
    qa: Dict[str, object] = {"pages": 0, "images": 0, "toc_entries": 0, "fonts": [], "raw_mermaid": 0}
    try:
        import pymupdf as fitz
    except Exception:
        return qa
    doc = fitz.open(str(pdf_path))
    try:
        qa["pages"] = doc.page_count
        qa["images"] = sum(len(page.get_images()) for page in doc)
        qa["toc_entries"] = len(doc.get_toc())
        fonts = set()
        raw_mermaid = 0
        for page in doc:
            for font in page.get_fonts():
                fonts.add(font[3])
            text = page.get_text()
            if "graph TD" in text or "flowchart TD" in text or "sequenceDiagram" in text:
                raw_mermaid += 1
        qa["fonts"] = sorted(fonts)
        qa["raw_mermaid"] = raw_mermaid
    finally:
        doc.close()
    return qa


def render(markdown_path: Path, pdf_path: Path, title: Optional[str] = None) -> dict:
    """Render the formatted spec Markdown into the deliverable PDF with Typst.

    Returns the same shape as _pymupdf_export plus engine/QA fields.
    status "unavailable" means typst or pandoc is not installed and the caller
    should use the PyMuPDF fallback.
    """
    typst_bin = find_binary("typst")
    pandoc_bin = find_binary("pandoc")
    if not typst_bin or not pandoc_bin:
        return {"status": "unavailable", "engine": "typst",
                "message": "typst and/or pandoc not found; falling back to PyMuPDF"}

    md_path = Path(markdown_path)
    out_path = Path(pdf_path)
    session_dir = md_path.parent
    try:
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {"status": "error", "engine": "typst", "message": f"Markdown read failed: {exc}"}

    meta = extract_metadata(md_text, title or "")
    body_md = _split_markdown_tables(strip_mermaid_fences(md_text))

    fonts_ready = any(FONT_DIR.glob("*.ttf")) or any(FONT_DIR.glob("*.otf"))
    font = "Inter" if fonts_ready else "Libertinus Serif"

    try:
        body_typst = fix_table_columns(_markdown_to_typst(body_md, session_dir, pandoc_bin))
        main_typst = (
            _TEMPLATE
            .replace("__TITLE__", _typst_string(meta["title"]))
            .replace("__SUBTITLE__", _typst_string(meta["subtitle"]))
            .replace("__VERSION__", _typst_string(meta["version"]))
            .replace("__DATE__", _typst_string(meta["date"]))
            .replace("__STATUS__", _typst_string(meta["status"]))
            .replace("__AUTHOR__", _typst_string(meta["author"]))
            .replace("__FONT__", font)
        )
        main_path = session_dir / "__tfm_main.typ"
        main_path.write_text(main_typst, encoding="utf-8")
        body_path = session_dir / "__tfm_body.typ"
        body_path.write_text(body_typst, encoding="utf-8")

        command = [typst_bin, "compile"]
        if fonts_ready:
            command += ["--font-path", str(FONT_DIR)]
        command += ["__tfm_main.typ", str(out_path)]
        proc = subprocess.run(command, capture_output=True, text=True,
                              cwd=str(session_dir), stdin=subprocess.DEVNULL, timeout=180)
        if proc.returncode != 0 or not out_path.is_file():
            raise RuntimeError(f"typst compile failed: {proc.stderr[-1500:]}")
    except Exception as exc:
        return {"status": "error", "engine": "typst", "message": f"Typst render failed: {exc}"}
    finally:
        for leftover in (session_dir / "__tfm_main.typ", session_dir / "__tfm_body.typ",
                         session_dir / "__tfm_body.md"):
            try:
                leftover.unlink()
            except OSError:
                pass

    result: Dict[str, object] = {"status": "ok", "engine": "typst",
                                 "pdf": str(out_path), "font": font}
    qa = qa_pdf(out_path)
    result.update(qa)
    return result

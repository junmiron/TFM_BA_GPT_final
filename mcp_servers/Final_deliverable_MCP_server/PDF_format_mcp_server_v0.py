#!/run/media/jun/Jun_6T/Code/mcp_servers/Final_deliverable_MCP_server/venv/bin/python3

"""
Final Deliverable MCP Server (FastMCP)

Tools:
  - format_spec(session_dir, md, diagram, out)
  - export_pdf(session_dir, md, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)
  - format_and_export(session_dir, md, diagram, md_out, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)

Run (stdio):
  python3 final_deliverable_mcp.py -d /run/media/jun/Jun_6T/Code/TFM_BA_GPT/experience
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional, List

from fastmcp import FastMCP

# ------------------------------ path guard ------------------------------

def resolve_under_allowed(path: str | Path, allowed: List[Path]) -> Path:
    p = Path(path).expanduser().resolve()
    for root in allowed:
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
    """Find a section by heading regex. Return (start_idx, end_idx) in chars."""
    m = re.search(rf"(?im)^(?P<hashes>#+)\s*(?:{heading_regex})\s*$", md)
    if not m:
        return -1, -1
    start = m.end()
    level = len(m.group("hashes"))
    pat = rf"(?im)^#{{1,{max(level, stop_at_level)}}}\s+"
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

def ensure_diagram_section(md: str, diagram_name: str) -> str:
    rel = diagram_name
    image_md = f"![Process Diagram]({rel}){{ width=95% }}\n"
    m = re.search(r"(?im)^##\s*Process Diagram\s*$", md)
    if m:
        start, end = find_section(md, "Process Diagram", stop_at_level=2)
        if start != -1:
            content = md[:start] + "\n" + image_md + "\n" + md[end:]
            return content
    tail = "\n\n## Process Diagram\n\n" + image_md + "\n"
    return md.rstrip() + tail

def ensure_in_scope_requirements_table(md: str) -> tuple[str, int]:
    start, end = find_section(md, r"In-?Scope\b.*", stop_at_level=3)
    if start == -1:
        return md, 0
    block = md[start:end]
    items = parse_numbered_list(block)
    if not items:
        return md, 0
    table = "\n### Business Requirements\n\n" + build_requirements_table(items) + "\n"
    updated = md[:end] + table + md[end:]
    return updated, len(items)

# -------- Functional Requirements mapping (FR -> BR) --------

def _extract_br_ids_from_in_scope(md: str) -> list[str]:
    start, end = find_section(md, r"In-?Scope\b.*", stop_at_level=3)
    if start == -1:
        return []
    items = parse_numbered_list(md[start:end])
    return [f"BR{i}" for i in range(1, len(items) + 1)]

def _strip_inline_br_tags(text: str) -> tuple[str, str | None]:
    """Return (clean_text, br_id_or_none). Detect forms like [BR1] or (BR: BR1)."""
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
    """Find '## Functional Requirements' and append a mapping table below it."""
    start, end = find_section(md, r"Functional Requirements", stop_at_level=3)
    if start == -1:
        return md, 0
    section = md[start:end]
    if "| Business Requirement ID | Functional Requirement ID | Description |" in section:
        return md, 0
    fr_items = parse_numbered_list(section)
    if not fr_items:
        return md, 0
    table, n = build_fr_table(md, fr_items)
    updated = md[:end] + "\n### Functional Requirements Mapping\n\n" + table + md[end:]
    return updated, n

# ------------------------------ formatting core ------------------------------

def format_document(session_dir: Path, md_file: str, diagram_file: str, out_file: str) -> dict:
    md_path = (session_dir / md_file).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Missing: {md_path}")

    md = load_text(md_path)

    # Build tables
    md, n_br = ensure_in_scope_requirements_table(md)
    md, n_fr = ensure_functional_requirements_table(md)

    # Ensure diagram section
    md = ensure_diagram_section(md, diagram_file)

    out_path = (session_dir / out_file).resolve()
    save_text(out_path, md)
    return {
        "written_to": str(out_path),
        "business_requirements": n_br,
        "functional_requirements": n_fr,
        "diagram": diagram_file,
    }

# ------------------------------ pandoc export ------------------------------

def have_pandoc() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False

def export_to_pdf(session_dir: Path, md_file: str, pdf_out: str, engine: str = "xelatex",
                  toc: bool = True, toc_depth: int = 2, margin: str = "1in",
                  mainfont: str = "Cantarell", monofont: str = "Fira Code") -> dict:
    md_path = (session_dir / md_file).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"Missing markdown file: {md_path}")
    pdf_path = (session_dir / pdf_out).resolve()

    cmd = [
        "pandoc", str(md_path), "-o", str(pdf_path),
        "--from", "gfm",
        "--pdf-engine", engine,
        "-V", f"geometry:margin={margin}",
        "-V", f"mainfont={mainfont}",
        "-V", f"monofont={monofont}",
    ]
    if toc:
        cmd += ["--toc", "--toc-depth", str(toc_depth)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Pandoc failed (exit %d): %s\nSTDOUT:\n%s\nSTDERR:\n%s" % (
                proc.returncode, " ".join(shlex.quote(c) for c in cmd), proc.stdout[-4000:], proc.stderr[-4000:]
            )
        )

    return {"written_to": str(pdf_path), "stdout": proc.stdout[-2000:]}

# ------------------------------ MCP server ------------------------------

def create_server(allowed_dirs: List[Path]) -> FastMCP:
    mcp = FastMCP("final-deliverable-mcp")

    @mcp.tool()
    def format_spec(
        session_dir: str,
        md: str = "functional_specification.md",
        diagram: str = "process_diagram.svg",
        out: str = "functional_specification.formatted.md",
    ) -> dict:
        """Format the functional specification for PDF: build BR/FR tables and add the diagram section."""
        sd = resolve_under_allowed(session_dir, allowed_dirs)
        return format_document(sd, md, diagram, out)

    @mcp.tool()
    def export_pdf(
        session_dir: str,
        md: str = "functional_specification.formatted.md",
        pdf_out: str = "deliverable.pdf",
        engine: str = "xelatex",
        toc: bool = True,
        toc_depth: int = 2,
        margin: str = "1in",
        mainfont: str = "Cantarell",
        monofont: str = "Fira Code",
    ) -> dict:
        """Export a (formatted) Markdown file to PDF using Pandoc."""
        if not have_pandoc():
            raise RuntimeError("pandoc not found. Install pandoc and a LaTeX engine (e.g., TeX Live).")
        sd = resolve_under_allowed(session_dir, allowed_dirs)
        return export_to_pdf(sd, md, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)

    @mcp.tool()
    def format_and_export(
        session_dir: str,
        md: str = "functional_specification.md",
        diagram: str = "process_diagram.svg",
        md_out: str = "functional_specification.formatted.md",
        pdf_out: str = "deliverable.pdf",
        engine: str = "xelatex",
        toc: bool = True,
        toc_depth: int = 2,
        margin: str = "1in",
        mainfont: str = "Cantarell",
        monofont: str = "Fira Code",
    ) -> dict:
        """Run formatting then export to PDF in one call."""
        sd = resolve_under_allowed(session_dir, allowed_dirs)
        fmt = format_document(sd, md, diagram, md_out)
        if not have_pandoc():
            fmt["note"] = "pandoc not found; skipping export."
            return fmt
        pdf = export_to_pdf(sd, md_out, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)
        return {**fmt, **{"pdf": pdf}}

    return mcp

# ------------------------------ entrypoint ------------------------------

def main():
    parser = argparse.ArgumentParser(description="Final Deliverable MCP stdio server")
    parser.add_argument("-d", "--dir", dest="dirs", action="append", required=True,
                        help="Allowed directory (can be passed multiple times)")
    args = parser.parse_args()

    allowed_dirs: List[Path] = []
    for d in args.dirs:
        dp = Path(d).expanduser().resolve()
        allowed_dirs.append(dp)
        if not dp.exists():
            print(f"[WARN] allowed dir does not exist yet: {dp}", file=sys.stderr)

    print(f"[INFO] Allowed roots: {', '.join(map(str, allowed_dirs))}", file=sys.stderr)

    mcp = create_server(allowed_dirs)
    if hasattr(mcp, "run_stdio"):
        mcp.run_stdio()
    else:
        mcp.run()

if __name__ == "__main__":
    main()

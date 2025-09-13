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
import asyncio
import json
import datetime

import argparse
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
from autogen_core.memory import MemoryContent, MemoryMimeType
from autogen_ext.memory.chromadb import (ChromaDBVectorMemory,
    PersistentChromaDBVectorMemoryConfig)

# If you want local embeddings:
try:
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except Exception:
    _HAS_ST = False

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
    """
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


# === RUNTIME-SAFE ASYNC RUNNER (works even if host loop is running) ===
def _run_coro(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        box = {}
        def _worker():
            box["result"] = asyncio.run(coro)
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join()
        return box.get("result")
    return asyncio.run(coro)


# === WHERE TO STORE CHROMA PERSISTENCE ===
def _chroma_root(allowed_dirs: List[Path]) -> Path:
    # pick the first allowed dir that looks like project root, drop .experiences under it
    root = allowed_dirs[0]
    out = (root / ".experiences").resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


# === BUILD THE EXPERIENCE PAYLOAD (your spec) ===
def build_payload(session_dir: Path, session_id: str) -> dict:
    wanted = [
        "interview.jsonl",
        "functional_specification.md",
        "functional_specification.formatted.md",
        "process_diagram.mmd",
        "process_diagram.png",
        "deliverable.pdf",
    ]
    files = []
    for name in wanted:
        p = session_dir / name
        if p.exists():
            st = p.stat()
            files.append({
                "name": name,
                "path": str(p),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
    return {
        "type": "TFM_BA_GPT.experience",
        "session_id": session_id,
        "root": str(session_dir),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "files": files,
    }


# === CREATE CHROMA MEMORY (Autogen wrapper) ===
def _make_chroma_memory(collection: str, persistence_path: Path,
                        k: int = 12, score_threshold: float = 0.15):

    model = SentenceTransformer('all-MiniLM-L6-v2')
    model = model.to('cuda')  # This moves the model to GPU

    cfg = PersistentChromaDBVectorMemoryConfig(
        collection_name=collection,
        persistence_path=str(persistence_path),
        k=k,
        score_threshold=score_threshold,
        embedding_function=model
    )
    # If you want to pass a custom embedding function (e.g., your model_client),
    # do: ChromaDBVectorMemory(config=cfg, embedding_function=model_client)
    # Leaving default lets Autogen use its built-in embedding path.
    return ChromaDBVectorMemory(config=cfg)


# === TINY FILE LOADERS ===
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def _read_jsonl(path: Path) -> list:
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                out.append({"_raw": line})
    return out


async def _add_all(memory, items):
    # add sequentially; you can switch to asyncio.gather if you prefer
    for it in items:
        await memory.add(it)
    return len(items)

def _chunk_text(s: str, max_chars: int = 2000, overlap: int = 200) -> list[str]:
    out, n = [], len(s)
    i = 0
    while i < n:
        j = min(n, i + max_chars)
        out.append(s[i:j])
        i = j - overlap if j < n else j
        if i < 0: i = 0
    return out

def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

def _extract_filename(q: str) -> str | None:
    m = re.search(r"([A-Za-z0-9_\-\.]+\.(?:md|mmd|png|jpg|jpeg|svg|pdf|jsonl))", q or "")
    return m.group(1) if m else None

def _session_header(session_id: str, name: str, path: Path, kind: str) -> str:
    # Embed the session id inside every chunk to make “no-query” retrieval easier
    return f"[SESSION {session_id}] [{kind}] file={name} path={path}\n"

# -------- Functional Requirements mapping (FR -> BR) --------

def _extract_br_ids_from_in_scope(md: str) -> list[str]:
    start, end = find_section(md, r"In-?Scope\b.*", stop_at_level=3)
    if start == -1:
        return []
    items = parse_numbered_list(md[start:end])
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
        subprocess.run(["pandoc", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False

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

    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(session_dir))
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
        pdf_out: str = "deliverable.pdf",
        engine: str = "xelatex",
        toc: bool = True,
        toc_depth: int = 2,
        margin: str = "1in",
        mainfont: Optional[str] = None,
        monofont: Optional[str] = None,
    ) -> dict:
        """Export a (formatted) Markdown file to PDF using Pandoc with robust preprocessing."""
        if not have_pandoc():
            raise RuntimeError("pandoc not found. Install pandoc and a LaTeX engine (e.g., TeX Live).")
        sd = resolve_under_allowed(session_dir, allowed_dirs, project_root)
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
        mainfont: Optional[str] = None,
        monofont: Optional[str] = None,
    ) -> dict:
        """Run formatting then export to PDF in one call."""
        sd = resolve_under_allowed(session_dir, allowed_dirs, project_root)
        fmt = format_document(sd, md, diagram, md_out)
        if not have_pandoc():
            fmt["note"] = "pandoc not found; skipping export."
            return fmt
        pdf = export_to_pdf(sd, md_out, pdf_out, engine, toc, toc_depth, margin, mainfont, monofont)
        return {**fmt, **{"pdf": pdf}}


    @mcp.tool()
    def save_experience_chroma(
        session_dir: str,
        session_id: str,
        collection_name: str = "tfm_ba_gpt_experiences",
        k: int = 12,
        score_threshold: float = 0.15,
    ) -> dict:
        """
        Index the whole session in Autogen's ChromaDBVectorMemory.
        Stores:
        - JSON 'experience' payload
        - Human summary
        - PATH cards for every file (fast folder lookups)
        - Chunked MARKDOWN for *.md and *.mmd
        - interview.jsonl as JSON + a TEXT synopsis (RAG-friendly)
        """
        sd = Path(session_dir).expanduser().resolve()
        resolve_under_allowed(sd, allowed_dirs)

        chroma_dir = _chroma_root(allowed_dirs)
        memory = _make_chroma_memory(collection_name, chroma_dir, k=k, score_threshold=score_threshold)

        payload = build_payload(sd, session_id)

        items: list[MemoryContent] = []

        # 1) Structured payload (JSON)
        items.append(
            MemoryContent(
                content={**payload, "__session_tag__": f"SESSION:{session_id}"},
                mime_type=MemoryMimeType.JSON,
                metadata={"kind": "experience-json", "session_id": session_id},
            )
        )

        # 2) Human-readable catalog summary
        lines = [f"SESSION {session_id} catalog for {payload['root']} ({len(payload['files'])} files):"]
        for f in payload["files"]:
            lines.append(f"- {f['name']} @ {f['path']} ({f['size']} bytes)")
        items.append(
            MemoryContent(
                content="\n".join(lines),
                mime_type=MemoryMimeType.TEXT,
                metadata={"kind": "experience-summary", "session_id": session_id},
            )
        )

        # Helper to add a path-card
        def _path_card(name: str, p: Path) -> MemoryContent:
            return MemoryContent(
                content=f"[SESSION {session_id}] File {name} is located at {str(p)}",
                mime_type=MemoryMimeType.TEXT,
                metadata={"kind": "path-entry", "session_id": session_id, "name": name, "path": str(p)},
            )

        by_name = {f["name"]: Path(f["path"]) for f in payload["files"]}

        # 3) Markdown & Mermaid: chunk and index full content
        for md_name in ("functional_specification.formatted.md", "functional_specification.md", "process_diagram.mmd"):
            p = by_name.get(md_name)
            if not p: 
                continue
            text = _safe_read(p)
            if text:
                chunks = _chunk_text(text, max_chars=2000, overlap=100)
                for idx, ch in enumerate(chunks):
                    items.append(
                        MemoryContent(
                            content=_session_header(session_id, md_name, p, "file-markdown-chunk") + ch,
                            mime_type=MemoryMimeType.MARKDOWN,
                            metadata={
                                "kind": "file-markdown-chunk",
                                "session_id": session_id, "name": md_name, "path": str(p),
                                "chunk_index": idx, "total_chunks": len(chunks),
                            },
                        )
                    )
            # path card
            items.append(_path_card(md_name, p))

        # 4) interview.jsonl as JSON + short TEXT synopsis for RAG
        if "interview.jsonl" in by_name:
            pj = by_name["interview.jsonl"]
            records = _read_jsonl(pj)
            items.append(
                MemoryContent(
                    content={"file": "interview.jsonl", "records": records, "__session_tag__": f"SESSION:{session_id}"},
                    mime_type=MemoryMimeType.JSON,
                    metadata={"kind": "file-json", "session_id": session_id, "name": "interview.jsonl", "path": str(pj)},
                )
            )
            # synopsis (flattened Q/A lines)
            synopsis = [f"[SESSION {session_id}] interview.jsonl synopsis:"]
            for r in records[:200]:  # cap to avoid huge vectors
                msg = r.get("message") or r.get("text") or ""
                if msg:
                    synopsis.append(f"- {msg}")
            items.append(
                MemoryContent(
                    content="\n".join(synopsis),
                    mime_type=MemoryMimeType.TEXT,
                    metadata={"kind": "file-json-synopsis", "session_id": session_id, "name": "interview.jsonl", "path": str(pj)},
                )
            )
            items.append(_path_card("interview.jsonl", pj))

        # 5) Path cards for the rest (png/svg/pdf/etc.)
        for name, p in by_name.items():
            if not any(m.metadata.get("name") == name and m.metadata.get("kind") == "path-entry" for m in items if m.metadata):
                items.append(_path_card(name, p))

        # Ensure every item has session_id metadata
        for it in items:
            it.metadata = {**(it.metadata or {}), "session_id": session_id}

        # Write all (Autogen API is async)
        written = _run_coro(_add_all(memory, items))
        return {
            "ok": True, "session_id": session_id, "files_indexed": len(payload["files"]),
            "written_items": written, "collection": collection_name,
            "persistence_path": str(chroma_dir),
        }

    @mcp.tool()
    def recall_experience_chroma(
        session_id: str,
        query: str | None = None,
        include_all: bool = False,
        top_k: int = 12,
        score_threshold: float = 0.15,
        collection_name: str = "tfm_ba_gpt_experiences",
    ) -> dict:
        """
        Recall from Autogen-Chroma.
        - If no query OR include_all=True: return payload + raw contents for key files.
        - If query asks “where is / what folder is <file>” => direct folder/path.
        - If query asks “content of <file>” => return full file content.
        - Otherwise: semantic QA over indexed chunks (md/mmd/json).
        """
        chroma_dir = _chroma_root(allowed_dirs)
        memory = _make_chroma_memory(
            collection_name, chroma_dir, k=top_k, score_threshold=score_threshold
        )

        # --- local helpers that CLOSE OVER `memory` --------------------------------
        async def _query_async(s: str):
            return await memory.query(s)

        def _q(s: str):
            return _run_coro(_query_async(s))

        def _read_if_exists(p: str) -> str:
            try:
                return Path(p).read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ""

        # Pull text + metadata from Autogen Chroma hits
        def _norm(rs):
            out = []
            hits = getattr(rs, "results", []) or []
            for r in hits:
                # r.memory is the MemoryContent (content/mime_type/metadata)
                mem = getattr(r, "memory", None)
                mcontent = None
                mmeta = {}
                mmime = None
                if mem is not None:
                    # handle either dict-like or object
                    if isinstance(mem, dict):
                        mcontent = mem.get("content")
                        mmeta = mem.get("metadata") or {}
                        mmime = mem.get("mime_type")
                    else:
                        mcontent = getattr(mem, "content", None)
                        mmeta = getattr(mem, "metadata", {}) or {}
                        mmime = getattr(mem, "mime_type", None)
                # some builds also expose r.text / r.content
                if not isinstance(mcontent, (str, bytes)) and mcontent is not None:
                    # could be an Image or other type – ignore for preview
                    pass
                text = None
                if isinstance(mcontent, (str, bytes)):
                    text = mcontent if isinstance(mcontent, str) else mcontent.decode("utf-8", "replace")
                if text is None:
                    text = getattr(r, "text", None) or getattr(r, "content", None) or ""

                # prefer top-level metadata if present, but merge both
                meta = {}
                try:
                    meta.update(getattr(r, "metadata", {}) or {})
                except Exception:
                    pass
                for k, v in (mmeta or {}).items():
                    meta.setdefault(k, v)
                if mmime and "mime_type" not in meta:
                    meta["mime_type"] = str(mmime)

                out.append({
                    "score": getattr(r, "score", None),
                    "metadata": meta,
                    "text": text,
                    "preview": (text[:240] if isinstance(text, str) else ""),
                })
            return out

        # Extract a value like the project name from markdown-ish text
        def _extract_project_name_from_text(txt: str) -> str | None:
            # **Project Name**: AI Dialer...
            m = re.search(r"(?im)^\s*\*\*?\s*Project\s+Name\s*\*\*?\s*:\s*(.+?)\s*$", txt)
            if m:
                return m.group(1).strip()
            # ## Project Name \n line(s) of text until next heading
            mh = re.search(r"(?im)^\s*##\s*Project\s+Name\s*$", txt)
            if mh:
                block = txt[mh.end():]
                nxt = re.search(r"(?im)^\s*#\s*|\A", block)
                span = block[:nxt.start()] if nxt else block
                first = span.strip().splitlines()
                return first[0].strip() if first else None
            # Markdown table cell: | Project Name | Value |
            m2 = re.search(r"(?im)^\s*\|\s*Project\s+Name\s*\|\s*(.+?)\s*\|", txt)
            if m2:
                return m2.group(1).strip()
            return None

        # Find path-entry rows for a filename
        def _path_for(filename: str, rs) -> str | None:
            for r in getattr(rs, "results", []) or []:
                md = getattr(r, "metadata", {}) or {}
                if md.get("kind") == "path-entry" and md.get("name") == filename and md.get("session_id") == session_id:
                    return md.get("path")
            return None

        # 0) No query => full catalog + core contents
        if include_all or not query:
            # Try to grab the JSON payload
            rs_payload = _q(f"SESSION {session_id} experience-json")
            payload = None
            for r in getattr(rs_payload, "results", []) or []:
                # get text from r.memory.content if present
                mem = getattr(r, "memory", None)
                raw = None
                if mem is not None:
                    raw = (mem.get("content") if isinstance(mem, dict) else getattr(mem, "content", None))
                raw = raw if isinstance(raw, str) else (getattr(r, "text", None) or "")
                try:
                    obj = json.loads(raw or "{}")
                except Exception:
                    obj = None
                if isinstance(obj, dict) and obj.get("type") == "TFM_BA_GPT.experience" and obj.get("session_id") == session_id:
                    payload = obj
                    break

            # If no payload, still return a path catalog
            if not payload:
                rs_paths = _q(f"SESSION {session_id} catalog")
                paths = []
                for r in getattr(rs_paths, "results", []) or []:
                    md = getattr(r, "metadata", {}) or {}
                    if md.get("kind") == "path-entry" and md.get("session_id") == session_id:
                        paths.append({"name": md.get("name"), "path": md.get("path")})
                return {
                    "ok": True, "mode": "catalog", "session_id": session_id,
                    "paths": paths,
                    "collection": collection_name, "persistence_path": str(chroma_dir),
                    "raw": _norm(rs_paths),
                }

            # Also return CONTENTS for the important files
            by_name = {f["name"]: f["path"] for f in payload.get("files", [])}
            reply = {
                "ok": True, "mode": "full", "session_id": session_id, "payload": payload,
                "collection": collection_name, "persistence_path": str(chroma_dir),
                "contents": {}
            }
            for name in ("functional_specification.formatted.md", "functional_specification.md", "process_diagram.mmd", "interview.jsonl"):
                p = by_name.get(name)
                if p:
                    reply["contents"][name] = _read_if_exists(p)
            return reply

        # 1) Filename intents
        filename = _extract_filename(query)
        if filename:
            if re.search(r"\b(content|show|print|display)\b", query, flags=re.I):
                rs = _q(filename)
                p = _path_for(filename, rs)
                if p:
                    return {"ok": True, "mode": "content", "file": filename, "path": p, "content": _read_if_exists(p)}
                return {"ok": False, "mode": "content", "file": filename, "reason": "Path not found in memory for this session."}

            if re.search(r"\b(where|folder|path)\b", query, flags=re.I):
                rs = _q(filename)
                p = _path_for(filename, rs)
                if p:
                    pp = Path(p)
                    return {"ok": True, "mode": "qa", "answer": f"{filename} is in folder: {str(pp.parent)}", "path": str(pp)}
                return {"ok": False, "mode": "qa", "reason": "No path-entry hit for this session."}

        # 2) General QA (RAG over chunk text), biased to this session
        compound = f"{query}\nSESSION {session_id}"
        rs = _q(compound)
        hits = _norm(rs)

        # Special case: mermaid content request
        if re.search(r"\b(process_diagram\.mmd|mermaid)\b", query, flags=re.I):
            rspaths = _q("process_diagram.mmd")
            p = _path_for("process_diagram.mmd", rspaths)
            if p:
                return {"ok": True, "mode": "content", "file": "process_diagram.mmd", "path": p, "content": _read_if_exists(p)}
            return {"ok": True, "mode": "query", "count": len(hits), "results": hits}

        # Try to answer directly from chunk text (preferred)
        # Scan top hits for a project name line
        if re.search(r"\bproject\s+name\b", query, flags=re.I):
            for h in hits:
                txt = h.get("text") or ""
                if not txt:
                    continue
                pn = _extract_project_name_from_text(txt)
                if pn:
                    return {
                        "ok": True,
                        "mode": "qa",
                        "answer": f"**Project Name**: {pn}",
                        "source": {"score": h.get("score"), "metadata": h.get("metadata")}
                    }
            # Fallback: read the file(s) from disk and extract there
            # Prefer formatted MD, then raw MD
            for fname in ("functional_specification.formatted.md", "functional_specification.md"):
                rspaths = _q(fname)
                p = _path_for(fname, rspaths)
                if p:
                    txt = _read_if_exists(p)
                    pn = _extract_project_name_from_text(txt)
                    if pn:
                        return {"ok": True, "mode": "qa", "answer": f"**Project Name**: {pn}", "source_path": p}

        return {
            "ok": True, "mode": "query",
            "count": len(hits),
            "results": hits,
            "collection": collection_name, "persistence_path": str(chroma_dir),
        }



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

#!/usr/bin/env python3
import argparse
import os
import sys
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
from fastmcp import FastMCP
from dataclasses import dataclass, asdict
import textwrap
import tempfile
import json
import re

# ---------- Config & helpers ----------
def resolve_under_allowed(path: str | Path,
                          allowed: List[Path],
                          project_root: Optional[Path] = None) -> Path:
    """
    Resolve 'path' to an absolute path under one of the allowed roots.
    Special handling:
      - If path starts with the token 'project_root/', join it to project_root.
      - Else if path is relative and project_root is given, join it to project_root.
    """
    s = str(path)
    p = Path(s)

    if project_root is not None:
        if s.startswith("project_root/"):
            p = project_root / s.split("project_root/", 1)[1]
        elif not p.is_absolute():
            p = project_root / p

    p = p.expanduser().resolve()

    for root in allowed:
        try:
            if p.is_relative_to(root.resolve()):
                return p
        except AttributeError:
            # Python < 3.9 compat
            r = root.resolve()
            if str(p).startswith(str(r) + "/") or str(p) == str(r):
                return p

    raise ValueError(f"Path not in allowed directories:\n{p}")

_MMDC_TIMEOUT_S = 180  # a hung puppeteer render must not hang the MCP session


def _mmdc_command() -> list[str]:
    """Resolve the mermaid-cli executable.

    On Windows npm installs `mmdc` as a shell script plus a `mmdc.cmd` shim;
    CreateProcess cannot run the extension-less script, so prefer the .cmd.
    """
    if os.name == "nt":
        resolved = shutil.which("mmdc.cmd") or shutil.which("mmdc")
        if resolved:
            return [resolved]
    return ["mmdc"]


def _strip_mermaid_fences(text: str) -> str:
    """Return one renderable Mermaid diagram from a source file.

    Mermaid files written by other tools are fenced with ```mermaid ... ```;
    mmdc cannot parse fences, so unwrap them. The diagram creator also
    frequently writes a *multi-diagram* Markdown document (headings plus several
    fenced blocks), and mmdc renders exactly one diagram per invocation —
    feeding it the whole document fails with UnknownDiagramError. Take the
    first fenced block, or the first block that starts with a diagram keyword.
    """
    stripped = text.strip()

    blocks = re.findall(r"```(?:mermaid|Mermaid)?\s*\n(.+?)```", stripped, flags=re.S)
    if blocks:
        for block in blocks:
            body = block.strip()
            if re.match(r"(?im)^\s*(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|"
                       r"erDiagram|journey|gantt|pie|mindmap|sankey-beta|xychart-beta|block-beta)\b",
                       body):
                return body
        return blocks[0].strip()

    # No fences: drop comment/heading noise so a stray leading `%%` or `##`
    # does not hide the diagram type from mmdc.
    lines = [l for l in stripped.splitlines()
             if not re.match(r"^\s*%%", l) and not re.match(r"^\s*#{1,6}\s", l)]
    return "\n".join(lines).strip()


def _puppeteer_flags(puppeteer_config: Optional[str]) -> list[str]:
    """Build the mmdc '-p' flag arguments.

    An explicit config always wins. Otherwise, in CI (GitHub-hosted runners
    on Ubuntu 24.04+ block unprivileged user namespaces, so Chrome's
    sandbox cannot start), fall back to the bundled config that disables
    the sandbox. Local (non-CI) runs keep mmdc's default behavior.
    """
    if puppeteer_config:
        return ["-p", puppeteer_config]
    if os.environ.get("CI"):
        bundled = Path(__file__).with_name("puppeteer-ci.json")
        if bundled.exists():
            return ["-p", str(bundled)]
    return []


def run_mmdc(input_path: Path, output_path: Path, fmt: str,
             theme: Optional[str] = None,
             width: Optional[int] = None,
             height: Optional[int] = None,
             background: Optional[str] = None,
             puppeteer_config: Optional[str] = None) -> None:
    raw = input_path.read_text(encoding="utf-8", errors="ignore")
    cleaned = _strip_mermaid_fences(raw)
    if cleaned != raw.strip():
        tmp = input_path.with_suffix(".clean.mmd")
        tmp.write_text(cleaned + "\n", encoding="utf-8")
        input_path = tmp

    cmd = _mmdc_command() + ["-i", str(input_path), "-o", str(output_path)]
    if theme:
        cmd += ["-t", theme]
    # mermaid-cli >= 11 dropped -w/-H in favour of --size (max width or height).
    if width or height:
        cmd += ["--size", str(max(width or 0, height or 0))]
    if background:
        cmd += ["-b", background]
    cmd += _puppeteer_flags(puppeteer_config)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Capture output: mmdc's stdout would otherwise corrupt the MCP
        # JSON-RPC stream (it shares the server's stdout).
        # stdin must be DEVNULL: a child that inherits the server's stdin pipe
        # never exits cleanly on Windows, so the tool call hangs until the MCP
        # client's read timeout kills the session.
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=_MMDC_TIMEOUT_S)
    except FileNotFoundError:
        raise RuntimeError("mmdc not found. Install with: npm i -g @mermaid-js/mermaid-cli")
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"mmdc did not finish within {_MMDC_TIMEOUT_S}s rendering {input_path.name}"
        )
    except subprocess.CalledProcessError as e:
        # Older/newer mmdc flag incompatibility (e.g. an old CLI without
        # --size): retry once without any size flags so the diagram still
        # renders.
        if "--size" in cmd:
            retry = [c for c in cmd if c not in ("--size", str(max(width or 0, height or 0)))]
            try:
                proc = subprocess.run(retry, check=True, capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL, timeout=_MMDC_TIMEOUT_S)
            except subprocess.CalledProcessError as e2:
                raise RuntimeError(
                    f"mmdc failed (exit {e2.returncode}): "
                    f"{' '.join(shlex.quote(c) for c in retry)}\n"
                    f"{(e2.stderr or '')[:1200]}"
                )
            return
        raise RuntimeError(
            f"mmdc failed (exit {e.returncode}): {' '.join(shlex.quote(c) for c in cmd)}\n"
            f"{e.stderr or e.stdout or ''}"
        )

try:
    from PIL import Image
except Exception:
    Image = None


# --- Mermaid checker/cleaner helpers ---

_ALLOWED_DIAGRAMS = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram",
    "erDiagram", "stateDiagram-v2", "gantt", "journey", "pie"
)

@dataclass
class Issue:
    severity: str   # "error" | "warning" | "info"
    code: str
    message: str
    recommendation: str
    line: int = 1

def _strip_bom(s: str) -> str:
    return s.lstrip("\ufeff")

def _strip_code_fences(s: str):
    issues = []
    lines = s.splitlines()
    if lines and re.match(r"^```+\s*mermaid\s*$", lines[0].strip(), flags=re.I):
        issues.append(Issue("error","FENCE_DETECTED",
                            "Markdown code fences detected (```mermaid ... ```).",
                            "Remove code fences; mmdc expects raw Mermaid text.",1))
        i = 1
        while i < len(lines) and not re.match(r"^```+\s*$", lines[i].strip()):
            i += 1
        content = "\n".join(lines[1:i]) if i < len(lines) else "\n".join(lines[1:])
        return content, issues
    if lines and re.match(r"^```+\s*$", lines[-1].strip()):
        issues.append(Issue("warning","TRAILING_FENCE",
                            "Trailing Markdown fence detected.",
                            "Remove trailing ``` fence.", len(lines)))
        return "\n".join(lines[:-1]), issues
    return s, issues

def _detect_diagram_type(s: str):
    for idx, raw in enumerate(s.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        m = re.match(rf"^({'|'.join(map(re.escape, _ALLOWED_DIAGRAMS))})\b", line)
        if m: return m.group(1), idx
        if re.match(r"^stateDiagram\b", line): return "stateDiagram-v2", idx
        if re.match(r"^graph\b", line): return "graph", idx
        if "-->" in line: return None, idx
    return None, 1

def _extract_init_block(s: str):
    issues = []
    def _json_fixup(body: str) -> str:
        body2 = re.sub(r",\s*([}\]])", r"\1", body)
        body2 = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", lambda m: json.dumps(m.group(1)), body2)
        return body2
    def repl(m):
        nonlocal issues
        raw = m.group(0)
        inner = m.group("json") or "{}"
        fixed = _json_fixup(inner)
        try:
            parsed = json.loads(fixed)
            normalized = json.dumps({"init": parsed}, separators=(",", ":"))
            if raw != f"%%{{ {normalized} }}%%":
                issues.append(Issue("warning","INIT_NORMALIZED",
                                    "init block normalized to strict JSON.",
                                    "Use strict JSON in %%{ init: ... }%% blocks.",1))
            return f"%%{{ {normalized} }}%%"
        except Exception as e:
            issues.append(Issue("error","INIT_JSON_INVALID",
                                f"init block JSON invalid: {e}",
                                "Fix JSON (double quotes, no trailing commas).",1))
            return raw
    pattern = re.compile(r"%%\s*\{\s*init\s*:\s*(?P<json>\{[\s\S]*?\})\s*\}\s*%%")
    s2 = re.sub(pattern, repl, s)
    return s2, issues

def _tidy_whitespace(s: str):
    issues = []
    s2 = s.replace("\r\n","\n").replace("\r","\n")
    before = s2
    s2 = "\n".join(line.rstrip() for line in s2.splitlines())
    if s2 != before:
        issues.append(Issue("info","TRAILING_WS_REMOVED","Trailing whitespace removed.","None",1))
    lines = s2.splitlines()
    if lines and sum(1 for l in lines if l.startswith("  ")) > len(lines)//2:
        s2 = textwrap.dedent(s2)
        issues.append(Issue("info","DEDENTED","Common left indent removed.","None",1))
    return s2, issues

def check_mermaid_text(raw: str) -> dict:
    issues = []
    text = _strip_bom(raw)
    text1, fence_issues = _strip_code_fences(text); issues += fence_issues
    text2, init_issues = _extract_init_block(text1); issues += init_issues
    text3, ws_issues    = _tidy_whitespace(text2);   issues += ws_issues
    dtype, line = _detect_diagram_type(text3)
    if not dtype:
        issues.append(Issue("error","NO_DIAGRAM_DETECTED",
                            "No Mermaid diagram type found at start of file.",
                            "Begin the file with e.g. 'flowchart TD' or 'sequenceDiagram'.", line))
    return {"detected_type": dtype, "issues": [asdict(i) for i in issues]}


def read_mermaid_source(src_p: Path) -> str:
    """Read a Mermaid source, falling back to the run's real diagram file.

    The diagram agents keep the Mermaid text in TextCanvasMemory, so a path like
    `conversation/<session>/canvas_diagram.md` never exists on disk. A bare
    FileNotFoundError crashes the tool call and the reviewer then retries with
    another invented path. Try the canonical file in the same directory and, if
    nothing is there, report what actually exists.
    """
    if src_p.exists():
        return src_p.read_text(encoding="utf-8", errors="replace")
    # Prefer any .mmd in the folder, then Markdown files that are clearly
    # diagram sources. Limiting the .md scan avoids silently returning the
    # functional spec because it happens to contain a fenced `flowchart` block.
    candidates = sorted(src_p.parent.glob("*.mmd")) + [
        p for p in sorted(src_p.parent.glob("*.md"))
        if "diagram" in p.name.lower() or "mermaid" in p.name.lower()
    ]
    for cand in candidates:
        try:
            text = cand.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"(?im)^\s*(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram)\b", text):
            return text
    available = ", ".join(p.name for p in sorted(src_p.parent.iterdir())) or "(empty)"
    raise FileNotFoundError(
        f"No Mermaid source at {src_p}. Mermaid text lives in the canvas, not a file. "
        f"Use {src_p.parent / 'process_diagram.mmd'}, or call check_mermaid_text/clean_mermaid_text "
        f"with the Mermaid string directly. Files in that folder: {available}"
    )

def clean_mermaid_text(raw: str):
    report = check_mermaid_text(raw)
    text = _strip_bom(raw)
    text, _ = _strip_code_fences(text)
    text, _ = _extract_init_block(text)
    text, _ = _tidy_whitespace(text)
    return text, report

# ---------- MCP server ----------

def create_server(allowed_dirs: List[Path], project_root: Path | None = None) -> FastMCP:
    mcp = FastMCP("mermaid-mcp")  # FastMCP 2.0 signature

    @mcp.tool()
    def render_mermaid_svg(
        input_path: str,
        output_path: str,
        theme: str = "default",
        width: Optional[int] = None,
        height: Optional[int] = None,
        background: Optional[str] = None,
        puppeteer_config: Optional[str] = None,
    ) -> str:
        """Render a Mermaid .mmd file to SVG."""
        src = resolve_under_allowed(input_path, allowed_dirs, project_root)
        dst = resolve_under_allowed(output_path, allowed_dirs, project_root)
        if dst.suffix.lower() != ".svg":
            raise ValueError("output_path must end with .svg")
        run_mmdc(src, dst, "svg", theme, width, height, background, puppeteer_config)
        return f"SVG written to {dst}"

    @mcp.tool()
    def render_mermaid_png(
        input_path: str,
        output_path: str,
        theme: str = "default",
        width: Optional[int] = None,
        height: Optional[int] = None,
        background: Optional[str] = None,
        puppeteer_config: Optional[str] = None,
    ) -> str:
        """Render a Mermaid .mmd file to PNG."""
        src = resolve_under_allowed(input_path, allowed_dirs, project_root)
        dst = resolve_under_allowed(output_path, allowed_dirs, project_root)
        if dst.suffix.lower() != ".png":
            raise ValueError("output_path must end with .png")
        run_mmdc(src, dst, "png", theme, width, height, background, puppeteer_config)
        return f"PNG written to {dst}"

    @mcp.tool()
    def png_to_jpg(
        input_png_path: str,
        output_jpg_path: str,
        quality: int = 92,
    ) -> str:
        """Convert a PNG to JPG (RGB)."""
        if Image is None:
            raise RuntimeError("Pillow not installed. pip install pillow")
        src = resolve_under_allowed(input_png_path, allowed_dirs, project_root)
        dst = resolve_under_allowed(output_jpg_path, allowed_dirs, project_root)
        if src.suffix.lower() != ".png":
            raise ValueError("input_png_path must be .png")
        if dst.suffix.lower() not in (".jpg", ".jpeg"):
            raise ValueError("output_jpg_path must be .jpg or .jpeg")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            if im.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.save(dst, quality=quality)
        return f"JPG written to {dst}"

    @mcp.tool()
    def render_mermaid_pdf(
        input_path: str,
        output_path: str,
        theme: str = "default",
        width: Optional[int] = None,
        height: Optional[int] = None,
        background: Optional[str] = None,
        puppeteer_config: Optional[str] = None,
    ) -> str:
        """Render a Mermaid .mmd file directly to PDF via mmdc."""
        src = resolve_under_allowed(input_path, allowed_dirs, project_root)
        dst = resolve_under_allowed(output_path, allowed_dirs, project_root)
        if dst.suffix.lower() != ".pdf":
            raise ValueError("output_path must end with .pdf")
        run_mmdc(src, dst, "pdf", theme, width, height, background, puppeteer_config)
        return f"PDF written to {dst}"

    @mcp.tool()
    def render_mermaid_all(
        input_path: str,
        out_dir: str,
        base_name: str = "process_diagram",
        theme: str = "forest",
        width: Optional[int] = None,
        height: Optional[int] = None,
        background: Optional[str] = None,
        puppeteer_config: Optional[str] = None,
        jpg_quality: int = 92,
        make_jpg: bool = True,
        make_svg: bool = True,
        make_png: bool = True,
        make_pdf: bool = True,
    ) -> str:
        """Render Mermaid to multiple formats in one call."""
        src = resolve_under_allowed(input_path, allowed_dirs, project_root)
        od = resolve_under_allowed(out_dir, allowed_dirs, project_root)
        od.mkdir(parents=True, exist_ok=True)
        made = []

        if make_svg:
            svg = od / f"{base_name}.svg"
            run_mmdc(src, svg, "svg", theme, width, height, background, puppeteer_config)
            made.append(str(svg))

        png_path = None
        if make_png or make_jpg:
            png_path = od / f"{base_name}.png"
            run_mmdc(src, png_path, "png", theme, width, height, background, puppeteer_config)
            made.append(str(png_path))

        if make_jpg:
            if Image is None:
                raise RuntimeError("Pillow not installed for JPG conversion")
            jpg = od / f"{base_name}.jpg"
            with Image.open(png_path) as im:
                if im.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                im.save(jpg, quality=jpg_quality)
            made.append(str(jpg))

        if make_pdf:
            pdf = od / f"{base_name}.pdf"
            run_mmdc(src, pdf, "pdf", theme, width, height, background, puppeteer_config)
            made.append(str(pdf))

        return "Created: " + ", ".join(made)

    @mcp.tool()
    def check_mermaid(
        input_path: str,
        try_compile: bool = True,
        theme: str = "default",
        puppeteer_config: Optional[str] = None,
    ) -> dict:
        """Analyze a Mermaid file; return detected_type, issues[], and optional mmdc_error."""
        src_p = resolve_under_allowed(input_path, allowed_dirs, project_root)
        raw = read_mermaid_source(src_p)
        report = check_mermaid_text(raw)

        if try_compile:
            import tempfile
            from pathlib import Path as _P
            try:
                with tempfile.TemporaryDirectory() as td:
                    tin = _P(td) / "_in.mmd"
                    tout = _P(td) / "_out.svg"
                    cleaned, _ = clean_mermaid_text(raw)
                    tin.write_text(cleaned, encoding="utf-8")
                    cmd = _mmdc_command() + ["-i", str(tin), "-o", str(tout)]
                    if theme:
                        cmd += ["-t", theme]
                    cmd += _puppeteer_flags(puppeteer_config)
                    proc = subprocess.run(cmd, capture_output=True, text=True,
                                          stdin=subprocess.DEVNULL)
                    if proc.returncode != 0:
                        report["mmdc_error"] = {
                            "returncode": proc.returncode,
                            "stdout": proc.stdout[-4000:],
                            "stderr": proc.stderr[-4000:],
                        }
            except FileNotFoundError:
                report["mmdc_error"] = {"message": "mmdc not found; skipped compile step."}
        return report

    @mcp.tool()
    def clean_mermaid(
        input_path: str,
        output_path: str,
        overwrite: bool = False,
    ) -> dict:
        """Clean a Mermaid file (strip fences, normalize init JSON/whitespace)."""
        src_p = resolve_under_allowed(input_path, allowed_dirs, project_root)
        dst_p = resolve_under_allowed(output_path, allowed_dirs, project_root)
        if dst_p.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing: {dst_p}")
        raw = read_mermaid_source(src_p)
        cleaned, report = clean_mermaid_text(raw)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        dst_p.write_text(cleaned, encoding="utf-8")
        return {"written_to": str(dst_p), "bytes": len(cleaned.encode('utf-8')), **report}


    return mcp

def main():
    parser = argparse.ArgumentParser(description="Mermaid MCP stdio server (mmdc wrapper)")
    parser.add_argument("-d", "--dir", dest="dirs", action="append", required=True,
                        help="Allowed directory (can be passed multiple times)")
    parser.add_argument("--project-root", dest="project_root", default=None,
                        help="Default root for resolving relative or 'project_root/...' paths")
    args = parser.parse_args()

    allowed_dirs = [Path(d).expanduser().resolve() for d in args.dirs]
    for d in allowed_dirs:
        if not d.exists():
            print(f"[WARN] allowed dir does not exist yet: {d}", file=sys.stderr)

    print(f"[INFO] Allowed roots: {', '.join(map(str, allowed_dirs))}", file=sys.stderr)

    pr = Path(args.project_root).expanduser().resolve() if args.project_root else None
    if pr and pr not in allowed_dirs:
        allowed_dirs.append(pr)
    mcp = create_server(allowed_dirs, project_root=pr)

    # Entry point may differ between versions
    if hasattr(mcp, "run_stdio"):
        mcp.run_stdio()
    else:
        mcp.run()

if __name__ == "__main__":
    main()

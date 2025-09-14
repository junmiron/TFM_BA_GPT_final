#!/usr/bin/env python3
import argparse
import os
import sys
import shlex
import subprocess
from pathlib import Path
from typing import Optional, List
from fastmcp import FastMCP

# ---------- Config & helpers ----------

def resolve_under_allowed(path: str, allowed: List[Path]) -> Path:
    p = Path(path).expanduser().resolve()
    for root in allowed:
        try:
            p.relative_to(root)
            return p
        except Exception:
            continue
    raise ValueError(f"Path not in allowed directories: {p}")

def run_mmdc(input_path: Path, output_path: Path, fmt: str,
             theme: Optional[str] = None,
             width: Optional[int] = None,
             height: Optional[int] = None,
             background: Optional[str] = None,
             puppeteer_config: Optional[str] = None) -> None:
    cmd = ["mmdc", "-i", str(input_path), "-o", str(output_path)]
    if theme:
        cmd += ["-t", theme]
    if width:
        cmd += ["-w", str(width)]
    if height:
        cmd += ["-H", str(height)]
    if background:
        cmd += ["-b", background]
    if puppeteer_config:
        cmd += ["-p", puppeteer_config]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise RuntimeError("mmdc not found. Install with: npm i -g @mermaid-js/mermaid-cli")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"mmdc failed (exit {e.returncode}): {' '.join(shlex.quote(c) for c in cmd)}")

try:
    from PIL import Image
except Exception:
    Image = None

# ---------- MCP server ----------

def create_server(allowed_dirs: List[Path]) -> FastMCP:
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
        src = resolve_under_allowed(input_path, allowed_dirs)
        dst = resolve_under_allowed(output_path, allowed_dirs)
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
        src = resolve_under_allowed(input_path, allowed_dirs)
        dst = resolve_under_allowed(output_path, allowed_dirs)
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
        src = resolve_under_allowed(input_png_path, allowed_dirs)
        dst = resolve_under_allowed(output_jpg_path, allowed_dirs)
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
        src = resolve_under_allowed(input_path, allowed_dirs)
        dst = resolve_under_allowed(output_path, allowed_dirs)
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
        src = resolve_under_allowed(input_path, allowed_dirs)
        od = resolve_under_allowed(out_dir, allowed_dirs)
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

    return mcp

def main():
    parser = argparse.ArgumentParser(description="Mermaid MCP stdio server (mmdc wrapper)")
    parser.add_argument("-d", "--dir", dest="dirs", action="append", required=True,
                        help="Allowed directory (can be passed multiple times)")
    args = parser.parse_args()

    allowed_dirs = [Path(d).expanduser().resolve() for d in args.dirs]
    for d in allowed_dirs:
        if not d.exists():
            print(f"[WARN] allowed dir does not exist yet: {d}", file=sys.stderr)

    print(f"[INFO] Allowed roots: {', '.join(map(str, allowed_dirs))}", file=sys.stderr)

    mcp = create_server(allowed_dirs)

    # Entry point may differ between versions
    if hasattr(mcp, "run_stdio"):
        mcp.run_stdio()
    else:
        mcp.run()

if __name__ == "__main__":
    main()

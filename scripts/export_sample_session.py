#!/usr/bin/env python3
"""Export a recorded session into the committed sample session (Feature 14).

Copies only the deliverables and the replay log - no probe files, no fragment
cache, no intermediates - into examples/sample_session/, and writes a README
generated from replay_meta.json.

Usage:
    python scripts/export_sample_session.py conversation/sess-demo-20261108000000
    python scripts/export_sample_session.py <session_dir> --out examples/sample_session

The session must contain replay_events.jsonl + replay_meta.json (produced by
scripts/record_demo_replay.py).
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Allow-list: real deliverables only.
FILES = [
    "functional_specification.pdf",
    "functional_specification.html",
    "functional_specification.md",
    "functional_specification.formatted.md",
    "interview.jsonl",
    "canvas_diagram.md",
    "process_diagram.mmd",
    "process_diagram.png",
    "process_diagram.svg",
    "process_diagram_2.mmd",
    "process_diagram_2.png",
    "process_diagram_2.svg",
    "process_diagram_3.mmd",
    "process_diagram_3.png",
    "process_diagram_3.svg",
    "process_diagram_4.mmd",
    "process_diagram_4.png",
    "process_diagram_4.svg",
]

REPLAY_FILES = [
    ("replay_events.jsonl", "replay/events.jsonl"),
    ("replay_meta.json", "replay/meta.json"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", help="Path to the recorded session folder")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "examples" / "sample_session"))
    args = parser.parse_args()

    src = Path(args.session_dir).resolve()
    if not src.is_dir():
        print(f"error: {src} is not a directory", file=sys.stderr)
        return 2
    meta_path = src / "replay_meta.json"
    if not meta_path.is_file():
        print("error: session has no replay_meta.json - run scripts/record_demo_replay.py first", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("error"):
        print(f"error: recorded run failed: {meta['error']}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    copied, missing = [], []
    for name in FILES:
        f = src / name
        if f.is_file():
            (out / name).write_bytes(f.read_bytes())
            copied.append(name)
        else:
            missing.append(name)
    for src_name, dst_name in REPLAY_FILES:
        f = src / src_name
        if f.is_file():
            dst = out / dst_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(f.read_bytes())
            copied.append(dst_name)
        else:
            missing.append(src_name)

    sizes = sum((out / c).stat().st_size for c in copied)
    readme = f"""# Sample session: WashLoop laundry service shop app

A real end-to-end BA-GPT run, committed so you can see the output without
running anything. Generated on {date.today().isoformat()} from session
`{meta.get('session_id', 'unknown')}`.

- Goal (fixed): the text in [`demo/goal.md`](../../demo/goal.md)
- Agents: {meta.get('event_counts', {}).get('message', 0)} agent messages,
  {meta.get('event_counts', {}).get('answer', 0)} stakeholder answers,
  {meta.get('event_counts', {}).get('info', 0)} status updates
  ({meta.get('event_count', 0)} events total, wall clock ~{meta.get('wall_duration_s', 0) // 60} min)
- Model lanes: agents `{meta.get('lanes', {}).get('model_client')}`,
  tools `{meta.get('lanes', {}).get('model_client_tools')}`,
  simulated stakeholder `{meta.get('lanes', {}).get('human_model')}`

## Files

| File | What it is |
|---|---|
| `functional_specification.pdf` | Typst-typeset spec (cover, linked TOC, diagrams split per page) |
| `functional_specification.html` | Self-contained HTML with the process diagram inline as SVG |
| `functional_specification.md` / `.formatted.md` | Markdown spec and Pandoc-formatted variant |
| `interview.jsonl` | Timestamped Q&A audit trail |
| `canvas_diagram.md` + `process_diagram*.mmd/.png/.svg` | Mermaid sources and renders |
| `replay/events.jsonl` | Full timestamped event log the interactive demo replays |
| `replay/meta.json` | Run metadata (task, lanes, duration, event counts) |

Reproduce this run yourself: `python scripts/record_demo_replay.py`, then
`python scripts/export_sample_session.py conversation/<session-id>`.
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    copied.append("README.md")

    print(f"exported {len(copied)} files ({sizes / 1e6:.1f} MB of content) to {out}")
    if missing:
        print("not present in the session (skipped): " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())

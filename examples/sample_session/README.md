# Sample session: WashLoop laundry service shop app

A real end-to-end BA-GPT run, committed so you can see the output without
running anything. Generated on 2026-11-08 from session
`sess-demo-washloop`.

- Goal (fixed): the text in [`demo/goal.md`](../../demo/goal.md)
- Agents: 93 agent messages,
  18 stakeholder answers,
  2 status updates
  (115 events total, wall clock ~44 min)
- Model lanes: agents `strata`,
  tools `strata`,
  simulated stakeholder `opencode`

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

## Which deliverable to use

- **HTML** - the recommended way to read the spec: self-contained, navigable,
  printable, diagram inline.
- **PDF** - the typeset copy for signatures, printing and formal review.
- **Markdown** - the best base to hand to an AI coding agent as a spec to
  implement from.

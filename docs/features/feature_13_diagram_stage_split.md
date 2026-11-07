# Feature 13 — Long process diagrams: stage-aware split instead of pixel banding

Session under review: `conversation/sess-20261106143438`
Related commits: `b09f356` (quiet-row band cuts), `0e495ef` (pandoc HR fix)

## 1. Problem

The end-to-end process diagram (`process_diagram.clean.mmd`, rendered 784 x 7749 px)
is ~12 pages tall. The PDF pipeline bands any image taller than the page into
PNG strips at "quiet" rows. Even with the snapped cuts, a reader sees one
diagram sliced into 8 strips with connector lines severed at page breaks —
the "cut in the middle" complaint.

## 2. Review of Claude's solution (`C:\Users\junmi\Downloads\files`)

**What it does well**
- Splits the flowchart into one page per stage (6 pages) using the `subgraph Stage N` structure.
- Replaces every cross-stage edge with paired off-page connector nodes (ISO-style OUT/IN flags with Ref letters). Loop-backs handled.
- Node/page assignment rule: nodes declared inside a subgraph belong to it; nodes declared outside are pulled by nearest upstream BFS — the X6 (refund) placement decision is reasonable.
- `split_stages.py` is deterministic and re-runnable.

**Measured problems (mmdc 12.2.0, A4 content box 447 x 640 pt)**

| Page | SVG size | Height at 447 pt width | Fits one page? |
|---|---|---|---|
| P1 sched | 891 x 1863 | 935 pt | **No** |
| P2 coll | 640 x 1820 | 1271 pt | **No** |
| P3 proc | 669 x 2170 | 1449 pt | **No** |
| P4 pay | 912 x 2343 | 1148 pt | **No** |
| P5 close | 649 x 921 | 634 pt | Yes |
| P6 kpi | 943 x 431 | 204 pt | Yes |

So the split reduces cuts but 4 of 6 pages still get band-cut by the existing
pipeline. The split is a **necessary but not sufficient** step.

**Critical rendering bug**: the provided SVGs use Mermaid's default
`htmlLabels: true`, which puts every label in a `<foreignObject>` (88 of them
in page 1). Typst cannot render `foreignObject`:
- it warns `image contains foreign object`,
- and it **drops all node labels** — QA on `claude_pipeline.pdf` (Claude's
  SVGs through the repo pandoc->typst pipeline) found 0 of 7 tested labels.
Fix: render with `{"mermaid": {"flowchart": {"htmlLabels": false}}}` so labels
become native SVG `<text>` (verified: labels survive as real, selectable PDF
text).

**Hard-coded specifics**: the `PIN = {"Q1": "COLL"}` table and stage naming
are hand-tuned for this diagram; agents generate different diagrams every
run, so the logic must be generalized.

## 3. Engine test: Typst+pandoc vs Typst alone

| Path | Diagram embedding | Labels | Verdict |
|---|---|---|---|
| pandoc md -> typst -> PDF (current pipeline) with **PNG** bands | raster | baked into pixels | works but blurry, band-cut |
| pandoc md -> typst -> PDF with **SVG fragments** (htmlLabels off) | native vector | real selectable text | **works** (demo: 58-page full spec, labels extractable) |
| Typst hand-written `.typ` (no pandoc) with SVG | native vector | real selectable text | works; same SVG caveat |

Typst embeds SVG natively — no conversion step needed, pandoc just passes the
`image(...)` through. The one hard requirement is `htmlLabels: false`.

## 4. Proposed design

**Stage-split + auto sub-split + vector SVG**, generalized from Claude's idea:

1. **Split at stage boundaries** (Claude's idea, generalized): parse the
   flowchart's `subgraph` blocks; orphan nodes assigned by upstream BFS; no
   hand-written PINs (configurable per session if ever needed).
2. **Auto sub-split oversized stages**: render each stage SVG, measure the
   viewBox; if height at content width > 640 pt, recursively split that stage
   by topological rank bands (already prototyped) until every fragment fits.
3. **Off-page connectors** for every cross-fragment edge: `OUT_Rx` / `IN_Rx`
   flag nodes (`@{shape: odd}`, Mermaid >= 11.3; CI pins 12.2.0). Edge labels
   stay on the source side. A connector-index table is emitted next to the
   figures so a reader can follow the flow between parts.
4. **Render fragments as SVG** with `htmlLabels: false` (vector, selectable
   labels) and keep PNG as a fallback when SVG embedding fails.
5. **Height-aware sizing**: fragment width % = min(95%, content_width *
   page_cap / natural_height) so portrait fragments never overflow the page.
   (The demo's 3 oversized images came from width-only scaling.)
6. **Keep quiet-row banding** (`b09f356`) as the fallback for diagram types
   that can't be graph-split (sequence diagrams, state machines, ERDs) and
   for flowcharts whose parse fails.
7. **HTML deliverable**: unchanged inline full SVG (no pagination in HTML).

## 5. Implementation plan

- **P1 — `diagram_split.py`** (new module in `mcp_servers/Final_deliverable_MCP_server/`):
  Mermaid parser, stage/assign logic, connector generation, rank-band
  sub-split. Pure stdlib, unit-testable without mmdc.
- **P2 — pipeline wiring**:
  - `lib/agents_tools_helpers.py::render_diagram_pngs` also emits
    `process_diagram_p1..N.svg/png` fragments for splittable flowcharts, and
    `embed_diagram_in_markdown` references them as numbered figures
    ("Process flow — part 1 of 6").
  - `typst_render._fit_diagram_images` keeps banding only as fallback; adds
    SVG support and height-aware scaling.
  - mmdc invocations get `-c` with `{"mermaid":{"flowchart":{"htmlLabels":false}}}`.
- **P3 — tests**:
  - Splitter: every original node/edge present exactly once; connector pairs
    symmetric; fragment count stable.
  - Fit: every fragment renders with height <= 640 pt at 447 pt width.
  - End-to-end: re-render `sess-20261106143438` spec; assert labels are
    selectable text in the PDF and 0 oversized images.
- **P4 — docs**: CHANGELOG entry, this feature doc, README tweak if needed.

Estimated: ~350 new lines + ~150 test lines. No dependency changes.

## 6. Acceptance criteria

- No diagram fragment exceeds one A4 page; no node box is ever sliced.
- Cross-stage links are explicit (Ref letters + connector index).
- Labels are selectable vector text in the PDF.
- Sequence/state/ER diagrams still render (banding fallback).
- Full backend suite green; CI green; re-rendered session PDF QA clean.

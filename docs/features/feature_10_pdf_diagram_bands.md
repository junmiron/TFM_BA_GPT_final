# Feature 10 - PDF diagram clipping

Status: implemented (2026-11-06).

## Root cause (measured)
The rendered diagram is a single tall PNG: `process_diagram.png` =
**511 x 2096 px**. Pandoc turns the Markdown image into an atomic
`#figure(image(..., width: 100%))`. At the 469 pt content width the figure
measures ~1924 pt tall - the page's content box is only **706 pt**, and
Typst never splits a figure: roughly **63% of the diagram is clipped**
(the same atomic-figure problem already solved for tables by row-chunking).

## Options considered
| Option | Result |
|---|---|
| A. Fit-scale whole image to 706 pt height | Labels render at ~2-3 pt - illegible |
| B. Force Mermaid `flowchart LR` (wide layout) | Changes diagram semantics; agents author TD layouts |
| C. **Band-split the PNG into page-sized slices at full width** | Labels stay legible; mirrors the proven table chunking |

**Recommended: C.**

## Design (option C)
1. In the finalize step (before Typst render), read the diagram PNG size with
   PIL. If its height at 469 pt width exceeds the content box, split it into
   `N = ceil(height_pt / 700)` bands, each ~700 pt tall at full width, with a
   ~30 pt overlap so no node label sits exactly on a cut.
2. Write `process_diagram_part1.png` ... `process_diagram_partN.png` into the
   session folder.
3. Post-processing pass in `typst_render.py` (like `fix_table_columns`)
   replaces the single figure with N figures, captioned
   "Process diagram (part k of N)".
4. Diagrams that already fit are untouched.
5. QA gate: render the real deliverable, use PyMuPDF to assert every band's
   bounding box is inside the page and nothing is clipped at margins.

## Files touched
- `mcp_servers/Final_deliverable_MCP_server/typst_render.py`
- `lib/agents_tools_helpers.py` (band generation)
- `tests/test_typst_render.py` (band-splitting unit tests)
- `.gitignore` if band PNGs should not be tracked (they are session artifacts,
  already inside `conversation/`)

## Acceptance
- PDF shows the complete diagram across consecutive pages, full width,
  readable labels; HTML unchanged.

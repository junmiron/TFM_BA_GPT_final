# Feature 6 - Prominent "Download Functional Spec PDF" button

Status: implemented (2026-11-06).

## Problem
The header button reads "Download spec" and downloads whichever artifact
`findSpecArtifact` picks - currently the Markdown file first
(`functional_specification.md` wins over `.pdf`). Placement is not prominent
and the label is wrong.

## Design
- One primary action in a **centered action row in the header, directly
  above the transcript**: label exactly **"Download Functional Spec PDF"**
  (approved placement: header, centered above the transcript).
- Target is always the `functional_specification.pdf` artifact.
- When the PDF does not exist yet (run not finished) the button is rendered
  greyed out (disabled) with title "The PDF appears once the run finishes" -
  it never disappears, matching the fixed-box philosophy of Feature 5.
- `findSpecArtifact` is replaced by `findPdfArtifact`; the fallback chain for
  other files stays in the Artifacts panel rows.
- Keep the per-artifact "Download" rows in the panel for md/html/png/svg.

## Files touched
- `ui/src/components/Header.tsx` - label, disabled state.
- `ui/src/lib/artifacts.ts` - `findPdfArtifact(artifacts)`.
- `ui/src/App.tsx` - wire the PDF artifact.
- vitest in `ui/src/lib` - artifact selection test.

## Acceptance
- Button reads "Download Functional Spec PDF".
- Click downloads the PDF when present; greyed out otherwise.

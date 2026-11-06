# Feature 11 - Friendlier web-version link label

Status: implemented (2026-11-06). Label chosen: "Open Functional Spec in browser".

Current label: "View web version".

Candidates:
- **"Open Functional Spec in browser"** (recommended - says what it is and
  that it opens in a new tab)
- "View Functional Spec (web)"
- "Read the full spec online"

Change is one string in `ui/src/components/Header.tsx` plus the existing
vitest that asserts the label. Disabled/greyed text stays "View web version"
until the HTML exists - will use the same new label with tooltip "The web
version appears once a run finishes".

## Files touched
- `ui/src/components/Header.tsx`
- vitest label assertion

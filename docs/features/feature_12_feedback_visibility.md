# Feature 12 - Feedback request must always be visible

Status: implemented (2026-11-06).

## Root cause
The satisfaction question renders as a transcript turn at the very end of
the scroll pane. The auto-scroll rule (`ui/src/lib/scroll.ts`) follows the
latest turn only when the reader is near the bottom, and forces a scroll only
when a *question* is pending. A `feedback_request` is not a question
(`awaitingQuestion` returns null by design), so a user who scrolled up to
read history never sees the Yes/No buttons - the run ends silently.

## Design (two layers)
1. **Pin the feedback request into the fixed question box (recommended).**
   Feature 5 made the composer always present. Extend it with a
   `feedback` state: when `feedback_request` is the latest pending event, the
   fixed bottom box shows the question and "Yes, deliverables are good" /
   "Not quite..." buttons plus the comment field. The transcript keeps a
   plain record bubble so the audit trail stays readable.
2. **Scroll attention flag**: `shouldFollowLatest` gains an
   `attentionPending` parameter that is true for pending questions **and**
   pending feedback; App passes `question || pendingFeedback`. Belt and
   braces for Chainlit, which has no pinned composer.

## Files touched
- `ui/src/components/AnswerBox.tsx` - feedback variant
- `ui/src/components/Transcript.tsx` - render record bubble only when the
  pinned box is not showing the live feedback prompt
- `ui/src/lib/scroll.ts` + `ui/src/App.tsx` - attention flag wiring
- `ui/src/state/runState.ts` - `pendingFeedback(thread)` helper
- `ui/src/lib/scroll.test.ts`, `runState.test.ts` - new cases

## Acceptance
- The Yes/No prompt is visible without manual scrolling in every terminal
  state; silence still means "no feedback"; tests cover the new state.

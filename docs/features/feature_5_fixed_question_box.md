# Feature 5 — Fixed interview question box

Status: implemented (2026-11-06).

## Problem
The answer composer (`AnswerBox`) is rendered only while a question exists:
`ui/src/App.tsx` guards it with `{question && <AnswerBox ... />}`. The box
appears and disappears, so the user never sees where to answer and the layout
jumps.

## Design
- Always render the question box at the bottom of the transcript column.
- Three states:
  1. **Question pending** (current behaviour): primary border, focused textarea,
     "Send answer" enabled when text is non-empty.
  2. **No question, run active**: greyed-out box — disabled textarea, muted
     border, caption "No question right now - the agents are working".
  3. **No run / finished session**: greyed-out box with caption "Start or
     continue a session to see interview questions".
- The question text arrives via the existing `awaitingQuestion(thread)`
  derivation; only the wrapper state changes. No backend change.
- Accessibility: `aria-live="polite"` on the caption; disabled controls get
  `aria-disabled`; box keeps a stable height so the transcript scroll position
  does not jump.

## Files touched
- `ui/src/components/AnswerBox.tsx` - add `state` prop ('question' | 'idle' | 'none').
- `ui/src/App.tsx` - remove the `question &&` guard; compute the state.
- `ui/src/state/runState.test.ts` / new vitest - reducer unchanged; component
  logic stays simple and testable.

## Acceptance
- The box is visible from session start to end.
- It never accepts input when there is no pending question.
- Transcript scroll position is stable when a question appears/disappears.

# Feature 3 — Continue an existing session: add information to the spec

Status: implemented (2026-11-06).

Implemented as:
- `POST /api/sessions/{id}/continue` with `{"supplement": "..."}`.
- `lib/continuation.py`: appends the supplement to `supplements.jsonl` (audit),
  merges it into `functional_specification.md` via the writer model, and a
  deterministic guard rejects any rewrite that drops existing headings - in
  that case an "Addendum (client supplement)" section is appended instead, so
  content is never lost.
- Version bump (`v1.2 -> v1.3`) in the metadata row/line, then
  `finalize_deliverables()` re-renders PDF/HTML/MD in the same session folder.
- UI: a "Add information to this specification" box appears under the
  transcript for any selected session that has artifacts, and the artifact
  list is refreshed after the update.
- Tests: `tests/test_continuation_transcript.py`.

## Goal
Selecting an existing session in the UI should let the user provide extra
information and have it merged into the existing functional specification,
re-rendering the deliverables.

## Current state
- Sessions on disk (`conversation/sess-.../`) appear in the session rail via
  `_persisted_sessions()` in `server/api.py`, but selecting one is read-only: the
  UI shows artifacts and an empty transcript ("This session ran earlier...").
- The workflow is single-shot: `create_workflow` + `run_workflow` builds a fresh
  team each time; `run_workflow` calls `team.reset()` and starts from `task_text`.
- `finalize_deliverables` (lib/agents_tools_helpers.py) is deterministic: given a
  `functional_specification.md` in the session dir it re-renders PNG/SVG/PDF/HTML.
- `interview.jsonl` holds the Q&A pairs; interview routing helpers
  (`current_round`, `question_from_coverage`) work off the conversation history.

## Design decision: in-place continuation, not a new session
The natural expectation is "add info to THIS spec". A new session id would break
links, the ledger, and the artifacts panel. So:

- Same session folder, same id. Spec version increments
  (Title Page metadata: `Version 1.0` → `1.1`, read by the Typst cover from the
  formatted markdown metadata).
- A `supplements.jsonl` file in the session dir records every continuation
  round: `{"ts": ..., "supplement": "...", "kind": "clarification|requirement|correction"}`.

## Flow
1. UI: selecting a persisted session shows the existing spec summary + a
   "Add information" composer (reusing AnswerBox) with a placeholder like
   "Add requirements, corrections, or context to this specification".
2. `POST /api/sessions/{id}/continue` with `{"supplement": "..."}`:
   - loads the existing `functional_specification.md`;
   - appends the supplement to `supplements.jsonl`;
   - starts a CONTINUATION run in the same folder.
3. Continuation run (new mode flag in `create_workflow(continuation=...)`):
   - the team is the same, but the planner is seeded with:
     existing spec + supplements + prior interview.jsonl;
   - the writer agent is instructed to PATCH rather than rewrite: it reads the
     current spec from disk, merges the new information into the right sections,
     and keeps FR numbering consistent (adds FR-xx.y items under existing groups);
   - the checker rounds still run (`MAX_CHECKER_ROUNDS`);
   - diagram: if the supplement changes statuses/states, the mermaid source is
     regenerated; otherwise the existing diagram is reused;
   - `finalize_deliverables` re-renders PDF/HTML/MD, so the artifacts panel shows
     updated files with fresh timestamps.
4. Transcript: the continuation run streams into the same live session object so
   the UI replays both the original (if still in memory) and the new run. For
   sessions only on disk, the continuation run starts a fresh event log seeded with
   a summary event ("Resuming sess-... from version 1.0").

## Guardrails
- One active continuation run per session (reject concurrent `continue` while
  status is `running`).
- Continuation inherits Feature 1: after a continuation finishes, the satisfaction
  question is asked again, and only happy sessions get re-indexed (upserts).
- Chainlit view: same continuation logic via a command (`/continue`) — optional,
  decide at approval.
- If the session folder has no `functional_specification.md`, `continue` returns
  409 with "no specification to extend".

## Changes
- `server/api.py`: `/api/sessions/{id}/continue` endpoint; `Session` gains
  `version` and `resumed_from_disk` fields; `_persisted_sessions()` reports
  `version` (parsed from spec metadata).
- `lib/pipeline.py`: `create_workflow(..., continuation: Optional[dict])` — seeds
  planner/writer prompts with the existing spec + supplements, and the termination
  step skips interview questions already answered.
- `lib/agents_tools_helpers.py`: `bump_spec_version(session_dir)`; version is
  written into the formatted markdown metadata block the Typst cover reads.
- `ui/src/components/SessionRail.tsx`: composer for persisted sessions;
  `AnswerBox` reused; disabled while a run is active.
- Tests: continuation merges supplements into the spec (deterministic writer for
  the test), version bump, concurrent-run rejection, artifacts regenerated.

## Acceptance criteria
1. Selecting an old session shows a composer.
2. Submitting info re-renders PDF/HTML/MD with the new content and version 1.1.
3. Nothing is lost from the previous spec (merge, not overwrite).
4. The interview quality assertions still apply to the continuation run.

## Open questions
- Should continuation re-run a mini-interview (ask follow-ups) or strictly apply
  the supplied text? (Recommend: apply text, then let the checker flag gaps the
  interviewer can ask about — covered by the existing coverage logic.)

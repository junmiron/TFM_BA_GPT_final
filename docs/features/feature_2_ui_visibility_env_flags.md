# Feature 2 — .env switches to hide the artifacts panel and internal agent chatter

Status: implemented (2026-11-06).

Implemented as:
- `UI_SHOW_ARTIFACTS` / `UI_SHOW_INTERNAL_MESSAGES` in `.env`, exposed by
  `/api/health` under `ui.show_artifacts` / `ui.show_internal`.
- `RunPanel.tsx` renders the Artifacts panel only when the flag is on.
- `Transcript.tsx` filters planner/summarizer/writer/checker/use-case turns out
  of the visible transcript when `show_internal` is false; interviewer and user
  turns, info and errors stay visible. The backend event log keeps everything
  for audit and for the feedback loop.
- Tests: `test_health_reports_ui_visibility_flags`.

## Goal
Two `.env` flags that change what the web UI shows:
1. `UI_SHOW_ARTIFACTS` — hide the Artifacts box in the right rail.
2. `UI_SHOW_INTERNAL_MESSAGES` — hide internal agent messages; the transcript shows
   only the conversation history (interviewer questions + user answers), plus
   errors.

## Current state
- The right rail is `ui/src/components/RunPanel.tsx`: "Artifacts" Panel + "Workflow"
  Panel. Artifacts come from the `artifacts` WS event and
  `GET /api/sessions/{id}/artifacts`.
- The transcript renders every event: `message` (all agents), `chunk` (streaming),
  `answer` (user), `info` (system notices), `error`. `ui/src/lib/roles.ts` maps agent
  sources to role labels; "internal" messages are planner/summarizer/writer/checker/
  diagram/reviewer/terminate chatter.
- The backend already reads `.env` at startup and exposes config via `/api/health`
  (`simulate_human`, `max_messages`, lane names). The UI fetches health once at
  startup (`ui/src/lib/api.ts` has a health call used for lanes/budget).

## Design

### Backend
`server/api.py` `/api/health` gains:

```python
"ui": {
    "show_artifacts": os.getenv("UI_SHOW_ARTIFACTS", "true").lower() in ("1","true","yes"),
    "show_internal":  os.getenv("UI_SHOW_INTERNAL_MESSAGES", "true").lower() in ("1","true","yes"),
}
```

No other backend change: events keep being recorded in full (the audit trail and
Feature 1 feedback depend on them); only the UI's rendering is filtered. That keeps
reconnect replay, debugging and the interview.jsonl untouched.

### UI
- `App.tsx` already loads health → store the two booleans in the run state.
- **Hide artifacts:** `RunPanel` conditionally omits the Artifacts Panel. The
  Workflow panel takes its place. Download endpoint stays available for API users.
- **Hide internal messages:** in `runState.ts` reducer (single choke point), when
  `show_internal === false`:
  - keep: `answer` (user), interviewer `message` events, `error`, and a minimal
    "Run started / Run finished / Stages complete" set of `info` lines;
  - drop: planner/summarizer/writer/checker/diagram/reviewer/terminate messages and
    their streaming chunks.
  The header lane indicator still shows model lanes (it is diagnostic, not chat).
- Empty-state text adapts: "Only the interview conversation is shown (internal
  agent messages are hidden by configuration)."

### .env additions (and `.env.example`)
```bash
UI_SHOW_ARTIFACTS=true
UI_SHOW_INTERNAL_MESSAGES=true
```

## Edge cases
- Turn budget panel: with internal messages hidden, the "N of M turns" counter still
  counts all events server-side (the real budget) — keep it, it is accurate.
- Hidden artifacts panel + Feature 1: the satisfaction widget lives in the
  transcript, not the artifacts box, so hiding artifacts does not break feedback.
- Historical sessions: persisted sessions have no event log in memory anyway; the
  filter only affects live runs.

## Tests
- Backend: health returns the flags; defaults are true; `false` values propagate.
- UI reducer tests: with `show_internal=false` a planner message produces zero turns,
  an interviewer question and a user answer do; errors always render.
- RunPanel test: artifacts panel absent when flag is off.

## Acceptance criteria
1. `UI_SHOW_ARTIFACTS=false` → no Artifacts box anywhere in the UI.
2. `UI_SHOW_INTERNAL_MESSAGES=false` → transcript shows only question/answer pairs
   (plus errors and run status).
3. Both default to current behaviour when unset.

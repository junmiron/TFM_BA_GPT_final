# Feature 1 — Reinforcement learning from satisfied sessions (feedback → RAG → fine-tune ledger)

Status: implemented (2026-11-06).

Implemented as:
- `lib/experience_indexer.py` - deterministic indexing of deliverables (spec MD,
  formatted MD, diagram MMD, interview Q&A pairs) into the `approved_experiences`
  ChromaDB collection, upsert-safe with ids `<session>-<file>-<chunk>`.
- `experiences/reinforcement_learning.md` - the ledger (session, date, task,
  chunks indexed, feedback). Fine-tune examples per session in
  `experiences/fine_tune/<session_id>.jsonl` (instruction/output pair).
- `feedback/<session_id>.md` + `.json` for unhappy runs; nothing is indexed then.
- Env: `FEEDBACK_ENABLED`, `FEEDBACK_TIMEOUT_S`, `RAG_APPROVED_COLLECTION`.
- Server gate: after `artifacts`, a `feedback_request` event is emitted and the
  run waits (max `FEEDBACK_TIMEOUT_S`) for a WS `feedback` message or a
  `POST /api/sessions/{id}/feedback`. Silence indexes nothing.
- Chainlit lane: `app2.py` asks the same question via `cl.AskUserMessage`.
- `lib/pipeline.py` attaches the approved-experiences memory to the agents so
  new runs can imitate previously approved work.
- Tests: `tests/test_experience_indexing.py`, feedback tests in
  `tests/test_server_api.py`.

## Goal
When a run completes, ask the user whether they are happy with the deliverables.
- Happy → feed the deliverables into the RAG memory the agents query, and record the
  session in a reinforcement-learning ledger (a Markdown document listing every
  satisfied session, later usable to fine-tune a model).
- Not happy → collect "what was wrong", save it to a feedback folder keyed by session
  id, and do NOT index anything into RAG.
- A `.env` switch enables/disables the whole feedback loop.

## Current state (verified in code)
- `lib/pipeline.py:127-137` builds ONE ChromaDB memory from `lib/rag_config.yaml`
  (collection `rag_collection`, seeded from web sites + `data/`) and attaches it to
  the planning, interviewer, summarizer, writer, checker and use-case agents
  (`memory=rag_memories` at lines 368, 391, 426, 452, 531, 586).
- `save_experience_chroma` (`mcp_servers/Final_deliverable_MCP_server/PDF_format_mcp_server.py:1791`)
  is invoked by the terminate agent's step list and indexes the whole session into a
  DIFFERENT collection, `tfm_ba_gpt_experiences` - that legacy tool and its collection were removed (2026-11-06) because nothing queried it
  during a run, and it is the tool that timed out (180 s) in the parked issue.
- `server/api.py:284-311` is the end-of-run hook: after `run_workflow` returns
  `stop_reason`, the session is marked `done` and an `artifacts` event is emitted.
  There is no post-run interaction today.
- Chainlit (`app2.py`) is the operator/debug view; it has no end-of-run prompt either.
- `Session.record(event)` broadcasts any dict to the UI over `/ws/sessions/{id}`;
  `_handle_client_message` accepts only `answer` and `stop` today.

## Design

### 1. End-of-run satisfaction question (UI + backend)
After the `complete`/`artifacts` events, the backend records a new event:

```json
{"type": "feedback_request", "question": "Are you happy with the quality of the deliverables?"}
```

The UI renders a compact widget in the transcript (two buttons: Yes / No, styled like
the existing AnswerBox). If "No" is clicked, a free-text box appears: "What did you
not like?". The answer travels over the existing WebSocket as:

```json
{"type": "feedback", "satisfied": true|false, "comment": "optional text"}
```

Chainlit gets the same question via an `input()`-style prompt (best-effort; the
feedback loop still works if nobody answers).

Timeout/absence policy: if no feedback arrives within `FEEDBACK_TIMEOUT_S` (default
300 s) or the browser closes, the session is recorded as `feedback: "none"` and
nothing is indexed. Silence is NOT satisfaction.

### 2. Happy path — feed the deliverables to RAG
New deterministic function (no model calls), `lib/rag_helpers.py`:

```python
def index_approved_deliverables(session_dir: Path, session_id: str,
                                collection: str | None = None) -> dict
```

It chunks and inserts only the approved output (this replaces the blanket
`save_experience_chroma` step for the happy path):
- `functional_specification.md` → semantic chunks (reuse `split_text`, 500/50)
- `functional_specification.formatted.md` → same (dedupe by content hash)
- `process_diagram.mmd` + `process_diagram.clean.mmd` → diagram source chunks
- `interview.jsonl` → one chunk per Q&A pair (the highest-value signal:
  question + the stakeholder answer that produced a good spec)
- metadata on every chunk: `kind: "approved-deliverable"`, `session_id`,
  `task`, `title`, `date`, `source_file`.

Collection choice (open question, see Questions at the end):
- **Recommended:** a dedicated collection `approved_experiences`, attached as a
  SECOND memory to the interview/writer agents at run start. Keeping it separate
  means web-scraped FAQ data and verified outputs are distinguishable, the ledger
  can rebuild it, and one bad batch never pollutes the general corpus.
- Alternative: insert directly into `rag_collection` (single query path, simpler).

Robustness (addresses the parked timeout):
- Run indexing in a FastAPI background task AFTER the run completes, so a slow
  SentenceTransformer embed never blocks the UI.
- Use a plain `chromadb.PersistentClient` (not the autogen wrapper) with
  upsert-by-id (`f"{session_id}-{kind}-{chunk_index}"`) so re-indexing never
  duplicates and never hangs on huge payloads.
- On failure: record `{"type": "info", "content": "Experience indexing failed: ..."}`;
  never fail a completed run because of RAG.

### 3. Happy path — reinforcement-learning ledger
`data/reinforcement_learning.md` (git-tracked, append-only):

```markdown
# Reinforcement Learning Ledger
Sessions the user explicitly rated as good. Source of truth for fine-tuning data.

| Session | Date | Task | Deliverables indexed | Feedback |
|---|---|---|---|---|
| sess-20261105113213 | 2026-11-05 | laundry shop app | spec, diagram, 14 Q&A pairs | "clear and complete" |
```

Alongside the ledger, for each happy session write
`data/fine_tune/<session_id>.jsonl`: one JSON line per example of shape
`{"task": ..., "instruction": "Write a functional specification for: <task>",
"output": "<functional_specification.md>", "session": ..., "date": ...}`.
The .md is the human-readable index; the .jsonl is the machine-readable corpus a
fine-tuning script can consume without touching ChromaDB. (Format open question.)

### 4. Unhappy path — feedback folder
`feedback/<session_id>.md`:

```markdown
# Feedback for sess-...
- Date: ...
- Satisfied: no
- What went wrong: <user comment>
- Artifacts at the time: list + sizes
```

Also `feedback/<session_id>.json` for programmatic mining (which sections were
criticised, stage attribution later). Unhappy sessions are NOT indexed into RAG.
A future step (out of scope now) aggregates feedback/ into recurring themes.

### 5. `.env` switches
```bash
FEEDBACK_ENABLED=true          # master switch: ask, index, ledger, feedback files
FEEDBACK_TIMEOUT_S=300         # how long the UI waits for an answer
RAG_APPROVED_COLLECTION=approved_experiences
REINFORCEMENT_LEDGER=data/reinforcement_learning.md
FEEDBACK_DIR=feedback
```
When `FEEDBACK_ENABLED=false`: no question is asked, nothing is indexed, no files
written. `/api/health` reports the switch so the UI knows not to render the widget.

## API / file changes
- `server/api.py`: `feedback` client WS message; `feedback_request` event;
  `POST /api/sessions/{id}/feedback` REST fallback; background task calling
  `index_approved_deliverables` / `write_ledger` / `write_feedback_file`;
  `/api/health` gains `feedback_enabled`.
- `lib/rag_helpers.py`: new deterministic indexing functions (no autogen wrapper).
- `lib/pipeline.py`: attach the approved-experiences memory when
  `FEEDBACK_ENABLED` and the collection exists.
- `app2.py` (Chainlit): end-of-run prompt (optional).
- `.env.example`: the switches above.
- New dirs: `feedback/`, `data/fine_tune/` (gitignore raw feedback? keep tracked —
  decide at approval).
- Tests: happy path indexes; unhappy path writes feedback file and skips index;
  `FEEDBACK_ENABLED=false` writes nothing; re-index is idempotent; ledger line
  format; timeout policy.

## Acceptance criteria
1. Completing a run shows the satisfaction question (UI and Chainlit).
2. "Yes" → chunks visible in the approved collection, ledger row appended,
   fine-tune JSONL written.
3. "No" → comment stored in `feedback/<session_id>.md`, nothing indexed.
4. `FEEDBACK_ENABLED=false` in `.env` disables everything cleanly.
5. A ChromaDB failure never fails a completed run.

## Risks
- Embedding model startup cost on first index (mitigated by background task +
  cached client).
- Same deliverable indexed twice across continuation runs (mitigated by
  upsert-by-id).
- PII: approved specs contain business content; ledger/feedback files stay local,
  like sessions already do.

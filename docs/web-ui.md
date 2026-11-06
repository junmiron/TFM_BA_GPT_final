# Web UI (React + FastAPI)

The Chainlit app is the original front-end. The `ui/` + `server/` pair is a
new front-end for the **same** pipeline: both call `lib/pipeline.py`, so they
cannot drift apart.

```text
lib/pipeline.py     the AutoGen team, stages, termination, MCP wiring
app2.py             Chainlit adapter (UI shell only)
server/api.py       FastAPI adapter (REST + WebSocket)
ui/                 React/Vite/TypeScript/Tailwind client
```

## Run it

```bash
# 1. build the client
cd ui && npm ci && npm run build

# 2. serve (ui/dist is mounted automatically when it exists)
python -m uvicorn server.api:app --port 8000
```

For client development with hot reload, run the Vite dev server separately and
point it at the API. The API allows CORS only from Vite's two default local
origins (`localhost:5173` and `127.0.0.1:5173`); it does not enable credentialed
cross-origin requests:

```bash
cd ui && cp .env.example .env && npm run dev
```

## Test it

```bash
# 1. the client: types, unit tests, production build
cd ui && npm run typecheck && npm test && npm run build

# 2. the backend contract (REST + WebSocket), against a real uvicorn
python -m pytest tests/test_server_api.py -q

# 3. a full run through the same API the UI calls (needs SIMULATE_HUMAN=true)
SIMULATE_HUMAN=true python -m uvicorn server.api:app --port 8000
python e2e/ui_backend_e2e.py          # prints RESULT: PASS/FAIL

# 4. the rendered page in a real browser
#    open http://127.0.0.1:8000 - start an interview, watch the stage rail,
#    Stop mid-run, then check the download links under the transcript
```

`e2e/ui_backend_e2e.py` mirrors the UI exactly (POST a task, follow the event
stream, verify the four deliverables exist and that the PDF has images,
bookmarks and no raw Mermaid text). Point it at any port with `UI_E2E_BASE`.

## API contract

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | lanes, `simulate_human`, whether the UI is built |
| GET | `/api/sessions` | recent sessions from `conversation/` + in-memory runs |
| POST | `/api/sessions` | body `{"task": "..."}`; starts a run, returns `session_id` |
| GET | `/api/sessions/{id}` | status, stage list, transcript, events, error |
| POST | `/api/sessions/{id}/stop` | cancels the AutoGen token and releases a pending `ask_user` wait |
| GET | `/api/sessions/{id}/artifacts` | deliverables with size and download URL |
| GET | `/api/files/{id}/{name}` | download a deliverable (PDF/HTML/MD/PNG) |
| WS | `/ws/sessions/{id}` | live events, replayed on connect; accepts `{"type":"answer","content":…}` and `{"type":"stop"}` |

Event shapes:

```json
{"type":"info","content":"..."}
{"type":"answer","content":"..."}
{"type":"message","source":"interviewer_agent","content":"...","phase":"interview"}
{"type":"chunk","content":"...","file":"functional_specification.md","chars":1234}
{"type":"artifacts","artifacts":[{"name":"functional_specification.pdf","url":"/api/files/..."}]}
{"type":"error","content":"..."}
{"type":"complete","content":"..."}
```

Stages (used by the progress rail):

```text
interview -> summary -> spec -> check -> diagram -> review -> export
```

## Design decisions

**Features from the prototype that were dropped.** The `talk-wiz-chat`
prototype had "load scripts", "lets talk" and "phone call". None of them map to
this pipeline, so they are not implemented. What replaces them:

- a task composer with a 4,000-character limit, instead of a script loader;
- a stage progress rail, so you can see which agent is working;
- an artifact panel with download links, instead of a call CTA.

**Streaming, not polling.** The WebSocket replays the full event log on connect
and then streams live events, so opening a running session mid-way shows the
whole transcript. The client reconnects with exponential backoff (up to 6
attempts, capped at 15 s).

**Answer box.** When a human is in the loop, the interviewer blocks on
`ask_user`, and the server queues answers received on the WebSocket. The UI
shows one answer box under the transcript, opened only when a `QUESTION:` is
unanswered; `Ctrl/Cmd + Enter` sends it and `Esc` stops the run. With
`SIMULATE_HUMAN=true` the stakeholder is simulated on a separate remote lane and
no answer box appears.

**Accessibility.**
- `lang="en"`, a skip-to-transcript link, `aria-live` regions for status and
  transcript, every control labelled, visible focus rings.
- `prefers-reduced-motion` disables animation.
- Colours come from CSS variables tuned for WCAG AA contrast.
- Layout collapses to one column below 1024 px. Session history is bounded and
  keyboard-scrollable so the transcript stays reachable on small screens;
  browser-checked at 390 px.

**No UI library.** Buttons, badges and panels are ~40-line local primitives so
there is no shadcn dependency and no design-system lock-in.

## Testing

```bash
cd ui && npm run typecheck && npm test
python -m pytest tests/test_server_api.py
```

The FastAPI tests use a scripted fake workflow, so they exercise the contract
without spending model tokens.

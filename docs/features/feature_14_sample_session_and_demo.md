# Feature 14 — Committed sample session + Vercel interactive demo

Status: **implemented — Option A approved** (2026-11-08)

## Goal

1. **GitHub**: ship a real, committed sample output (`examples/sample_session/`) so
   nobody has to run the pipeline to see what BA-GPT produces. Source:
   `conversation/sess-20261106143438` (or a fresh recorded run — see §5).
2. **Vercel**: an interactive demo — the real UI with a fixed goal. The viewer
   presses **Start interview** once and watches a scripted session play back in
   realtime: messages, stage status, scrolling transcript, artifact window.
   With a **pause** button, **speed** buttons, **two versions** (with/without
   internal agent messages), and the **final artifacts viewable** (same files
   as the sample session).

## Research findings

### F1. The backend already records the complete, timestamped event log

`server/api.py` → `Session.record()`: every event broadcast to the UI is
appended to `session.events` with an ISO `ts`, and a reconnecting WebSocket
client replays the whole log. The log is the *entire* run:

| event type | payload | what it carries |
|---|---|---|
| `info` | `content` | system status ("Simulated stakeholder active…", "Starting multi-agent workflow…", completeness notes) |
| `message` | `source`, `content` | **every** agent message — internal (planning, summarizer, writer, checker, diagram, reviewer) *and* interviewer/user |
| `chunk` | `source`, `content` | streamed deltas (typing effect) |
| `answer` | `content` | echo of the (simulated) user answer |
| `complete` | `stop_reason`, `artifacts` | run finished |
| `artifacts` | `artifacts[]` | final file list with names/kinds/sizes/URLs |
| `error` / `feedback_request` | … | failures / satisfaction gate |

So a "with internal messages" demo is possible **only from a fresh recording** —
the log is in-memory and `sess-20261106143438` already finished.

### F2. `interview.jsonl` is not enough (confirms the suspicion)

It holds only the interviewer Q&A + simulated-user answers (40 lines for that
session). No internal agents, no status events, no chunks, no artifact events.
It stays in the sample session as the *short interview* file, but it cannot be
the demo's data source.

### F3. The UI is already replay-capable — the only network coupling is one hook

- `ui/src/state/runState.ts` — `reducer`/`applyEvent` are **pure functions** of
  `ServerEvent`. They build turns, stage progress (`stageStates` from which
  agents spoke), artifacts and terminal state. No I/O.
- `ui/src/hooks/useSessionSocket.ts` — the *only* WebSocket coupling. Replace
  it with a replay engine and everything downstream works unchanged.
- `ui/src/components/Transcript.tsx` — already takes a `showInternal` prop and
  filters `INTERNAL_SOURCES` (planner, summarizer, writer, checker, …). The
  "two versions" requirement is a **prop flip on the same component**.
- `ui/src/components/RunPanel.tsx` — stage badges + artifact download list;
  artifact URLs are `/api/files/<id>/<name>` → remapped to static paths.
- `ui/src/lib/roles.ts` / `roleStyles.ts` / `workflow.ts` / `format.ts` /
  `artifacts.ts` / `scroll.ts` — pure, reusable as-is.

### F4. The pipeline can be recorded headlessly

With `SIMULATE_HUMAN=1`, `create_workflow(ask_user, notify, session_id)` +
`run_workflow(workflow, task, sink)` runs with **zero human input**: the
`user` UserProxyAgent is answered by the human simulator on the `HUMAN_MODEL`
lane (same setup as `sess-20261106143438`). A recording sink that appends
`{"ts": …, **event}` to a list reproduces exactly what `Session.record` does.

### F5. Vercel cannot host the live app

Vercel serverless: no long-running Python/AutoGen process, no server WebSockets.
The product UI (`ui/`) assumes a local backend (`VITE_API_URL`, settings,
sessions, health). → The demo must be a **static replay** of the recorded event
stream. This is a strength: deterministic, pausable, speedable, uses the real
UI components, and the artifacts are static files.

## Options considered

| # | option | verdict |
|---|--------|---------|
| A | **Static replay of a recorded full event log** through the real reducer + components | ✅ **Recommended** — real UI, both versions from one recording, trivial pause/speed, Vercel-static |
| B | Reconstruct events from `interview.jsonl` | ❌ internal agent messages would be invented, not real |
| C | Mock backend on Vercel serverless | ❌ AutoGen/Python/WS don't fit serverless |
| D | Pre-rendered video / screen capture | ❌ not interactive, no artifact window, poor on LinkedIn |
| E | Demo mode inside `ui/` (`?demo=1` route) | ⚠️ possible, but drags health/sessions/settings/WS code into the deployed bundle; keeps product and demo coupled. Chosen against |

## Design (Option A)

### 1. `examples/sample_session/` (committed to GitHub)

```
examples/sample_session/
├── README.md                          # what it is, how it was produced, run date, models
├── functional_specification.pdf       # ~1.5 MB (split diagrams, white headers)
├── functional_specification.html      # self-contained (inline SVG)
├── functional_specification.md
├── functional_specification.formatted.md
├── interview.jsonl                    # short Q&A only
├── canvas_diagram.md                  # 4 reviewed mermaid diagrams
├── process_diagram{,_2,_3,_4}.mmd     # mermaid sources
├── process_diagram{,_2,_3,_4}.png
├── process_diagram{,_2,_3,_4}.svg
└── replay/
    ├── events.jsonl                   # full timestamped event log (ALL agents)
    └── meta.json                      # task text, lanes, wall duration, event counts, source session id
```

**Excluded** (test/debug artifacts of the PDF work, per the session dir audit):
`__tfm_body.md`, `__tfm_body.typ`, `_m.*`, `_probe*`, `_s.*`, `_vec*`
(probe files), `*.clean.mmd` (intermediates), `process_diagram_part_*.svg`
(12 fragment cache files, ~4.3 MB), `process_diagram_2_band{1,2}.png`,
`process_diagram_parts.json` (fragment manifest).

Copy is driven by an allow-list in `scripts/export_sample_session.py
<session_dir>`, so any session can be exported the same way.

### 2. `demo/` — standalone Vite app (Vercel root)

```
demo/
├── package.json  vite.config.ts  tsconfig.json  index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx                 # demo layout (Header + hero/transcript + RunPanel)
│   ├── replay.ts               # playback engine (scheduler, pause, speed)
│   ├── demoState.ts            # fetch events.jsonl + meta.json, feed shared reducer
│   ├── components/
│   │   ├── StartHero.tsx       # fixed goal + [Start interview] + version segmented control
│   │   ├── PlaybackBar.tsx     # play/pause · 2x 4x 8x 16x · restart · progress · agents toggle
│   │   └── ArtifactViewer.tsx  # end-of-run: open PDF, open HTML, inline preview
│   └── (reused from ../ui/src: runState.ts, Transcript, RunPanel, roles,
│      roleStyles, workflow, format, artifacts, scroll, ui/ primitives, index.css)
└── public/sample-session/      # copied from examples/sample_session at build time
```

**Reused, not rewritten**: `reducer`/`applyEvent`/`stageStates`, `Transcript`
(incl. `showInternal`), `RunPanel` (stages + artifact list), role styles,
scroll-follow logic, Tailwind theme. Only new code: the playback engine, the
three demo components, artifact URL remapping.

**Playback engine (`replay.ts`)**:
- Input: parsed `events.jsonl` → `[{t0_ms, event}]` from the real `ts` fields.
- Clock: `setInterval` tick (or rAF) advancing a virtual clock; dispatches the
  next event when `virtual_now >= next.t0_ms * (1/speed)`.
- Controls: `play/pause/resume`, `speed ∈ {2,4,8,16}` (default 8), `restart`.
- Realistic typing: `chunk` events are dispatched as recorded, so the reducer's
  existing streaming-turn logic produces the typing effect for free.
- Minimum inter-event gap ~80 ms at 1× so a burst of fast events still reads.
- Artifact remap: `url: /api/files/<id>/<name>` → `./sample-session/<name>`
  (same origin) — RunPanel downloads and header buttons work with plain static
  files, no backend.
- Deterministic + unit-testable: pure `advance(clock, speed, paused, events,
  cursor)` function; vitest covers monotonicity, speed scaling, pause, end.

**Demo chrome** (replaces SessionRail + AnswerBox):
- **Landing**: project title, the fixed goal (the laundry-shop brief, read from
  `meta.json`), **[Start interview]** button, segmented control
  **"Conversation only" | "Full agent team"** (maps to `showInternal`),
  speed preset. Deep links: `?agents=1|0`, `?speed=16`, `?autoplay=1`.
- **Running**: real `Transcript` (auto-scroll, scrollable history), real
  `RunPanel` (7 stage badges light up as each agent speaks; artifact list
  appears at the end), pinned **PlaybackBar** with pause/resume, 2×/4×/8×/16×,
  restart, progress ("Stage 4 of 7 · 3:12 of 8:30 at 8×").
- **Finished**: "Artifacts ready" state — **Open spec (HTML)** (iframe
  preview of the self-contained HTML deliverable), **Download PDF**, full
  artifact list. Same files as `examples/sample_session/`.

### 3. Recording + export scripts

- `scripts/record_demo_replay.py` — headless run
  (`SIMULATE_HUMAN=1`, lanes from `.env`, task = fixed demo goal) with a
  recording sink; writes `<session_dir>/replay_events.jsonl` + `replay_meta.json`
  (task, lanes, duration, per-type event counts). Exit code reflects success;
  prints the final `stop_reason` and artifact list.
- `scripts/export_sample_session.py <session_dir>` — allow-list copy to
  `examples/sample_session/` (deliverables + replay log) and writes
  `README.md` (generated: run date, source session, models, duration).
- CI: no new jobs needed (scripts are opt-in; `demo/` gets a `build` check in
  the existing `web-ui` job or a small `demo` job: `npm ci && npm run build`).

### 4. Vercel deployment

- Vercel project root `demo/` (its own project, not the Python app):
  install `npm ci`, build `npm run prebuild && npm run build` (`prebuild`
  copies `examples/sample_session` → `demo/public/sample-session`), output
  `demo/dist`.
- Free preview per PR + one production URL for the LinkedIn post.

## Implementation plan

| phase | work | verification |
|---|---|---|
| **P1 — Recording** | `record_demo_replay.py`; run one full headless run (Groq lanes, ~1 h wall clock, token cost of one normal run); QA the event log (all 7 stages' READY, `complete` + `artifacts`, sane gaps, internal sources present) | event-log QA script prints stage coverage + event counts; spot-check a `chunk` burst |
| **P2 — Sample session** | `export_sample_session.py`; produce `examples/sample_session/`; commit | `git ls-files examples/` shows only allow-listed files; PDF/HTML open; `interview.jsonl` short |
| **P3 — Demo skeleton** | scaffold `demo/` (vite+react+tailwind, mirror `ui/`); wire `../ui/src` imports; `replay.ts` engine + unit tests; smoke replay with a 10-event fixture | vitest green; `vite build` green; fixture replays through the real reducer in dev |
| **P4 — Demo chrome** | StartHero, PlaybackBar (pause/speed/restart/agents toggle/progress), ArtifactViewer (PDF/HTML preview), deep links, artifact URL remap | full replay at 16× (~4–5 min) watched end-to-end: stages light up, typing visible, pause/resume holds, toggle flips internal messages, downloads work |
| **P5 — Ship** | Vercel deploy (or GitHub import), README + LinkedIn copy, optional screen-capture GIF at 16× | production URL loads, replay runs, artifacts open |

Estimated effort: P1 ~0.5 d (mostly waiting on the run), P2 ~0.25 d,
P3 ~0.5–1 d, P4 ~0.5–1 d, P5 ~0.25 d.

## Open questions (for approval)

1. **Demo goal**: keep the laundry-shop brief (same as `sess-20261106143438`)? — recommended yes.
2. **Sample session source**: the **fresh recorded run** (recommended — its PDF
   is rendered with the current code: split diagrams, white headers) vs the
   existing `sess-20261106143438` files (event log lost → demo would be
   conversation-only, no internal-messages version).
3. **Speeds**: 2×/4×/8×/16×, default 8× (a 69-min run ≈ 8.6 min at 8×, ≈ 4.3 min at 16×)?
4. **Vercel**: new project for `demo/` (recommended) — and do you want me to
   deploy via the Vercel tooling, or hand you the config to deploy yourself?

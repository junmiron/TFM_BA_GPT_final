# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added

- Deliverable guidance: HTML is presented as the read-friendly spec, PDF as the
  signed/printed copy, Markdown as the base for AI coding agents (README,
  sample-session README, demo artifact viewer, demo hero).
- Demo dialog box (`demo/src/components/DialogBox.tsx`): a pinned panel styled like the
  real UI's answer composer that shows the current interviewer question and the simulated
  stakeholder's answer as the replay pairs them, so viewers can follow the dialogue without
  scrolling the transcript.
- Interactive Vercel demo (`demo/`): a static SPA that replays a real recorded
  run through the product's own React components and reducer - fixed goal,
  one-button start, pause/resume, 2x/4x/8x/16x speed, interview-only vs full
  agent-team transcript, artifact viewer with the committed sample deliverables.
  `scripts/record_demo_replay.py` records the replay log from a headless
  simulated run; `scripts/export_sample_session.py` exports clean deliverables
  to `examples/sample_session/`.

- Graph-aware splitting of tall Mermaid process diagrams (`diagram_split.py`):
  each stage subgraph becomes a numbered figure ("Process flow — Stage 3 (part
  4 of 12)"), tall stages are re-cut on topological rank bands, and edges that
  cross parts become paired `Ref X` out/in flag nodes with a connector index
  table. Fragments render as SVG with native (`htmlLabels: false`) labels, so
  Typst keeps every node label as selectable PDF text; fragment renders are
  cached per session via a digest manifest. Diagrams that cannot be split
  (no stage subgraphs) still fall back to quiet-row banding.

### Fixed

- The HTML deliverable's document title is now the project name from the
  Title Page metadata (`WashLoop v1 - Functional Specification Document`)
  instead of the literal heading "Title Page", which appeared in the browser
  tab and PDF metadata. `_extract_title` falls back to the first non-Title-Page
  heading when no Project field exists.
- Table header rows are now always dark-on-white: pandoc tables emitted with
  an integer column count (`columns: 5,`) or with header cells wrapped over
  several lines skipped the styling pass, leaving black header text on the
  dark header fill (solid blocks instead of white text). Both shapes are now
  normalized, with proportional widths computed from content.
- Cover title renders at 25pt with hyphenation off, so "Functional
  Specification Document" fits the page width on one line instead of being
  hyphen-split across two rows.
- PDF deliverable regression: pandoc's parser swallowed everything between two
  standalone `---` rules into one headerless single-column table (mangled
  tables, 114-page renders), and YAML-metadata parsing failures made the Typst
  engine fall back to the plain PyMuPDF renderer (unlinked bullet Contents).
  Standalone section rules are now rewritten as `***` before conversion, the
  YAML-metadata extension is disabled for the spec Markdown, and the Typst
  output is QA'd for linked Contents entries and intact tables.
- Diagram banding now snaps every band cut to the quietest row (whitespace or
  a lone connector line) near the page limit instead of cutting at a fixed
  height through node boxes; bands tile the diagram exactly with no overlap.
  `_markdown_to_typst` resolves the body path to an absolute path so pandoc
  finds it even when the caller passes a relative session path.

## [1.3.0] - 2026-11-06
### Removed



- Technical-debt cleanup: deleted the unreferenced legacy files (`app.py`, `lib/old/`, `src/old/`, `PDF_format_mcp_server_v0/v1.py`, `Mermaid-MCP_old.py`, `chainlit_en-US.md`, unused `public/` logos) and the archived `docs/Conversation/` example sessions.

- Dead functions with no callers: `default_summary_path`, `save_conversation_pair`, `_prev_agent_question`, `_diagram_block_from_source`, `_header_line_cells`; plus unused imports across `lib/` and the MCP servers.

- Unused Mermaid MCP tools (`render_mermaid_svg`, `render_mermaid_pdf`, `render_mermaid_all`, `png_to_jpg`) - the pipeline only uses `clean_mermaid`, `check_mermaid`, `render_mermaid_png`.

- Redundant `onnxruntime` pin in requirements (provided transitively by chromadb).

- Legacy dev notebooks and duplicates under `test/`; the four manual e2e harnesses moved to `e2e/`.
- Pre-project research archives `docs/TFM/`, `docs/Mermaid/` and `docs/Examples FDS/`, and the
  169 MB local `mcp_servers/PyMCP-FS/` vendored server (its file tools were replaced by
  project-scoped helpers in `lib/agents_tools_helpers.py`).



### Added
- Interview answer box is always visible: active when a question is pending,
  greyed and disabled otherwise (Feature 5).
- Header action row centered above the transcript: "Download Functional Spec
  PDF" (targets the PDF, greyed out until it exists) and "View web version"
  opening `functional_specification.html` inline in a new tab (Features 6-7).
- New `/api/view/{session}/{name}` inline-serving endpoint (html/md/svg/png;
  PDFs stay download-only).
- Removed the dead `save_experience_chroma`/`recall_experience_chroma` MCP tools and
  their `sentence_transformers` embedding code from the deliverable server; finalize
  no longer indexes every session (only user-approved runs reach the RAG now,
  via `lib/experience_indexer.py`).
- Configuration page (gear icon): model lanes, model IDs/base-URL overrides,
  API keys (masked, never echoed), AI-human simulation toggle, UI visibility
  flags and run limits, saved through a whitelisted `/api/config` GET/PUT that
  rewrites only whitelisted lines of `.env` (Feature 8).

- **Reinforcement learning from approved sessions** (`lib/experience_indexer.py`):
  after a run completes the user is asked whether they are happy with the
  deliverables. "Yes" indexes them into a dedicated `approved_experiences`
  ChromaDB collection (queried by the interview/writer agents alongside the
  web RAG), appends the session to `experiences/reinforcement_learning.md`
  and writes a task -> spec JSONL example under `experiences/fine_tune/`.
  "No" captures the critique in `feedback/<session_id>.md`; silence indexes
  nothing. Controlled by `FEEDBACK_ENABLED` / `FEEDBACK_TIMEOUT_S`.
- **UI visibility switches**: `UI_SHOW_ARTIFACTS` hides the Artifacts panel;
  `UI_SHOW_INTERNAL_MESSAGES=false` shows only the interviewer/user
  conversation (the full event log stays in the backend for audit).
- **Session continuation**: select an existing session and add information -
  `POST /api/sessions/{id}/continue` merges the supplement into the spec
  (heading-preserving guard with an Addendum fallback), bumps the version
  and re-renders PDF/HTML/MD in place. Supplements are audited in
  `supplements.jsonl`.
- **Meeting transcript to spec**: attach a `.txt/.md/.docx/.pdf/.vtt/.srt`
  transcript when creating a session (`lib/transcript_loader.py`). The
  transcript is saved as `source_transcript.txt` and seeds the run so the
  interview only fills gaps.


### Fixed
- Session continuation returned HTTP 500: the merge call used a non-existent
  AutoGen method (`create_completion`); it now uses `create()` and falls back to
  a deterministic Addendum merge when the model lane is unreachable.
- Process diagrams taller than one page were clipped in the PDF; the Typst
  renderer now splits them into full-width page-sized bands ("part k of N").
- The satisfaction/feedback request was easy to miss: it now appears in the
  pinned composer box and forces the transcript to scroll to it.

### Changed
- Header web link now reads "Open Functional Spec in browser".
- SECURITY.md now documents the local API surface (localhost binding, CORS
  allowlist, key-presence-only config endpoints, 10 MB upload cap) instead of
  claiming there is no server.
- `.gitignore` lost stale entries for the removed `frontend/` app and docs
  archives.

## [1.2.0] - 2026-11-05

Dependency upgrade anchored on AutoGen 0.7.5 (the final release of the archived
microsoft/autogen project). Every other package is pinned to the newest version
that is provably compatible with it. The full matrix and the reasoning behind
each pin are in `docs/dependency-versions.md`.

### Changed
- **AutoGen 0.7.4 -> 0.7.5** (`autogen-agentchat`, `autogen-core`,
  `autogen-ext[openai,chromadb,mcp,ollama]`). No code changes were needed: the
  0.7.5 API surface is identical, and all three model lanes
  (`strata`, `opencode`, `groq`) were re-probed live after the bump.
- **Every dependency is now pinned exactly** instead of using open ranges:
  chainlit 2.12.0, fastmcp 3.4.11, mcp 1.30.0, chromadb 1.5.9,
  sentence-transformers 6.2.0, lxml 6.1.3, lxml_html_clean 0.4.2,
  readability-lxml 0.9, PyMuPDF 2.1, markdown 3.11.2, python-dotenv 1.2.4,
  PyYAML 6.0.3, pillow 13.0.0, beautifulsoup4 4.15.0, pytest 9.2.0.
  `requirements.txt` now installs a reproducible set on both CI Python 3.11
  and 3.13.
- **fastmcp stays on the 3.x line on purpose**: 4.1.6 requires `mcp>=2.3`, and
  chainlit 2.12 caps `mcp<2.0.0`. 3.4.11 is the newest that satisfies both.
- **`@mermaid-js/mermaid-cli` pinned to 12.2.0** in CI (was unpinned), and the
  local install was upgraded from 12.0.0. Diagram rendering tests pass on the
  new version.
- CI actions bumped: `actions/checkout` v4 -> v7.0.1, `actions/setup-python` v5 -> v7.1.0,
  both commit-pinned; `actions/setup-node` is also commit-pinned for the UI job. A
  `python -m pip check` step runs before the Python test suite.

### Removed
- **langchain and langchain-community are gone.** They were only used for one
  text splitter and four document loaders; `langchain-community` is sunset and
  emits a `DeprecationWarning` on import, and langchain 1.x dropped
  `langchain.text_splitter` entirely. `lib/rag_helpers.py` now carries a
  ~40-line recursive splitter plus PyMuPDF/httpx/stdlib OOXML readers, so the
  RAG corpus is indexed with libraries the project already depends on.
- The `lxml.html.clean.Cleaner` import (deprecated shim) is replaced by
  `lxml_html_clean.Cleaner`.

### Added
- `docs/dependency-versions.md` - the upgrade analysis: why each package moved,
  which versions are blocked by which constraint, and the verification gates.
- `tests/test_rag_splitter.py` - guards that `langchain` is never imported again
  and that the replacement splitter respects chunk size, overlap and content.

### Added - web UI
- **`ui/` - React + Vite + TypeScript + Tailwind client.** Three columns: session rail
  (create/switch runs), live transcript with role-coloured turns and streaming chunks,
  and a run panel showing the seven pipeline stages plus the artifact download list.
  The answer box only appears when the interviewer is waiting for a human reply.
  `Ctrl/Cmd + Enter` sends, `Escape` stops the run, focus rings are visible, the
  transcript is `aria-live`, and `prefers-reduced-motion` disables the animations.
  The API base comes from `VITE_API_URL` (default `http://127.0.0.1:8000`) - no
  hardcoded host. `load scripts`, `lets talk` and `phone call` from the Lovable
  prototype are not implemented.
- **Frontend toolchain upgraded** to React 19.3.1, Vite 8.3.5, Vitest 5.0.5,
  TypeScript 7.0.2 and Tailwind 4.3.3; the locked install reports zero npm
  vulnerabilities. CI now runs the frontend typecheck, tests and production build.
- **`lib/pipeline.py`** - the AutoGen team, stage table and termination sequence moved
  out of `app2.py`. Chainlit and FastAPI are now thin adapters over the same workflow,
  so both front-ends produce identical artifacts.
- **`server/api.py`** - FastAPI sessions API (`/api/health`, `/api/sessions`,
  `/api/sessions/{id}`, `/api/sessions/{id}/stop`, `/api/files/{id}/{name}`) plus a
  `/ws/sessions/{id}` WebSocket that replays history on connect and streams events.
  Completed sessions are finalized before artifacts are listed.
- `tests/test_server_api.py` (FastAPI contract, scripted fake workflow - no API key)
  and `ui/src/**/*.test.ts` (vitest: question extraction, stage derivation, artifact
  ordering, reducer transitions).
- FastAPI 0.162.0 and Uvicorn 0.54.0 are pinned as the React UI server stack.
- `docs/web-ui.md` - architecture, run commands, API contract and UI design rationale.
- `test/ui_backend_e2e.py` - full-stack harness that drives a real uvicorn with a real
  simulated-stakeholder interview, asserts all seven stages finish, the deliverables land
  in the folder the API tracks, the PDF has images/bookmarks and no raw Mermaid, and the
  interview has at least three rounds with no verbatim repeated answers.
- **Turn budget is visible.** `/api/health` reports `max_messages`, and the run panel
  shows "12 of 300 turns used", so a long interview is never an unbounded scroll.
- Session rail and run panel are sticky on desktop, and the answer box scrolls into
  view the moment the interviewer asks a question (honouring `prefers-reduced-motion`).

### Fixed
- `tests/test_rag_splitter.py` imported `rag_helpers` without putting `lib/` on
  `sys.path`; it only worked when another test module had already inserted it, so
  running the file alone failed with `ModuleNotFoundError`.
- `run_mmdc` in the Mermaid MCP server had no subprocess timeout. A puppeteer render
  that hung would hold the MCP session open until the client's read timeout killed
  it; each render is now capped at 180s and raises a readable error.
- Local Vite development now passes API preflight requests only from the two
  default localhost origins; credentials and other origins remain disallowed.
- The web UI Stop action now cancels the workflow, wakes an `ask_user` blocked on
  the answer queue, and retains `stopped` after the run exits; real-uvicorn tests
  cover answer delivery, stop while waiting, and stop during team construction.
- `StopButton` took focus when it mounted, yanking the caret out of the answer
  composer every time a run started. `Escape` is handled globally in `App.tsx`, so
  the button no longer needs focus; the composer keeps the caret.
- `docs/web-ui.md` documented a `/api/sessions/{id}/events` route that the backend
  never implements (the session detail endpoint already returns the event log).
- `docs/dependency-versions.md` claimed torch was bounded at `<2.9`; the actual pin
  is `>=2.2,<3`. README now says Python 3.11 or 3.13, matching the CI matrix.
- **A single unparsable diagram used to delete every diagram after it.** The
  embedded PNG list walked `process_diagram.png`, `_2.png`, `_3.png` ... and
  stopped at the first gap, so an eleven-diagram canvas whose fifth render failed
  ended up with four images in the PDF and HTML. `_diagram_png_names` now returns
  one positional slot per canvas diagram (`None` where the render failed), which
  also stops the sixth PNG being attached to the fifth diagram.
- Mermaid reads `;` as a statement separator, so a semicolon inside a sequence
  message ("Open bag record; same actions allowed...") makes mmdc exit 1 with a
  parse error and the diagram silently disappears. `_render_one_mmdc` now retries
  once with message-line semicolons rewritten as commas, and the Mermaid MCP
  `check_mermaid`/`clean_mermaid` tools report and fix the same pattern. Verified
  end to end: the session that lost diagram 5 now renders all eleven
  (`pdf images 11`, `html imgs 11`, `md images 11`).
- **The "You" role tag was invisible.** It used `bg-white/20` with
  `text-primary-foreground`; white composited on the white card is white on white,
  a measured WCAG ratio of 1.00. The tag now uses the primary fill with
  primary-foreground text (5.78:1), and `ui/src/components/roleStyles.test.ts`
  rejects translucent white tag backgrounds so the mistake cannot return.
- `ui/src/index.css` mapped `--color-input` to `hsl(var(--input))` while `--input`
  was never declared in `:root`, so inputs fell back to an accidental border
  colour. `--input: 220 13% 85%` is now defined next to `--border`.
- **A completed run showed zero downloads in the web UI.** `run_workflow`
  invents its own `sess-<timestamp>` when the workflow has no id, so the
  interview, the spec, the diagram and the PDF landed in
  `conversation/sess-20261105051544/` while the API tracked
  `sess-20261105051520` and reported `artifacts: []`. `_start_run` now pins
  `workflow["session_id"]` to the id the UI is tracking, and a contract test
  asserts the deliverables land in exactly that folder.
- **Two whole sections were missing from the deliverable.** The spec writer
  sometimes glues a heading onto the end of the previous paragraph with no
  newline - `...basic reporting.## 4. Functional Requirements` - so Markdown never
  sees a heading: sections 4 and 8 vanished from the outline, the TOC and the
  HTML, and their subsections were re-parented under the wrong section
  (`### 4.1` became `### 3.1`). `split_glued_headings` now breaks those headings
  out, and `finalize_deliverables` applies it to `functional_specification.md`
  itself so all three deliverables agree. Re-finalizing the affected run gave
  `## 1-5, 7-9` plus `## Process Diagram`, PDF outline 10 entries, HTML 10 `<h2>`.
- MuPDF could loop forever or silently drop content when a table row was taller
  than one page. PDF export now splits long rows into paginatable pieces and
  bounds the Story writer; pathological layouts fail fast instead of hanging.
  Long-row regression tests confirm the cell text survives in the PDF.
- The Markdown/HTML embedder still compacted the PNG list:
  `lib/agents_tools_helpers._diagram_png_names` returned only the files that
  exist, so when the second of three canvas diagrams failed to render,
  `process_diagram_3.png` landed under "Bag lifecycle" and "Shelf moves" lost
  its image. It now returns one slot per canvas diagram, `None` where the render
  failed, matching the positional list the PDF path already used.
- A missing template section could be routed back to the interviewer, which
  repeated questions the document already answered. Checker gaps for all required
  sections now return to the writer, the retry loop is capped, and finalization
  reports any still-missing template headings.
- `faulthandler` caught the old finalize stall inside the import chain of
  `sentence_transformers` -> `transformers` -> `importlib.metadata.packages_distributions`,
  not inside MuPDF: the PDF MCP server is exec'd as a plain library by
  `finalize_deliverables`, so its top-level `sentence_transformers` import cost
  ~40s on every export. It is now lazy, and `autogen_ext.memory.chromadb` moved
  into the two tools that actually use it. Cold load of the module: 1.14 s with
  `torch`, `transformers`, `sentence_transformers` and `chromadb` all absent. A
  test asserts none of them is imported at module scope.
- The template gate is now enforced at export rather than only reported. The
  checker gets `MAX_CHECKER_ROUNDS` (3, configurable) writer passes on a missing
  section; past that the loop closes and `ensure_template_sections` writes the
  section from material already in the document (requirement titles, the status
  lifecycle, explicit `**Term**: definition` lines and two-column tables) - never
  from a model guessing. A section the interview gave no material for is still
  written, but with an explicit "fill this in before sign-off" marker, so every
  PDF/HTML/Markdown deliverable structurally contains all nine template sections
  and the hole is visible. `finalize_deliverables` reports
  `auto_filled_sections` and `placeholder_sections`, and the API posts both to
  the session transcript.
- **The simulated stakeholder answered the planner instead of the interviewer.** AutoGen
  passes the *last* message to `input_func`, and every `QUESTION:` from `interviewer_agent`
  is routed through `planning_agent` before the user replies, so the persona kept receiving
  `Task state: ...` and answered "I don't see the analyst's question".
  `selector_with_question` now stashes the real question and `workflow_user_input` feeds that
  to the persona, consuming the capture once per answer. The wrapper must be `async`:
  AutoGen decides sync-vs-async with `inspect.iscoroutinefunction` when the team is built, and
  a sync wrapper that returns a coroutine aborts the run with
  `Selector function returned an invalid speaker name`.
- `/api/sessions` could time out while synchronous model setup started in the
  background; clients retrying the POST then created duplicate runs. Session runs
  now start as Starlette background tasks after the response is flushed, with a
  real-uvicorn regression test for the slow-start path.
- **The simulated stakeholder answered questions from previous rounds.** `latest_question`
  scanned the whole transcript, and in rounds where the interviewer emitted only its
  subject-status table there was no `QUESTION:` in the current round, so the persona
  re-answered an old question verbatim. `current_round()` now bounds the search to turns
  after the stakeholder's last answer, `question_from_planner()` recovers the question from
  the planner's assignment text, `question_from_coverage()` derives the next question from
  the interviewer's coverage table, and `question_for_user()` never feeds a status line to
  the persona. `tests/test_interview_routing.py` (24 cases) covers every path.
- **A finished run still showed an empty Artifacts panel and a greyed Download button.**
  The UI's WebSocket whitelist silently dropped the server's `artifacts` event, and the
  reducer's `complete` case reset the list to `[]` even when a partial list had already
  been fetched. The `complete` event now carries an artifact snapshot, `artifacts` is
  accepted over the socket and installs the final list after finalization, and `App.tsx`
  refetches once if a terminal run ends with an empty panel. Verified live: 18 artifacts
  listed, Download enabled, `/api/files/...` serves the 437 KB PDF.
- **The interviewer's tool calls invented a session folder** (e.g.
  `sess-20260624080000` - a date that never existed), because the prompt told the model to
  generate a session id when none was provided. `create_workflow` now receives the run's
  id from the API and substitutes it into the tool spec; the transcript and the
  `interview.jsonl` `_meta` header record the folder that actually exists.
- **The turn counter stayed at zero while a run was in progress.** `record()` increments
  `session.messages` on `message` and `answer` events, so the run panel's
  "12 of 300 turns used" reflects live progress instead of staying at 0.

### Added - deliverable rendering (Typst PDF, redesigned HTML)
- **Vector diagrams in the HTML deliverable.** Mermaid now also
  renders `process_diagram.svg` (best-effort alongside the PNG), and
  `functional_specification.html` inlines that SVG instead of a raster data URI:
  labels stay crisp at any zoom or print. Each inlined figure gets a unique id
  (mmdc scopes its CSS to `my-svg`), and stale SVGs are cleaned up when the
  canvas shrinks. The PDF still embeds the PNG unchanged.
  `tests/test_finalize_deliverables.py` covers SVG generation, inline embedding
  and the PNG fallback.
- **`mcp_servers/Final_deliverable_MCP_server/typst_render.py`** - a Typst +
  pandoc PDF renderer for `functional_specification.pdf`: cover page with the
  Title Page metadata, a Contents page with clickable links and dotted leaders,
  a running header/footer with "Page N of M", table headers that repeat across
  page breaks, packed page flow, and the bundled Inter font. Pandoc converts
  Markdown to Typst; a post-processing pass chunks tables taller than one page
  at row boundaries (pandoc wraps tables in atomic `#figure`s that clip) and
  sizes columns from real cell content - each column gets at least its longest
  word's width, the rest is distributed by content weight - so short columns
  like `Priority` stay compact and `Status`/`Source` wrap at word boundaries
  instead of hyphen-splitting (hyphenation is switched off inside table cells).
  Raw Mermaid fences are stripped from the PDF body; the rendered PNG
  stays. PyMuPDF reads the finished PDF back for QA (pages, bookmarks, embedded
  fonts, no raw Mermaid). On a full session spec the deliverable went from 26
  plain MuPDF pages to a 29-page typeset document with cover, linked contents
  and 61 bookmarks.
- **`scripts/install_render_tools.py`** - fetches pinned portable typst 0.15.1
  and pandoc 3.13 into the gitignored `vendor/bin` (Windows and Linux); CI runs
  it before the test suites. `export_pdf`/`format_and_export` now default to
  `engine="typst"`, fall back to the pure-Python PyMuPDF renderer when the
  binaries are missing, and still accept `engine="xelatex"` or `"pymupdf"`.
- **Inter 4.1 fonts** (SIL OFL 1.1) bundled in
  `mcp_servers/Final_deliverable_MCP_server/fonts/` so the PDF is identical on
  Windows and CI.
- **Redesigned HTML deliverable** in `build_html_deliverable`: sticky Contents
  sidebar with scroll-spy highlighting, a cover header carrying the document
  metadata (version, date, status badge, prepared by), tables with dark sticky
  header rows and zebra striping, print CSS, and responsive collapse under 900px.
  Mermaid source stays collapsed in `<details>` for the web version.
- `tests/test_typst_render.py` - metadata extraction, Mermaid stripping,
  proportional column widths, full Typst render (cover, Contents, footer,
  bookmarks, Inter font, no leftover intermediate files), the PyMuPDF fallback
  when the toolchain is absent, and the HTML sidebar/cover/`<details>` contract.

### Fixed
- **The web UI model lane mislabeled the human.** `/api/health` reported
  `HUMAN_MODEL` (default `opencode`) as the "human" lane even when
  `SIMULATE_HUMAN` was off and the answers came from the browser. The backend
  now reports `user`, and the header reads `you (human)`; the model name still
  appears when the stakeholder really is simulated.
- **The answer composer scrolled out of view on long transcripts.** The chat
  column is capped to the viewport height at `lg`, the transcript scrolls inside
  its own pane, and the answer box is pinned at the bottom (`sticky bottom-0`).
  New turns auto-scroll the transcript only when the reader is already near the
  bottom (`shouldFollowLatest` in `ui/src/lib/scroll.ts`), so scrolling up to
  read history is never hijacked.
- **"Start interview" was clipped in the 18rem rail.** The kbd hint and the
  button did not fit in the 262px row, so the flex row compressed the button and
  its text wrapped inside the fixed 32px height. The button is now full-width on
  its own row with the shortcut as a caption below.
- **Artifacts panel sat below Workflow in the right rail.** RunPanel now
  renders Artifacts first, Workflow second.

## [1.1.0] - 2026-11-04

Makes the pipeline deterministic end-to-end on Windows and moves the model load off a single
provider: the agent team runs on the local GPU lane, the simulated stakeholder runs on a
remote lane, and the deliverables (Markdown with the diagram, a PDF with a real outline, and a
self-contained HTML) are produced without pandoc or LaTeX.

### Added
- **HTML deliverable.** `functional_specification.html` is written next to the PDF by
  `finalize_deliverables()`, and `export_html()` is exposed as an MCP tool. The document is
  self-contained: the diagram PNG is embedded as a data URI, headings get anchor ids, and a
  linked Contents block is generated from them. It ships with print CSS, and the tall flowchart
  sits in a scrollable figure so the page does not stretch to 3700 px.
- **The Mermaid diagram now lives in the Markdown deliverable.** `embed_diagram()` inserts the
  rendered PNG plus the ```mermaid fence into `functional_specification.md`, which GitHub and
  most Markdown viewers render natively. It is idempotent and keeps any prose already in the
  "Process Diagram" section. The PDF keeps only the rendered PNG - the raw source is stripped
  before the PyMuPDF Story render, since it would otherwise appear as a wall of monospaced text.
- **Split model lanes.** Agents use `MODEL_CLIENT`/`MODEL_CLIENT_TOOLS`; the simulated stakeholder
  uses `HUMAN_MODEL`. New profiles: `src/model_config_strata.yaml` (local Strata / LM
  Studio-compatible OpenAI endpoint, `max_tokens: 16000`) and `src/model_config_opencode.yaml`
  (remote `opencode-go`, `max_tokens: 2000`, `include_name_in_message: false`,
  `x-opencode-session` header). `src/model_config_groq.yaml` is tracked as well (placeholder key
  only). This removes the Groq free-tier ceiling of 8000 tokens/min, which throttled the whole
  run.
- `lib/human_simulator.py`: `HumanSimulator` / `build_human_simulator()` drives a simulated
  stakeholder interview, enabled in the live app with `SIMULATE_HUMAN=true` and
  `HUMAN_MODEL=<profile>`. The persona is grounded with the task you entered via `set_brief()`.
- `src/rate_limit_retry.py`: `RateLimitRetryClient` wraps remote clients, parses `Retry-After`
  and Groq's "try again in N seconds", and backs off exponentially up to 60 s across 5 attempts.
- `src/tool_call_recovery.py`: recovers tool calls from local models that emit the text form
  `<function=name>...</function>` instead of a structured function call.
- **Real PDF outline.** `_pymupdf_export()` collects heading positions from the final render pass
  and calls `doc.set_toc(outline)`, so the deliverable has navigable bookmarks rather than only a
  rendered "Contents" block. The export result returns `toc_entries`.
- Canvas writes are mirrored to disk by `mirror_canvas_to_disk(update_file_tool)`, so the Mermaid
  MCP server can read the diagram the diagram agent built in memory.
- `test/e2e_real_pipeline.py`, `test/roleplay_e2e.py`, `test/test_terminate_pipeline.py`:
  real-pipeline, split-lane roleplay and termination checks that honour the `.env` profile.
- New test modules: `test_pdf_export.py`, `test_finalize_deliverables.py`,
  `test_human_simulator.py`, `test_model_loader.py`, `test_rate_limit_retry.py`,
  `test_session_module_identity.py`, `test_path_and_dedup.py`, `test_tool_call_recovery.py`,
  `test_no_deprecated_imports.py`, `test_quiet_deprecations.py`, plus additions to
  `test_mcp_servers.py`. The offline suite now runs 93 tests.
- `markdown` added to `requirements.txt` for the pure-Python Markdown-to-HTML step in the PDF
  export.

- `append_md_file_tool` in `lib/agents_tools_helpers.py`: appends a Markdown chunk to the spec file, used by the writer's chunked save flow.

- **User answers in `app2.py` are no longer rejected as empty.** Chainlit's `AskUserMessage.send()` returns a StepDict whose text lives under `"output"`, but the user-proxy input loop only read `"content"` (a key that does not exist), so every valid answer was treated as empty, re-asked forever and the workflow appeared to hang right after the interviewer's first question. `app2.py` now reads `"content"`/`"output"`/`"text"` like `app.py` already did; typing into the main chat bar while a run is in progress also gets an explicit hint instead of being silently dropped.
- **Memory-backed agents no longer crash on LM Studio / llama.cpp backends.** autogen's `ChromaDBVectorMemory` and `TextCanvasMemory` inject retrieved context as a SystemMessage appended at the *end* of the model context; llama.cpp rejects such requests (`Jinja Exception: System message must be at the beginning`), which killed the interviewer's turn right after the planner's assignment with no visible question. `lib/rag_helpers.py` now provides `TemplateSafeChromaDBVectorMemory` and `TemplateSafeTextCanvasMemory`, which inject the same content as a UserMessage; both apps use them for all memory-backed agents.
- **Interviewer agent no longer kills the workflow when the ChromaDB RAG store is unopenable.** A `chromadb_storage/` created by a different chromadb version only fails on first query (the client opens lazily), which crashed the interviewer's first turn and stopped the run right after the planner's assignment with no visible question. `app.py`/`app2.py` now validate the store at startup with one warm-up query and continue without RAG memory if it is unopenable (a warning is printed to the console). To restore RAG, delete `chromadb_storage/` and `index_state.json` so the store is rebuilt with the installed chromadb version.
- Corrected the embedding model name in `docs/troubleshooting.md` (`paraphrase-multilingual-mpnet-base-v2`, not `all-MiniLM-L6-v2`).
- **Final deliverables are presented in the chat when a run completes.** After "Workflow complete", `app2.py` now renders the full functional specification inline and attaches `process_diagram.png` (inline), `functional_specification.pdf` and a downloadable copy of the `.md`. If `terminate_agent` skipped its file steps, it falls back to `conversation/functional_specification.md` and renders the diagram on the fly from `process_diagram.mmd` via `mmdc` (fences stripped; resolved with `shutil.which`, since bare `mmdc` is not found by Python subprocess on Windows).

### Fixed
- **Only the first diagram in the Mermaid canvas reached the PDF.** The reviewer keeps the
  canvas as a Markdown document (a heading plus a ```mermaid fence per diagram). Embedding that
  whole document in a single fence nested the inner fences, so the first diagram rendered as a
  PNG and every diagram below it printed as raw Mermaid source. `canvas_diagrams()` now splits
  the canvas into one entry per fence, `render_diagram_pngs()` renders each with its own `mmdc`
  invocation (`process_diagram.png`, `process_diagram_2.png`, ...), and `embed_diagram()` writes
  one image-plus-source block per diagram. Canvas headings that only existed because the canvas
  was pasted into the spec are dropped; genuine prose in the section is kept.
- **PyMuPDF Story silently dropped the last diagram.** Story skips an `<img>` that cannot fit in
  the space left on the page. Diagrams were capped at exactly the page content height, so in a
  ten-diagram spec the tenth image never made it into the PDF. `_img_tag()` now caps diagrams at
  `_CONTENT_H - 60` to leave room for the heading above them.
- **Mermaid fences were stripped with a naive toggle.** A line carrying a language opens a fence
  and only a bare ``` closes one; treating inner ```mermaid lines as closers mis-paired the fences
  and let diagram source leak into the PDF as prose.
 `finalize_deliverables()`
  accepted any existing PDF that embedded an image, so a run that rewrote the spec reported PASS
  against a PDF five hours old. The gate now requires an image *and* a real outline, and treats a
  PDF whose mtime is not newer than the spec as stale. Equality counts as stale, because Windows
  clock resolution can put both writes in the same tick.
- **Headings and paragraphs after a Markdown table were swallowed into table cells.** The
  `tables` extension keeps consuming non-blank lines after a table row, which turned
  `## 4. Non-Functional Requirements` into `<td>## 4. Non-Functional Requirements</td>` and folded
  `FR-31`-`FR-36` into one mapping-table cell. `ensure_blank_line_before_headings()` inserts the
  required blank lines and skips fenced code blocks.
- **Duplicated subsection numbers.** Subsections inside a section could restart at the same
  number (for example `8.4` where `8.14` belongs). `normalize_heading_numbering()` renumbers only
  duplicates, so legitimate gaps such as `4.1`, `4.3` and body cross-references like "see Section
  4.2" are preserved.
- **PDF export hung on tall diagrams.** A Mermaid PNG taller than the page content box made
  PyMuPDF Story run unbounded; `_img_tag()` now measures the image and scales it to the content
  box. TOC page-number stabilisation is bounded to 4 layout-only passes (the previous unbounded
  `fitz.Story.write_stabilized()` hung), and the TOC is emitted inside `<body>` rather than before
  `<!DOCTYPE html>`.
- **`mmdc` on mermaid-cli 11/12.** `-w`/`-H` were removed upstream, so the MCP server now passes
  `--size` and retries without any size flag if the CLI rejects it.
- **The Mermaid MCP subprocess could hang** waiting on inherited stdin (`stdin=subprocess.DEVNULL`).
- **`UnknownDiagramError` on multi-diagram documents.** `mmdc` renders one diagram per invocation,
  so `_strip_mermaid_fences()` now extracts the first real fenced diagram. `read_mermaid_source()`
  falls back to actual `.mmd` files, and the `.md` fallback is restricted to diagram/mermaid-named
  files so it cannot accidentally read a functional specification containing fenced blocks.
- **Mermaid reviewer `FileNotFoundError`** (8 occurrences in one roleplay run) caused by canvas
  diagram text living only in memory; resolved by the disk mirror plus the source fallback.
- **Diagram rendering silently failed in CI.** `render_diagram_png()` called `mmdc` without
  the bundled `puppeteer-ci.json`, so Chrome's sandbox could not start on GitHub runners
  (Ubuntu 24.04+ blocks unprivileged user namespaces via AppArmor) and the PNG test skipped
  even though `mmdc` was installed. The helper now applies the same CI detection as the
  Mermaid MCP server, and a test asserts the `-p` flag is present in CI and absent locally.
- **Duplicate module import in `app2.py`.** `from lib import agents_tools_helpers` alongside
  `from agents_tools_helpers import ...` created two distinct module objects with separate
  `_ACTIVE_SESSION` globals, so artifacts landed flat in `conversation/` instead of the session
  directory.
- **Nested session directories** (`conversation/sess-X/sess-X/`): the path resolver now preserves
  paths that are already session-scoped.
- **Groq profile.** `compound-beta` was retired by Groq on 2026-09-21, so the profile uses
  `openai/gpt-oss-120b`. The loader preferred a stale YAML key over the valid `.env` key, because
  it tested `"api_key" in provider` where `provider` was the provider class-name string;
  `resolve_api_key()` now prefers the environment key. `.env` is loaded at import so callers read
  `MODEL_CLIENT` before constructing a client. `max_tokens` is 4000 for the 8000 tokens/min tier.
  Groq bills actual tokens, not the requested `max_tokens`, so lowering it is not a substitute for
  splitting lanes.
- **Empty FR/BR mapping tables.** Requirement parsing handles Groq-style `### 4.1 ...` subsection
  bullet lists plus a plain-bullet fallback, and the scope-heading regex matches "Purpose and
  Scope" as well as "In-Scope".

- **The functional specification is now saved in chunks instead of one giant tool call.** `functional_spec_writer_agent` was instructed to pass the ENTIRE document (~10k words) as a single `write_md_file_tool` argument; on local models that degrades into a malformed text-form "tool call" that never executes, so no file appeared on disk while the agent still sent READY. The writer now saves sections 1-3 with `write_md_file_tool`, appends the remaining section groups with a new `append_md_file_tool` (each chunk < ~4000 words), always uses the tool's default path (`conversation/functional_specification.md`) instead of inventing one, and must verify all 9 sections on disk with `read_md_file_tool` before sending READY.
- **The spec checker no longer passes a missing file.** When `read_md_file_tool` reports the document is missing or empty (the writer's save failed), `functional_spec_checker_agent` now explicitly returns NEEDS_INFO listing "the entire document" instead of judging from conversation memory, so the planner routes back to the writer for a real re-save.
- **`terminate_agent` can actually read the interview log.** Step 1 ("extract session_id from interview.jsonl") was impossible: the agent had no file-read tool and fell back to `sess-unknown`. It now has `read_md_file_tool` and the prompt tells it exactly how to call it.
- **Infinite empty-message loops are stopped with a clear error.** After an unrecoverable malformed tool call, some models emit empty messages forever while the selector keeps re-selecting the same agent (previously only `MAX_MESSAGES=300` could end this). `app2.py` now cancels the run after 3 consecutive empty messages from one agent and explains what happened in the chat.
- **LM Studio mid-run failures are explained in the UI.** A model being unloaded (`400 Bad Request - Model unloaded by user or API request`) or a speculative-decoding engine crash previously only showed up as a console traceback; `app2.py` now catches these and posts an actionable hint (reload the model / restart the LM Studio server).

### Changed
- **Session lookup no longer picks a stale run.** `_find_latest_session_dir()` chose the
  newest `functional_specification.md` under `conversation/` regardless of which run it
  belonged to, so a fixture folder left behind by `test/test_terminate_pipeline.py`
  (`sess-term-test`, a 426-char stub) could be reported as the current run's output. The
  active session set by `start_workflow` is now checked first; the mtime scan is a
  fallback only.
- **Deliverables are named after what they are.** The PDF and HTML are now
  `functional_specification.pdf` and `functional_specification.html` instead of
  `deliverable.pdf` / `deliverable.html`, so every output of one run shares the
  same stem: `.md`, `.formatted.md`, `.pdf`, `.html`.
  `migrate_legacy_deliverable_names()` renames the old files in a session folder
  on the next run, and only when the new name does not already exist.
- **One standard for model configuration.** No profile YAML holds a secret: every
  `api_key` line was removed from `src/model_config_*.yaml`, and `src/model_loader.py`
  injects the key from the environment (`OPENAI_API_KEY`, `GROQ_API_KEY`,
  `OPENCODE_GO_API_KEY`, `AZURE_OPENAI_API_KEY`, `HF_TOKEN`, `GITHUB_TOKEN`). Local
  profiles (strata, lmstudio, ollama, onnx) need no key at all. Host and model name
  now come from the YAML instead of `.env` - `.env` carries only the lane selection
  (`MODEL_CLIENT`, `MODEL_CLIENT_TOOLS`, `HUMAN_MODEL`) and the keys.
  `<PROFILE>_BASE_URL` / `<PROFILE>_MODEL` remain available as per-run overrides for
  the test harnesses.
- **No more deprecation noise.** Every `import fitz` became `import pymupdf as fitz`
  (`fitz` is the deprecated PyMuPDF alias) - seven sites. The two warnings we cannot fix
  upstream, traceloop's class-based Pydantic config and fastmcp's `authlib.jose` import,
  are filtered by their exact category in `pytest.ini` and through
  `lib/quiet_deprecations.suppress_third_party_deprecations()`, called before chainlit
  and fastmcp are imported in `app2.py` and `scripts/smoke_check.py`. Warnings from our
  own code are untouched, and `tests/test_no_deprecated_imports.py` guards against the
  alias coming back.
- Tool agents use `reflect_on_tool_use: false` with `max_tool_iterations: 10` instead of
  reflecting after every tool call.
- `terminate_agent` writes into `conversation/<SESSION_ID>/` rather than `experience/<SESSION_ID>/`.
- **pandoc and LaTeX are now optional.** When `pandoc` is missing the PDF is exported through
  PyMuPDF Story, which still embeds the diagram and writes a real outline.

- **Cleaner startup, no more warning noise.** Removed the inert pre-2.12 MCP sections from `.chainlit/config.toml` (they triggered a "Ignoring pre-2.12.0 MCP config sections" warning), added `USER_AGENT=TFM_BA_GPT/1.0` to `.env.example` (silences the langchain_community user-agent warning), replaced the default Chainlit welcome screen with an app-specific one (`chainlit.md` + `chainlit_en-US.md`, which also silences the missing-translation warning) and added a small app logo in `public/`. `/experience` runtime artifacts are now gitignored.

## 1.0.0 - 2026-11-02
First public release. The project was audited and patched to run reproducibly
on Windows, Linux and macOS without any machine-specific assumptions.

### Added
- `README.md`, `CONTRIBUTING.md`, `docs/architecture.md`,
  `docs/configuration.md`, `docs/troubleshooting.md`.
- `.env.example` documenting every environment variable.
- `scripts/smoke_check.py`: reports which packages, tools and config files are
  present before you try to run the app.
- `tests/`: an offline pytest suite (file tools, selector routing, config
  hygiene, MCP server startup, and a full end-to-end pipeline run with a
  scripted model client that needs no API key).
- `src/model_config_openai_npt.yaml`: OpenAI profile with
  `parallel_tool_calls: false` for tool-calling agents.
- Local `move_file_tool` and `ensure_dir_tool` in `lib/agents_tools_helpers.py`.
- GitHub Actions CI running the test suite on push.

### Fixed
- API keys are no longer hard-coded in `src/model_config_*.yaml`; they are
  injected from the environment by `src/model_loader.py`.
- Model and MCP paths were absolute Linux paths (`/run/media/...`); they are
  now resolved relative to the project root.
- `MaxMessageTermination(100000000)` replaced with `MAX_MESSAGES` (default 300).
- The **TERMINATE** termination token is now restricted to `terminate_agent` only
  (`TextMentionTermination(..., sources=["terminate_agent"])`); any agent echoing
  that word no longer ends a run mid-task (see `docs/troubleshooting.md`).
- `terminate_agent` referenced a file tool from a vendored MCP server that is
  not part of this repo; it now uses the local helpers.
- Mermaid MCP server: `mmdc` output was written to stdout and corrupted the MCP
  JSON-RPC stream; subprocess output is now captured. Windows `mmdc.cmd` is
  detected, and fenced Mermaid blocks are stripped before rendering.
- PDF MCP server: hard-coded `model.to('cuda')` now falls back to CPU.
- Deprecated `datetime.utcnow()` calls replaced with timezone-aware timestamps.
- `lib/agents_creator.py`: `resolve_memory` no longer returns `None` into a
  memory list when the requested memory type is unavailable.
- `requirements.txt` cleaned and pinned to the versions this project is known
  to work with.

### Removed
- Local artifacts, caches, logs, media and generated data were untracked from
  Git so the repository ships source and documentation only.

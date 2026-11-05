# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
- `/api/sessions` could time out while synchronous model setup started in the
  background; clients retrying the POST then created duplicate runs. Session runs
  now start as Starlette background tasks after the response is flushed, with a
  real-uvicorn regression test for the slow-start path.

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

# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-11-04

Makes the pipeline deterministic end-to-end on Windows and moves the model load off a single
provider: the agent team runs on the local GPU lane, the simulated stakeholder runs on a
remote lane, and the deliverables (PNG diagram, PDF with a real outline) are produced without
pandoc or LaTeX.

### Added
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
- **Final deliverables are presented in the chat when a run completes.** After "Workflow complete", `app2.py` now renders the full functional specification inline and attaches `process_diagram.png` (inline), `deliverable.pdf` and a downloadable copy of the `.md`. If `terminate_agent` skipped its file steps, it falls back to `conversation/functional_specification.md` and renders the diagram on the fly from `process_diagram.mmd` via `mmdc` (fences stripped; resolved with `shutil.which`, since bare `mmdc` is not found by Python subprocess on Windows).

### Fixed
- **A deliverable from a previous run could satisfy the current one.** `finalize_deliverables()`
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

# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- **The functional specification is now saved in chunks instead of one giant tool call.** `functional_spec_writer_agent` was instructed to pass the ENTIRE document (~10k words) as a single `write_md_file_tool` argument; on local models that degrades into a malformed text-form "tool call" that never executes, so no file appeared on disk while the agent still sent READY. The writer now saves sections 1-3 with `write_md_file_tool`, appends the remaining section groups with a new `append_md_file_tool` (each chunk < ~4000 words), always uses the tool's default path (`conversation/functional_specification.md`) instead of inventing one, and must verify all 9 sections on disk with `read_md_file_tool` before sending READY.
- **The spec checker no longer passes a missing file.** When `read_md_file_tool` reports the document is missing or empty (the writer's save failed), `functional_spec_checker_agent` now explicitly returns NEEDS_INFO listing "the entire document" instead of judging from conversation memory, so the planner routes back to the writer for a real re-save.
- **`terminate_agent` can actually read the interview log.** Step 1 ("extract session_id from interview.jsonl") was impossible: the agent had no file-read tool and fell back to `sess-unknown`. It now has `read_md_file_tool` and the prompt tells it exactly how to call it.
- **Infinite empty-message loops are stopped with a clear error.** After an unrecoverable malformed tool call, some models emit empty messages forever while the selector keeps re-selecting the same agent (previously only `MAX_MESSAGES=300` could end this). `app2.py` now cancels the run after 3 consecutive empty messages from one agent and explains what happened in the chat.
- **LM Studio mid-run failures are explained in the UI.** A model being unloaded (`400 Bad Request - Model unloaded by user or API request`) or a speculative-decoding engine crash previously only showed up as a console traceback; `app2.py` now catches these and posts an actionable hint (reload the model / restart the LM Studio server).

### Added
- `append_md_file_tool` in `lib/agents_tools_helpers.py`: appends a Markdown chunk to the spec file, used by the writer's chunked save flow.

- **User answers in `app2.py` are no longer rejected as empty.** Chainlit's `AskUserMessage.send()` returns a StepDict whose text lives under `"output"`, but the user-proxy input loop only read `"content"` (a key that does not exist), so every valid answer was treated as empty, re-asked forever and the workflow appeared to hang right after the interviewer's first question. `app2.py` now reads `"content"`/`"output"`/`"text"` like `app.py` already did; typing into the main chat bar while a run is in progress also gets an explicit hint instead of being silently dropped.
- **Memory-backed agents no longer crash on LM Studio / llama.cpp backends.** autogen's `ChromaDBVectorMemory` and `TextCanvasMemory` inject retrieved context as a SystemMessage appended at the *end* of the model context; llama.cpp rejects such requests (`Jinja Exception: System message must be at the beginning`), which killed the interviewer's turn right after the planner's assignment with no visible question. `lib/rag_helpers.py` now provides `TemplateSafeChromaDBVectorMemory` and `TemplateSafeTextCanvasMemory`, which inject the same content as a UserMessage; both apps use them for all memory-backed agents.
- **Interviewer agent no longer kills the workflow when the ChromaDB RAG store is unopenable.** A `chromadb_storage/` created by a different chromadb version only fails on first query (the client opens lazily), which crashed the interviewer's first turn and stopped the run right after the planner's assignment with no visible question. `app.py`/`app2.py` now validate the store at startup with one warm-up query and continue without RAG memory if it is unopenable (a warning is printed to the console). To restore RAG, delete `chromadb_storage/` and `index_state.json` so the store is rebuilt with the installed chromadb version.
- Corrected the embedding model name in `docs/troubleshooting.md` (`paraphrase-multilingual-mpnet-base-v2`, not `all-MiniLM-L6-v2`).
- **Final deliverables are presented in the chat when a run completes.** After "Workflow complete", `app2.py` now renders the full functional specification inline and attaches `process_diagram.png` (inline), `deliverable.pdf` and a downloadable copy of the `.md`. If `terminate_agent` skipped its file steps, it falls back to `conversation/functional_specification.md` and renders the diagram on the fly from `process_diagram.mmd` via `mmdc` (fences stripped; resolved with `shutil.which`, since bare `mmdc` is not found by Python subprocess on Windows).

### Changed
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

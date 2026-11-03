# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- **Memory-backed agents no longer crash on LM Studio / llama.cpp backends.** autogen's `ChromaDBVectorMemory` and `TextCanvasMemory` inject retrieved context as a SystemMessage appended at the *end* of the model context; llama.cpp rejects such requests (`Jinja Exception: System message must be at the beginning`), which killed the interviewer's turn right after the planner's assignment with no visible question. `lib/rag_helpers.py` now provides `TemplateSafeChromaDBVectorMemory` and `TemplateSafeTextCanvasMemory`, which inject the same content as a UserMessage; both apps use them for all memory-backed agents.
- **Interviewer agent no longer kills the workflow when the ChromaDB RAG store is unopenable.** A `chromadb_storage/` created by a different chromadb version only fails on first query (the client opens lazily), which crashed the interviewer's first turn and stopped the run right after the planner's assignment with no visible question. `app.py`/`app2.py` now validate the store at startup with one warm-up query and continue without RAG memory if it is unopenable (a warning is printed to the console). To restore RAG, delete `chromadb_storage/` and `index_state.json` so the store is rebuilt with the installed chromadb version.
- Corrected the embedding model name in `docs/troubleshooting.md` (`paraphrase-multilingual-mpnet-base-v2`, not `all-MiniLM-L6-v2`).

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

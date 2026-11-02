# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
- The planner no longer emits `TERMINATE` itself, which ended runs before the
  deliverables were produced.
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

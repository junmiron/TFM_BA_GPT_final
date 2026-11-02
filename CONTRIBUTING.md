# Contributing

Thanks for interest in BA-GPT. Small, focused pull requests are preferred - the
pipeline is a chain of prompts and tools, so large refactors are hard to verify.

## Before you start

1. Install dependencies and check your machine:

```bash
pip install -r requirements.txt
python scripts/smoke_check.py
```

2. Run the tests. They need no API key:

```bash
python -m pytest -q tests
```

## Branches and commits

- Branch from `main`; name the branch after the change (`fix/mermaid-rendering`).
- Keep commits scoped to one concern. Reference the issue number when there is one.
- Update `CHANGELOG.md` in the same pull request.

## Changing an agent

Agents live in `lib/agents_config.yaml` (or inline in `app2.py`). Each entry has:

| Key | Meaning |
|---|---|
| `type` | `assistant` or `user_proxy` |
| `description` | what the selector sees when choosing the next agent |
| `system_message` | the prompt |
| `tools` | dotted import paths, e.g. `agents_tools_helpers.read_md_file_tool` |
| `mcp_tools` | `mcp_boot.<name>` helpers |
| `use_memory` | `vector_memory`, `canvas_memory`, or `false` |
| `reflect_on_tool_use` | make the agent summarise after a tool call |
| `stream` | stream tokens to the UI |

If you add a tool, add a test in `tests/test_pipeline.py` that calls it.

If you change the hand-off protocol, also update the planner's `[ASSIGNMENT]`
marker rules and the termination chain in `terminate_agent`.

## Adding a model backend

1. Copy `src/model_config_template.yaml` to `src/model_config_<name>.yaml`.
2. Add the name to `CONFIG_FILES` and its key env var to `API_KEY_ENV` in
   `src/model_loader.py`.
3. Never put a real key in the YAML - the loader injects it from the environment.

## Security rules

- Never commit `.env`, real keys, or generated `conversation/` / `experience/` output.
- If a secret reaches the repository, rotate it and rewrite history with
  `git-filter-repo` before publishing.

## Style

- Match the surrounding code. Type hints and docstrings are welcome, ceremony is not.
- No new dependencies without a clear reason; discuss them in the pull request first.

# Configuration

Everything the app needs is either an environment variable or one of four YAML
files. No absolute paths are hard-coded: every path is resolved from the project
root.

## Environment variables

Create `.env` from `.env.example`. `.env` is gitignored and never read by the
model configs directly - `src/model_loader.py` loads it and injects the key.

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_CLIENT` | `openai` | profile used by the reasoning agents |
| `MODEL_CLIENT_TOOLS` | `openai_npt` | profile for agents that call tools |
| `MAX_MESSAGES` | `300` | hard cap on team turns |
| `OPENAI_API_KEY` | - | required for `openai` / `openai_npt` |
| `AZURE_OPENAI_API_KEY` | - | for the `azure` profile |
| `GROQ_API_KEY` | - | for the `groq` profile |
| `HF_TOKEN` | - | for the `hugging` profile |
| `GITHUB_TOKEN` | - | for the `github` profile |

`MODEL_CLIENT_TOOLS` exists because several agents call tools in the same turn,
and some backends reject `parallel_tool_calls`. `openai_npt` sets
`parallel_tool_calls: false`.

## Model profiles

Each `src/model_config_<name>.yaml` holds the provider and model name; the key
comes from the environment.

```yaml
provider: autogen_ext.models.openai.OpenAIChatCompletionClient
config:
  model: gpt-4o
  api_key: REPLACE_WITH_YOUR_API_KEY   # replaced at load time
  parallel_tool_calls: false
  model_info:
    vision: false
    function_calling: true
    json_output: true
```

Available out of the box: `openai`, `openai_npt`, `ollama`, `lmstudio`, `onnx`.
For Azure, Groq, Hugging Face or GitHub Copilot, copy `src/model_config_template.yaml`
to `src/model_config_<name>.yaml`. Those files are gitignored on purpose.

Local backends need a running server:

| Profile | Endpoint |
|---|---|
| `ollama` | `http://localhost:11434` |
| `lmstudio` | `http://localhost:1234/v1` |
| `onnx` | `http://localhost:5272/v1` |

## `lib/agents_config.yaml`

Defines the eleven participants. Per agent:

```yaml
interviewer_agent:
  type: assistant
  description: ...      # what the selector sees
  system_message: |     # the prompt
  tools:
    - agents_tools_helpers.save_conversation_to_jsonl
  mcp_tools:
    - mcp_boot.pdf_format_tools
  use_memory: vector_memory   # vector_memory | canvas_memory | false
  reflect_on_tool_use: true
  stream: true
```

Tool names are dotted import paths resolved by `lib/agents_creator.py`.
`lib/old/` keeps previous revisions of this file for reference; they are not used.

## `lib/rag_config.yaml`

```yaml
CHROMA_DIR: "chromadb_storage"     # ChromaDB persistence, project-relative
DOCS_DIR: "data"                   # documents to index
COLLECTION_NAME: "rag_collection"
STATE_FILE: "index_state.json"     # remembers what was already indexed
SITES:
  - "https://www.morebusiness.com/business-analyst-interview-questions/"
  ...
```

If `data/` is missing the indexer prints a warning and continues; it does not
fail. `SITES` entries are fetched with `readability`/`lxml` on first run.

## `.chainlit/config.toml`

Chainlit UI settings. Defaults are fine; the ones that matter here:

```toml
[project]
session_timeout = 3600            # keep the agent session alive for 1 hour
persist_user_env = false          # do not store keys in the Chainlit DB

[features.spontaneous_file_upload]
enabled = true                    # you can attach reference documents

[features.mcp.stdio]
allowed_executables = ["npx", "uvx"]
```

## External tools

| Tool | Needed for | Install |
|---|---|---|
| `mmdc` | PNG/SVG/PDF diagram rendering | `npm i -g @mermaid-js/mermaid-cli` |
| `pandoc` | PDF export | `winget install pandoc` / `apt install pandoc` |
| `xelatex` | PDF export | TeX Live / MiKTeX |

Check with `python scripts/smoke_check.py`. Missing `pandoc` or `xelatex` costs
you only `deliverable.pdf`; `mmdc` costs you `process_diagram.png`.

## What is never committed

`.env`, `data/`, `chromadb_storage/`, `conversation/`, `experience/`,
`*.log`, `__pycache__/`, `.venv*`, and all media/binaries. See `.gitignore`.

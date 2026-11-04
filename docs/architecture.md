# Architecture

BA-GPT is one `SelectorGroupChat` of eleven participants. A model decides which
agent speaks next; the orchestrator keeps the work moving through an explicit
hand-off protocol, and the last agent writes the deliverables to disk.

```
user ─┐
      │  planning_agent drives every hand-off
      ▼
planning_agent ─► interviewer_agent ─► summarizer_agent ─► functional_spec_writer_agent
                                                        │            │
                                                        │            ├─► use_case_agent
                                                        │            └─► glossary_agent
                                                        │
                                                        └─► functional_spec_checker_agent
                                                          │   (NEEDS_INFO → back to interviewer)
                                                          ▼
                                                     diagram_creator_agent
                                                          ▼
                                                     mermaid_code_reviewer_agent
                                                          ▼
                                                     terminate_agent  ─► TERMINATE
```

## The participants

| Agent | Role | Tools | Memory |
|---|---|---|---|
| `planning_agent` | decomposes the task, tracks pending/done, emits `[ASSIGNMENT]` markers | none | - |
| `interviewer_agent` | asks one `QUESTION:` per turn, saves each Q&A pair | `save_conversation_to_jsonl` | vector |
| `user` | Chainlit-backed `UserProxyAgent`; answers through the chat UI | none | - |
| `summarizer_agent` | summarises the interview; needs the exact reply `APPROVE SUMMARY` | none | vector |
| `functional_spec_writer_agent` | writes the 9-section FSD | `write_md_file_tool`, `read_md_file_tool` | vector |
| `functional_spec_checker_agent` | audits the spec, emits `NEEDS_INFO` or `READY` | `read_md_file_tool` | vector |
| `use_case_agent` | generates use cases / user stories on request | none | vector |
| `glossary_agent` | generates the glossary on request | none | vector |
| `diagram_creator_agent` | writes Mermaid code to the canvas | `read_md_file_tool`, `canvas.update_file_tool` | canvas |
| `mermaid_code_reviewer_agent` | reviews Mermaid syntax and clarity | `canvas.update_file_tool`, `write_mermaid_to_file_tool` | canvas |
| `terminate_agent` | runs the export pipeline and ends the run | `move_file_tool`, `ensure_dir_tool`, Mermaid MCP, PDF MCP | - |

Definitions live in `lib/agents_config.yaml` (`app.py`) or inline in `app2.py`.

## Hand-off protocol

The selector chooses the next speaker from the agents' `description` fields and
the conversation history. The orchestrator makes that deterministic by ending
every turn with exactly one marker line:

```
[ASSIGNMENT] agent=interviewer_agent task="ask about ordering" awaiting_user_reply=true
```

`lib/agents_tools_helpers.py` parses those markers (`_latest_assignment`,
`_phase`, `_agent_has_ready`) to keep the team from looping on the wrong agent.

Two invariants matter:

1. While `awaiting_user_reply=true`, only `user` may speak.
2. `TERMINATE` may only come from `terminate_agent`, so the run cannot end
   before the deliverables are written.

## Termination pipeline

`terminate_agent` runs a fixed sequence:

1. read `conversation/interview.jsonl` and take the first `session_id`
2. `ensure_dir_tool(conversation/<SESSION_ID>)`
3. `move_file_tool` the interview, spec and Mermaid file into that folder
4. `clean_mermaid(...)` on the `.mmd` file
5. `render_mermaid_png(...)`
6. `format_and_export(...)` → `functional_specification.formatted.md` and `deliverable.pdf`
7. `save_experience_chroma(...)` so the session is retrievable later
8. output `TERMINATE`

The team also has a hard stop: `MaxMessageTermination(MAX_MESSAGES)` (default 300),
combined with `TextMentionTermination("TERMINATE")`.

## MCP servers

Two stdio servers ship in `mcp_servers/` and are launched by `lib/mcp_boot.py`
with the project root as their only allowed directory.

**`mcp_servers/Mermaid-MCP/Mermaid-MCP.py`** - `check_mermaid`, `clean_mermaid`,
`render_mermaid_svg`, `render_mermaid_png`, `render_mermaid_pdf`,
`render_mermaid_all`, `png_to_jpg`. Requires the `mmdc` binary (mermaid-cli).
On Windows it resolves `mmdc.cmd`. Subprocess output is captured so it cannot
corrupt the JSON-RPC stream.

**`mcp_servers/Final_deliverable_MCP_server/PDF_format_mcp_server.py`** -
`format_spec`, `export_pdf`, `format_and_export`, `save_experience_chroma`,
`recall_experience_chroma`. Formatting is pure Python; the PDF step uses `pandoc` + `xelatex` when
present, otherwise PyMuPDF Story. Embeddings use `paraphrase-multilingual-mpnet-base-v2`, GPU if available,
otherwise CPU.

## RAG memory

`lib/rag_helpers.py` builds a ChromaDB collection (`rag_collection`) with a local
SentenceTransformer embedding function, indexes everything under `data/`, and
optionally scrapes the `SITES` list in `lib/rag_config.yaml`. `index_state.json`
records which documents were already indexed so re-runs do not re-embed.

Two memory types are exposed to agents:

- **vector memory** - ChromaDB-backed semantic recall for interview context
- **canvas memory** - AutoGen `TextCanvasMemory`, used as the shared scratch file
  for the Mermaid diagram (`canvas_diagram.md`)

## Data flow

```
data/            reference documents (local, gitignored)
chromadb_storage/  ChromaDB persistence (local, gitignored)
conversation/     working files while a session runs (gitignored)
conversation/<id>/  final deliverables per session (gitignored)
```

`docs/Conversation/` contains archived examples of finished sessions so you can
see the expected output shape without running the app.

## Where the design is fragile

- The orchestrator is a prompt, not a state machine. A model that drops the
  `[ASSIGNMENT]` marker stalls the pipeline; `MAX_MESSAGES` is the safety net.
- `summarizer_agent`'s approval is a literal string match.
- Both MCP servers only accept paths inside the project root.
- Diagram quality depends on `mmdc` being installed and on the reviewer loop
  converging.

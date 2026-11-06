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

Definitions live in `lib/agents_config.yaml` and `lib/pipeline.py`; `app2.py` wires them into the interview and termination sequence.

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
6. `format_and_export(...)` → `functional_specification.formatted.md` and `functional_specification.pdf`
7. `finalize_deliverables(...)` → renders every fence in the canvas (`process_diagram.png`, `process_diagram_2.png`, ...), embeds each PNG plus its Mermaid fence into `functional_specification.md`, and writes the self-contained `functional_specification.html` (diagram inlined as SVG when available)
8. **feedback gate** → asks whether the user is happy with the deliverables; "yes" indexes the session into the `approved_experiences` ChromaDB collection via `lib/experience_indexer.py`, a critique goes to `feedback/<session_id>.md`, silence indexes nothing
9. output `TERMINATE`

The team also has a hard stop: `MaxMessageTermination(MAX_MESSAGES)` (default 300),
combined with `TextMentionTermination("TERMINATE")`.

## MCP servers

Two stdio servers ship in `mcp_servers/` and are launched by `lib/mcp_boot.py`
with the project root as their only allowed directory.

**`mcp_servers/Mermaid-MCP/Mermaid-MCP.py`** - `check_mermaid`, `clean_mermaid`,
`render_mermaid_png`. Requires the
`mmdc` binary (mermaid-cli).
On Windows it resolves `mmdc.cmd`. Subprocess output is captured so it cannot
corrupt the JSON-RPC stream.

**`mcp_servers/Final_deliverable_MCP_server/PDF_format_mcp_server.py`** -
`format_spec`, `export_pdf`, `export_html`, `format_and_export`. Formatting is pure Python; the PDF step uses the Typst renderer
(`typst_render.py`: pandoc Markdown to Typst, cover page, linked Contents, bundled Inter font, tall-diagram band splitting)
when the binaries are installed - otherwise PyMuPDF Story.

## RAG memory

`lib/rag_helpers.py` builds a ChromaDB collection (`rag_collection`) with a local
SentenceTransformer embedding function, indexes everything under `data/`, and
optionally scrapes the `SITES` list in `lib/rag_config.yaml`. `index_state.json`
records which documents were already indexed so re-runs do not re-embed.
When `FEEDBACK_ENABLED=true`, a second ChromaDB collection (`approved_experiences`,
managed by `lib/experience_indexer.py`) holds only sessions the user approved,
and the interview/writer agents query both memories.

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

A live example session lives in `conversation/` while the app runs; finished
deliverables (`functional_specification.*`, diagrams) land in
`conversation/<SESSION_ID>/`.

## Where the design is fragile

- The orchestrator is a prompt, not a state machine. A model that drops the
  `[ASSIGNMENT]` marker stalls the pipeline; `MAX_MESSAGES` is the safety net.
- `summarizer_agent`'s approval is a literal string match.
- Both MCP servers only accept paths inside the project root.
- Diagram quality depends on `mmdc` being installed and on the reviewer loop
  converging.

# BA-GPT — Multi-Agent Business Analyst (AutoGen + Chainlit)

A multi-agent interviewer that runs a budgeted requirements interview with a
human, then produces a traceable **Functional Specification Document** plus a
process diagram and a PDF deliverable.

```
user  <->  planning_agent (orchestrator)
              |
              v
   interviewer_agent -> summarizer_agent -> functional_spec_writer_agent
                              (uses use_case_agent, glossary_agent)
                                    -> functional_spec_checker_agent
                                    -> diagram_creator_agent
                                    -> mermaid_code_reviewer_agent
                                    -> terminate_agent  (exports .mmd/.png/.pdf)
```

Outputs land in `experience/<SESSION_ID>/`:
`interview.jsonl`, `functional_specification.md`, `functional_specification.formatted.md`,
`process_diagram.mmd`, `process_diagram.png`, `deliverable.pdf`.

## Requirements

| Requirement | Why |
|---|---|
| Python 3.11+ (tested on 3.13) | AutoGen 0.7, Chainlit |
| Node.js + `mermaid-cli` (`mmdc`) | renders the process diagram PNG |
| `pandoc` + a LaTeX engine (`xelatex`) | renders `deliverable.pdf` (optional: without it you still get the Markdown) |
| An OpenAI (or Ollama / LM Studio) model | the agents |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
npm i -g @mermaid-js/mermaid-cli    # for the diagram
# optional: winget install pandoc / choco install texlive
```

Copy the env template and add your key:

```bash
cp .env.example .env    # then set OPENAI_API_KEY
```

Check the machine is ready:

```bash
python scripts/smoke_check.py
```

## Run

```bash
chainlit run app2.py -w
```

`app.py` is the YAML-driven variant of the same team (agents defined in
`lib/agents_config.yaml`); `app2.py` instantiates them explicitly. Both use the
same model loader, selector and tools.

Choose the model profile with `MODEL_CLIENT` in `.env`
(`openai`, `openai_npt`, `ollama`, `lmstudio`, `onnx`, ...).

## Configuration

| File | Purpose |
|---|---|
| `.env` | secrets and runtime switches (**never committed**) |
| `src/model_config_*.yaml` | model profiles; keys are injected from the environment |
| `lib/agents_config.yaml` | agent roles, system prompts, tools |
| `lib/rag_config.yaml` | ChromaDB directory, document folder, reference sites |
| `MAX_MESSAGES` | hard cap on team turns (default 300) |

## Tests

```bash
python -m pytest -q tests
```

`tests/test_pipeline.py` covers the file/JSONL tools, the selector routing and
config hygiene; `tests/test_mcp_servers.py` starts the bundled Mermaid and PDF
MCP servers and checks their tools.

## Project layout

```
app.py / app2.py          Chainlit entry points
lib/                      agent factory, tools, selector, RAG indexer, MCP boot
src/                      model client loader + model profiles
mcp_servers/              Mermaid renderer + deliverable formatter (stdio MCP)
data/                     reference documents indexed into ChromaDB (local)
conversation/            live working files during a session
experience/<session>/    final deliverables per session
docs/                     thesis material, transcripts, examples
```

## Known limitations

- PDF export needs `pandoc` + `xelatex`; without them the pipeline stops at
  `functional_specification.formatted.md` and reports it.
- Mermaid rendering needs `mmdc` on PATH (Windows uses the `mmdc.cmd` shim).
- The interview is interactive: a human must answer every `QUESTION:`.

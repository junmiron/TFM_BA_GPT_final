# Troubleshooting

Symptoms first, causes second. All of these were reproduced on this project.

## The app starts but nothing happens after the first message

The orchestrator is a prompt, not a state machine. If the planning agent stops
emitting its `[ASSIGNMENT]` marker, the selector has nothing to route on and the
run stalls until `MAX_MESSAGES` is reached.

```bash
# raise the ceiling while you debug
MAX_MESSAGES=600 chainlit run app2.py -w
```

Check that the model you picked is strong enough for instruction following.
`gpt-4o` works; small local models often drop the marker format.

## `400 Bad Request: parallel_tool_calls is not supported`

The backend rejects parallel tool calls. Set:

```bash
MODEL_CLIENT_TOOLS=openai_npt
```

`openai_npt` is the same model with `parallel_tool_calls: false`. For another
backend, edit that profile in `src/`.

## `No API key for profile 'openai'`

`.env` is missing or `OPENAI_API_KEY` is empty:

```bash
cp .env.example .env    # then set OPENAI_API_KEY
python scripts/smoke_check.py
```

## Mermaid renders nothing / `mmdc` not found

```bash
npm i -g @mermaid-js/mermaid-cli
mmdc --version
```

On Windows, npm installs both `mmdc` and `mmdc.cmd`. The MCP server looks for
both. If the agent still fails, render the file by hand to confirm the pipeline:

```bash
mmdc -i experience/<SESSION_ID>/process_diagram.mmd -o test.png
```

If the `.mmd` file contains ``` fences, the server strips them automatically
(`clean_mermaid` writes a `.clean.mmd` first).

## MCP server crashes with `Exception in subprocess` or a JSON parse error

Anything the MCP server prints to **stdout** corrupts the JSON-RPC stream. All
subprocesses in `mcp_servers/` must use `capture_output=True`. If you add a
tool, send diagnostics to stderr:

```python
print("debug", file=sys.stderr)
```

## `deliverable.pdf` is missing

PDF export needs `pandoc` **and** a LaTeX engine:

```bash
pandoc --version
xelatex --version
```

Without them the pipeline still produces `functional_specification.formatted.md`
and reports the missing dependency. The diagram and the interview log are
unaffected.

## Diagram never appears in `experience/<SESSION_ID>/`

`terminate_agent` moves the source files from `conversation/` into
`experience/<SESSION_ID>/`, so after a completed session `conversation/` is
empty. That is expected. If the session id could not be read from
`interview.jsonl`, the folder is named `sess-unknown`.

## `data/` indexing warnings

```
Documents directory not found: .../data - skipping local document indexing.
```

`data/` is gitignored. Put your reference PDFs/docx files there; the indexer
embeds them into `chromadb_storage/`. Delete `chromadb_storage/` and
`index_state.json` to force a clean re-index.

## Interviewer agent goes silent after the planner's assignment (ChromaDB store panic)

Symptom: the UI shows `planning_agent`'s `[ASSIGNMENT] agent=interviewer_agent ...`
message and then nothing — no question, no error bubble. The console ends with a
traceback containing:

```
pyo3_runtime.PanicException: range start index 10 out of range for slice of length 9
```

Cause: `chromadb_storage/` was created by a different (older) version of chromadb
than the one installed. The ChromaDB client is opened **lazily** on first query, so
startup succeeds and only the first memory-bearing agent turn (the interviewer's)
crashes — which kills the whole run mid-conversation.

Fix: rebuild the store with the installed chromadb version:

```bash
rm -rf chromadb_storage index_state.json   # Windows: rmdir /s /q chromadb_storage && del index_state.json
chainlit run app2.py -w                    # re-indexes data/ and the configured URLs on start
```

Since v1.0.1, `app.py`/`app2.py` also validate the store at startup (one warm-up
query) and continue without RAG memory instead of dying mid-conversation if it is
unopenable — you will see a `⚠️  RAG vector memory unavailable ...` line in the console.

## Interviewer goes silent on LM Studio: `System message must be at the beginning`

Symptom: same as above (planner's assignment, then silence), but the console ends
with an OpenAI-style error from the local backend:

```
openai.BadRequestError: Error code: 400 - ... "Jinja Exception: System message must be at the beginning."
```

Cause: autogen's memory implementations (`ChromaDBVectorMemory`, `TextCanvasMemory`)
inject retrieved context by appending a **SystemMessage at the end** of the model
context. llama.cpp-based backends (LM Studio) enforce chat-template ordering and
reject any request where a system message is not first — so every turn of an agent
with non-empty memory crashes, killing the run mid-conversation.

Fix: this project ships template-safe subclasses in `lib/rag_helpers.py`
(`TemplateSafeChromaDBVectorMemory`, `TemplateSafeTextCanvasMemory`) that inject
the same content as a **UserMessage** instead. Both apps already use them; if you
add another memory-backed agent, give it one of these classes rather than the raw
autogen ones when running against LM Studio / llama.cpp.

## RAG memory errors on first run

The embedding model `paraphrase-multilingual-mpnet-base-v2` downloads on first use.
After that it is cached by `sentence-transformers`. If the download fails, the app
falls back to CPU-only vector memory (and, since v1.0.1, continues without RAG).

## Tests fail on the end-to-end suite

`tests/test_end_to_end.py` needs `mmdc` because it asserts a rendered PNG.
Without it the test is skipped, not failed. The rest of the suite needs no key
and no network:

```bash
python -m pytest -q tests
```

## Windows path issues

Paths are resolved from the project root, so the app can be run from any
directory. If a tool reports a path outside the project, that is deliberate:
both MCP servers reject writes outside the project root to keep agents from
touching the filesystem elsewhere.

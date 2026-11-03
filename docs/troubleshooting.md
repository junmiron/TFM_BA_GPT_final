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

## Workflow hangs after the interviewer's first question: `Input cannot be empty`

Symptom: the interviewer asks its first question, you type an answer in the
question box and submit it, then the app replies "Input cannot be empty" and
asks again — forever. The console shows a `UserInputRequestedEvent` from the
user proxy and nothing after it.

Cause (fixed in v1.0.1): Chainlit's `AskUserMessage.send()` returns a StepDict
whose text is under `"output"`, but `app2.py`'s user-proxy input loop only read
`"content"` — a key that does not exist — so every valid answer looked empty and
was re-asked. The fix reads `"content"`/`"output"`/`"text"` (same as `app.py`).

Note: while a run is in progress, answers must go into the question box shown
in the chat; text typed into the main input bar at the bottom does not reach the
workflow (the app now tells you this explicitly).

## LM Studio: `Engine protocol predict stream returned an error` (`speculative batch index ...`)

Symptom: a run dies with "An error occurred in the group chat" and every agent's
turn fails with:

```
openai.BadRequestError: Error code: 400 - {'error': 'Engine protocol predict stream returned an error: {"code":500,"message":"got exception: speculative batch index N is not inside the current sub-batch ..."}'}
```

Cause: this is a crash *inside LM Studio's inference engine* (its draft-model /
speculative-decoding path), not in this project. Once it happens, every request
fails until the server state resets.

Fix: restart the local server — `lms server stop` then `lms server start`
(the loaded model stays in VRAM and comes back within seconds). If it keeps
happening, disable speculative decoding / the draft model for that model in
LM Studio's settings.

## The spec file never appears: writer says READY but `conversation/functional_specification.md` is missing

Symptom: `functional_spec_writer_agent` sends **READY** (and later the checker
complains about "missing sections"), yet there is no `functional_specification.md`
anywhere under `conversation/`. The console shows the writer's turn ending with a
huge block of text that *looks like* a tool call but was never executed.

Cause: the original prompt told the writer to pass the ENTIRE document (~10k words)
as one `write_md_file_tool` argument. On local models, arguments that large degrade
into malformed text-form "tool calls" — the model prints them instead of emitting a
valid function call, so nothing is written while the agent believes it saved.

Fix (in place since v1.0.1): the writer now saves in chunks — sections 1-3 with
`write_md_file_tool`, then section groups appended via `append_md_file_tool`
(each chunk < ~4000 words), always at the tool's default path, and must verify all
9 sections on disk with `read_md_file_tool` before sending READY. The checker also
treats a missing/empty file as NEEDS_INFO ("the entire document") instead of judging
from conversation memory, so the planner routes back to the writer for a real re-save.

If you still see it: the model is too weak for tool calling — use a stronger one
for `MODEL_CLIENT_TOOLS`.

## The workflow loops forever with empty messages from one agent (often `terminate_agent`)

Symptom: after some stage, the UI shows repeated empty bubbles from the same agent
and nothing else happens. In the console the selector keeps picking that agent turn
after turn until you kill it (`MAX_MESSAGES`, default 300, is the only backstop).

Cause: after an unrecoverable malformed tool call (see previous section), some models
emit empty messages forever; the custom `selector_func` re-selects `terminate_agent`
until it says TERMINATE, which never comes.

Fix (in place since v1.0.1): `app2.py` cancels the run after **3 consecutive empty
messages from one agent** and posts an explanation in the chat. Restart the chat to
continue; if a specific stage keeps doing this, check that LM Studio is serving the
expected model and consider a stronger tool-calling model for `MODEL_CLIENT_TOOLS`.

## Run dies mid-way: `400 Bad Request - Model unloaded by user or API request`

Symptom: a run works for a while, then every LLM call fails with:

```
openai.BadRequestError: Error code: 400 - {'error': 'Model unloaded by user or API request'}
```

Cause: LM Studio unloaded the model from VRAM (manually, via its UI/API, or because
another app took the GPU memory). The OpenAI-compatible endpoint then rejects every
request until the model is loaded again.

Fix: reload `qwen3.8-27b` in LM Studio and restart the chat. To make this less likely,
disable "unload on idle" for the model in LM Studio's settings if you run long
multi-agent sessions (a full pipeline can take 10+ minutes of wall time).

Since v1.0.1 `app2.py` also catches this error and posts an actionable hint in the UI
instead of only printing a traceback to the console.

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

# Dependency upgrade plan (v1.2.0)

Anchor of the whole matrix is **AutoGen**, because every agent, tool and memory
object in this project comes from it. Everything else is pinned to whatever is
both latest *and* provably compatible with that anchor.

## 1. AutoGen (the anchor)

| Package | Before | After | Why |
|---|---|---|---|
| `autogen-agentchat` | 0.7.4 | **0.7.5** | Latest release. Microsoft archived `autogen` (read-only since 2025), so 0.7.5 is the terminal version — there is no 0.8 line to chase. |
| `autogen-core` | 0.7.4 | **0.7.5** | Must match agentchat exactly. |
| `autogen-ext[openai,chromadb,mcp,ollama]` | 0.7.4 | **0.7.5** | Same. Extras used: `openai` (every lane is an OpenAI-compatible chat client), `chromadb` (RAG + experience memory), `mcp` (the two MCP servers), `ollama` (profile registry). |

Verified in the venv: `AssistantAgent`, `UserProxyAgent`, `AgentTool`,
`SelectorGroupChat`, `StdioServerParams`, `mcp_server_tools`,
`ChromaDBVectorMemory`, `TextCanvasMemory`, `OpenAIChatCompletionClient` all
import and run. The 0.7.4 → 0.7.5 API surface is unchanged, so no code rewrite
was required.

## 2. Downstream and application dependencies

| Package | Before | After | Constraint |
|---|---|---|---|
| `chainlit` | `>=2.5,<3` | **2.12.0** | Latest. It is the only thing that caps `mcp`: chainlit 2.12 requires `mcp>=1.28.1,<2.0.0`. |
| `fastapi` | — | **0.162.0** | Latest at the UI integration; serves REST/WebSocket endpoints and mounts the React build. |
| `uvicorn[standard]` | — | **0.54.0** | Latest at the UI integration; ASGI server. The `wsproto` test transport avoids the deprecated websockets legacy path. |
| `mcp` | `>=1.9` | **1.30.0** | Latest 1.x. 2.x exists but chainlit forbids it. |
| `fastmcp` | `>=2.6,<3` | **3.4.11** | 4.1.6 requires `mcp>=2.3` → conflicts with chainlit. 3.4.11 is the newest that still accepts `mcp<2`, and it also fixes the `authlib.jose` deprecation path. |
| `chromadb` | `>=1.0,<2` | **1.5.9** | Required by `autogen-ext[chromadb]` (`>=1.0`). Existing `chromadb_storage/` reads fine on 1.5.9. |
| `sentence-transformers` | `>=5.0` | **6.2.0** | Embedding model `paraphrase-multilingual-mpnet-base-v2` still resolves; embeddings verified (768-dim) after upgrade. |
| `torch` | unpinned | **>=2.2,<3** | Pulled by sentence-transformers; 2.15.0 CPU wheel installed and verified (768-dim embeddings). Kept open so a CUDA build can be swapped in without touching the pin. |
| `openai` | unpinned | **>=3.46** | autogen-ext needs `>=1.93`; 3.46 verified against `strata`, `opencode` and `groq` lanes. |
| `pydantic` | `>=2.11,<3` | **>=2.14,<3** | chainlit/autogen both work on 2.14.2. |
| `PyMuPDF` | `>=1.24` | **2.1** | PDF Story + bookmarks (`set_toc`) already used; `fitz` alias replaced by `pymupdf`. |
| `lxml` | `>=5.0` | **6.1.3** | + `lxml_html_clean` 0.4.2 (the Cleaner moved out of `lxml.html.clean`). |
| `readability-lxml` | `>=0.8` | **0.9** | |
| `pillow` | `>=10.0` | **13.0.0** | PNG scaling for tall diagrams. |
| `beautifulsoup4` | `>=4.12` | **4.15.0** | |
| `markdown` | `>=3.5` | **3.11.2** | HTML deliverable. |
| `python-dotenv` | `>=1.0` | **1.2.4** | |
| `PyYAML` | `>=6.0` | **6.0.3** | |
| `pytest` | `>=8.0` | **9.2.0** | |
| `numpy` | unpinned | **>=1.26,<2.5** | numpy 2.5 requires Python ≥3.12; CI runs 3.11 and 3.13. |
| `onnxruntime` | commented out | **>=1.31** | chromadb's default embedding path; now installed, so the smoke check stops warning. |

## 3. Packages removed

**`langchain` and `langchain-community` are gone.** Two reasons:

1. `langchain-community` is sunset (emits a `DeprecationWarning` on import),
   which broke the "no deprecation noise" guarantee the test suite enforces.
2. langchain 1.x removed `langchain.text_splitter`, so the old import path is
   dead anyway.

Only four things were actually used from it — a text splitter, a PDF loader, a
text loader and a web loader. All four are replaced with ~60 lines using
libraries the project already depends on (`pymupdf`, `httpx`, `readability`,
`lxml`), plus a stdlib DOCX reader. Net effect: **5 fewer packages**, no
deprecation warnings, no behavioural change in the RAG corpus.

## 4. External tooling

| Tool | Before | After |
|---|---|---|
| `@mermaid-js/mermaid-cli` (`mmdc`) | 12.0.0 | **12.2.0** |
| Node.js | 26.8.1 | unchanged (Vitest 5 supports Node 22.12, 24 and 26; CI pins 26.8.1) |
| CI `actions/checkout` | v4 | **v7.0.1** (commit-pinned) |
| CI `actions/setup-python` | v5 | **v7.1.0** (commit-pinned) |
| CI `actions/setup-node` | — | **v7.1.0** (commit-pinned) |
| CI Python matrix | 3.11, 3.13 | unchanged (chainlit caps at <3.14) |

CI installs `mermaid-cli@12.2.0` explicitly so diagram tests don't drift
against whatever npm serves that day.

## 5. React UI toolchain

The UI dependency lock was refreshed separately from the AutoGen/Python stack.
The upgrades were applied in compatibility batches and verified after each:

| Package | Before | After | Notes |
|---|---|---|---|
| `react`, `react-dom` | 18.3.1 | **19.3.1** | React 19 migration guide followed; the app uses `createRoot` and has no removed legacy render API. |
| `@types/react`, `@types/react-dom` | 18.x | **19.3.0** | Matched to React 19; typecheck passes. |
| `vite` | 5.4.21 | **8.3.5** | Vite 8 uses Rolldown/Oxc; current configuration has no deprecated Rollup/esbuild options. |
| `@vitejs/plugin-react` | 4.7.0 | **6.1.2** | Peer-compatible with Vite 8. |
| `vitest` | 2.1.9 | **5.0.5** | Vite >=6.4 and Node >=22.12; current CI uses Node 26.8.1. |
| `typescript` | 5.9.3 | **7.0.2** | Strict typecheck passes on the native compiler. |
| `tailwindcss` | 3.4.19 | **4.3.3** | Moved to `@import "tailwindcss"` and CSS `@theme`; removed v3 PostCSS config and `autoprefixer`. |
| `@tailwindcss/vite` | — | **4.3.3** | Tailwind's Vite plugin, compatible with Vite 8; replaces the v3 PostCSS integration. |

The next patch releases of `@vitejs/plugin-react` (6.2.1), Tailwind (4.3.4)
and Vitest (5.1.0) had been published on Nov 2, right at the dependency
upgrade policy's three-day cooldown on Nov 5. The newest older compatible
releases are selected above; those newer patches are deferred until the cooldown
expires. The Tailwind 4 target requires Safari 16.4+, Chrome 111+, and Firefox 128+.
The UI uses modern Chromium and CI's hosted browser build; keep Tailwind 3.4
instead if older browsers become a supported target. Sources:

- [React 19 upgrade guide](https://react.dev/blog/2024/04/25/react-19-upgrade-guide)
- [Vite migration guide](https://vite.dev/guide/migration.html)
- [Vitest 5 migration guide](https://vitest.dev/guide/migration/)
- [Tailwind CSS upgrade guide](https://tailwindcss.com/docs/upgrade-guide)

## 6. Verification gates

The upgrade is only "done" when all of these are green:

1. `pytest tests` — full suite, zero warnings.
2. `python test/e2e_real_pipeline.py` — real model lanes + MCP servers + PDF.
3. `python test/test_terminate_pipeline.py` — terminate agent path.
4. `python test/roleplay_e2e.py` — full interview-to-deliverable run.
5. `python scripts/smoke_check.py` — lane keys, mmdc, engines.
6. Live lane probe: `strata`, `opencode`, `groq` each return a completion.
7. RAG probe: persisted ChromaDB collection queries after the chromadb bump.
8. `cd ui && npm ci && npm run typecheck && npm test && npm run build` —
   lockfile install, 24 UI tests, and production bundle.

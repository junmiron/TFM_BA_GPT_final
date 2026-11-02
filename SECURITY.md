# Security Policy

BA-GPT runs locally and talks directly to your model provider. It has no
server, no database of user data, and no telemetry.

## What is never stored

- **API keys** live in `.env` or your shell environment. The YAML model
  profiles contain only the `REPLACE_WITH_YOUR_API_KEY` placeholder; the key is
  injected at load time by `src/model_loader.py`.
- **Interview content** is written to `conversation/` and `experience/<session>/`
  on your machine. Both are gitignored.
- **ChromaDB embeddings** are persisted in `chromadb_storage/` (gitignored).

## Reporting a vulnerability

Open a private issue or email `junmiron@gmail.com`. Do not post keys or
interview content in a public issue.

## If a key has been committed

1. Rotate it at the provider - the value is already public.
2. Remove it from the working tree (`git rm --cached .env`).
3. Rewrite history with `git-filter-repo`:

```bash
git filter-repo --invert-paths --path .env
```

4. Force-push. A shallow clone is not enough: old commits still carry blobs.

## Scope of the MCP servers

Both MCP servers accept a `-d` allowed directory and reject writes outside it.
Do not widen that to your home directory.

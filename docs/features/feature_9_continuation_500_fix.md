# Feature 9 - Fix session continuation (HTTP 500)

Status: implemented (2026-11-06).

## Root cause (reproduced)
`lib/continuation.py:_model_complete` calls

```python
response = await client.create_completion([...])
```

AutoGen 0.7.5 (installed in `.venv_win`) has **no** `create_completion` method -
the client exposes `create(messages) -> CreateResult`. The `AttributeError`
bubbles through the API's try/except into a bare
`HTTPException(500, "continuation failed: ...")`.

Reproduced by running `apply_supplement` on a copy of
`conversation/sess-e2e-20261105093824` (the session in the screenshot): it
fails exactly at `continuation.py:59`.

Side observations:
- The supplement is already appended to `supplements.jsonl` **before** the
  model call, so the audit trail is intact even on failure - good.
- The unit tests passed because they inject a fake `complete=` function; the
  production path was never exercised. That is the test gap.

## Design
1. `_model_complete` calls `client.create([...])` and reads `.content`, using
   the same retry/recovery wrappers `load_model_client` already applies.
2. If the model call itself fails (e.g. Strata server down), fall back to the
   deterministic Addendum merge instead of a 500 - the user's supplement is
   never lost and the spec version still bumps.
3. API returns the real detail: `{"merged": "fallback", "reason": "model
   unavailable: <short error>"}` so the UI shows a useful message, plus the
   server logs the traceback.
4. Tests:
   - `_model_complete` exercised against a stub client exposing only `create`
     (catches the exact API-name regression).
   - apply_supplement with a raising model -> Addendum fallback + bumped
     version + deliverables re-rendered.

## Files touched
- `lib/continuation.py`
- `server/api.py` (error detail)
- `tests/test_continuation_transcript.py`

## Acceptance
- "Update specification" succeeds with the configured lane, or clearly reports
  a fallback when the lane is unreachable. No bare 500.

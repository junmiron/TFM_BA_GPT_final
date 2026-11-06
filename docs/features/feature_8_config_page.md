# Feature 8 - In-app configuration page

Status: implemented (2026-11-06).

## Problem
All switches (model lanes, keys, human simulation, UI visibility) live in
`.env` and require editing a file by hand. The user wants a settings page
reachable from the interface.

## Design

### Entry point
- Gear icon in the header ("Configuration"). Clicking it swaps the SPA to a
  **dedicated Configuration view** in the same page/app (no new deployment,
  no new server); "Back to session" returns to the interview. The main
  layout, sessions and WS connections are untouched while the view is open.

### What the page shows (grouped)
1. **Model lanes**
   - Reasoning lane (`MODEL_CLIENT`): dropdown of the 11 profiles
     (openai, openai_npt, azure, groq, hugging, github, opencode, ollama,
     lmstudio, strata, onnx).
   - Tool-calling lane (`MODEL_CLIENT_TOOLS`).
   - Per-profile **Model ID** and **Base URL** overrides
     (`<PROFILE>_MODEL`, `<PROFILE>_BASE_URL`) - exactly the override
     mechanism `src/model_loader.py` already supports.
2. **API keys** (one per remote service)
   - `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, `GROQ_API_KEY`, `HF_TOKEN`,
     `GITHUB_TOKEN`, `OPENCODE_GO_API_KEY`.
   - The page never reads back key values: each field shows
     "set (••••••)" or "not set". Typing a new value replaces it.
   - Local services (strata, lmstudio, ollama, onnx) do not require an API key.
3. **Human simulation**
   - Enable/disable AI-human interview (`SIMULATE_HUMAN`).
   - Which service plays the stakeholder (`HUMAN_MODEL` dropdown).
4. **UI visibility** (mirrors Feature 2)
   - Show/hide Artifacts panel (`UI_SHOW_ARTIFACTS`).
   - Show/hide internal agent messages (`UI_SHOW_INTERNAL_MESSAGES`).
5. **Run limits** (included per approval)
   - `MAX_MESSAGES`, `MAX_CHECKER_ROUNDS`, `FEEDBACK_ENABLED`,
     `FEEDBACK_TIMEOUT_S`.

### Backend contract
- `GET /api/config` -> current values; keys only as `{env: "OPENAI_API_KEY", present: true}`;
  list of available profiles and any model/base URL environment overrides.
- `PUT /api/config` -> partial dict of whitelisted variables only. Anything
  not in the whitelist is rejected (400). Values are validated
  (profile names via `PROFILES` + aliases, booleans, ints in sane ranges).
- On save: update `os.environ` **and** rewrite the project `.env` in place
  (only the whitelisted lines; other lines untouched, line endings preserved).
- Effect timing:
  - UI flags: the front-end refetches `/api/health` and re-renders live.
  - Model lanes/keys: apply to the **next session** that is created
    (`create_workflow` builds fresh clients per session). A run already in
    flight is not interrupted - the page states this clearly.

### Security notes
- Keys are never echoed by the API, only presence booleans.
- `.env` stays gitignored; the settings page writes only whitelisted keys.
- This is a local app (127.0.0.1); if ever exposed publicly, the settings
  page would need authentication - flagged, not solved here.

## Files touched
- `server/api.py` - `/api/config` GET/PUT + `.env` writer helper.
- `ui/src/components/SettingsPage.tsx` (new), gear icon in `Header.tsx`,
  view switch in `App.tsx`.
- `tests/test_config_api.py` - whitelist enforcement, masking, .env round-trip,
  invalid values rejected; empty profile overrides restore YAML defaults.
- UI build and integration smoke check - settings view loads and saves through PUT.

## Acceptance
- Gear icon opens a settings page with all switches listed above.
- Changing a lane and starting a new session uses the new lane.
- Keys never appear in plain text in any API response or page.

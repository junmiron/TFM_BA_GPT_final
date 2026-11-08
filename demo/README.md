# BA-GPT interactive demo

A static, self-contained replay of a real BA-GPT interview that runs in the
browser - no server, no model keys, no rate limits. It replays the event log
recorded from a genuine headless run (`scripts/record_demo_replay.py`) through
the **same** React components and reducer the product uses (`ui/src/...`), so
what you see in the demo is what the real app renders.

## What you get

- Fixed goal pre-filled (WashLoop laundry shop). One button: **Start interview**.
- Real-time transcript playback: agent messages, status updates, tool activity,
  stage progress in the run panel.
- **Pause / resume**, speed control (2x, 4x, 8x, 16x), restart.
- Two modes: conversation only, or full internal agent messages (toggle).
- Artifact viewer at the end: the functional specification (PDF download + HTML
  preview) and the process diagrams, straight from `examples/sample_session/`.

## How the data is produced

```text
scripts/record_demo_replay.py   headless run, records replay_events.jsonl + replay_meta.json
scripts/export_sample_session.py copies deliverables + replay log to examples/sample_session/
demo/scripts/copy_sample.mjs    prebuild step: sample files -> demo/public/
```

## Run locally

```bash
cd demo
npm install
npm run dev        # http://localhost:5173/ba-gpt/demo/ (base path set for Vercel)
```

## Build for Vercel

```bash
npm run build      # dist/ is a static SPA; serve under /ba-gpt/demo/
```

The build is pure static output (`vite.config.ts` sets `base: '/ba-gpt/demo/'`),
so it can be copied into the portfolio site's `site/ba-gpt/demo/` folder and
deployed with no server.

URL params: `?speed=16` sets the playback speed, `?agents=0` hides internal
agent messages by default.

## Tests

```bash
npm test           # vitest: replay engine (parse, offsets, scheduling, artifacts)
npm run typecheck  # tsc against the shared ui/src types
```

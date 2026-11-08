#!/usr/bin/env python3
"""Record a full, fully scripted demo run as a replayable event log (Feature 14).

Headless run with SIMULATE_HUMAN: the simulated stakeholder answers every
interview question, so the demo is reproducible without a human. The recorded
stream is exactly what ``server/api.py`` broadcasts to the web UI - same event
types, same payloads, real timestamps - so the interactive Vercel demo replays
the genuine UI behaviour through the same reducer, not a mock.

Defaults: the demo goal comes from ``demo/goal.md``; the human lane is forced
to ``opencode`` (override with --human-model) so Groq-style tokens/min ceilings
never throttle the interview half of a demo run.

Usage:
    python scripts/record_demo_replay.py
    python scripts/record_demo_replay.py --task "..." --session-id sess-demo-1
    python scripts/record_demo_replay.py --human-model groq

Outputs (inside the session folder):
    replay_events.jsonl   one JSON object per event, with ISO-8601 UTC "ts"
    replay_meta.json      task, lanes, duration, event counts, artifact list
"""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import agents_tools_helpers  # noqa: E402
from lib.pipeline import PROJECT_ROOT, create_workflow, run_workflow  # noqa: E402

# Same kinds the web UI uses (server/api.py ARTIFACT_KINDS).
ARTIFACT_KINDS = {
    "functional_specification.pdf": "pdf",
    "functional_specification.html": "html",
    "functional_specification.md": "markdown",
    "functional_specification.formatted.md": "markdown",
    "interview.jsonl": "jsonl",
    "process_diagram.mmd": "mermaid",
}


def kind_of(name: str) -> str:
    if name in ARTIFACT_KINDS:
        return ARTIFACT_KINDS[name]
    if name.startswith("process_diagram") and name.endswith(".png"):
        return "png"
    return "file"


def list_artifacts(session_dir: Path) -> list:
    return [
        {
            "name": f.name,
            "kind": kind_of(f.name),
            "size": f.stat().st_size,
            "url": f"/api/files/{session_dir.name}/{f.name}",
        }
        for f in sorted(session_dir.iterdir())
        if f.is_file()
    ]


class RecordingSink:
    """EventSink that appends every event to a JSONL file as it happens.

    Writing incrementally means a crashed or interrupted run still leaves a
    usable partial log for inspection.
    """

    def __init__(self, log_path: Path, session_dir: Path) -> None:
        self.log_path = log_path
        self.session_dir = session_dir
        self.events: list = []
        self.counts: Counter = Counter()

    def record(self, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        self.events.append(event)
        self.counts[event["type"]] += 1
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    async def info(self, content: str) -> None:
        self.record({"type": "info", "content": content})

    async def message(self, source: str, content: str) -> None:
        self.record({"type": "message", "source": source, "content": content})

    async def stream(self, source: str, content: str) -> None:
        self.record({"type": "chunk", "source": source, "content": content})

    async def flush(self) -> None:
        pass

    async def complete(self, stop_reason) -> None:
        self.record({"type": "complete", "stop_reason": str(stop_reason),
                     "artifacts": list_artifacts(self.session_dir)})

    async def error(self, content: str) -> None:
        self.record({"type": "error", "content": content})


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=None, help="Goal text (default: demo/goal.md)")
    parser.add_argument("--goal-file", default=str(ROOT / "demo" / "goal.md"))
    parser.add_argument("--session-id", default=None, help="Session id (default: sess-demo-<utc>)")
    parser.add_argument("--human-model", default="opencode",
                        help="Lane for the simulated stakeholder (default: opencode)")
    args = parser.parse_args()

    task = args.task
    if not task:
        goal = Path(args.goal_file)
        if not goal.is_file():
            print(f"error: no task given and {goal} does not exist", file=sys.stderr)
            return 2
        task = goal.read_text(encoding="utf-8").strip()
    if not task:
        print("error: task is empty", file=sys.stderr)
        return 2

    os.environ["SIMULATE_HUMAN"] = "true"
    os.environ["HUMAN_MODEL"] = args.human_model

    session_id = args.session_id or "sess-demo-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    session_dir = Path(PROJECT_ROOT) / "conversation" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "replay_events.jsonl"
    log_path.unlink(missing_ok=True)

    started = datetime.now(timezone.utc)
    print(f"Recording demo run into {session_dir}")
    print(f"  lanes: agents={os.getenv('MODEL_CLIENT')} tools={os.getenv('MODEL_CLIENT_TOOLS')} "
          f"human={os.getenv('HUMAN_MODEL')}")

    sink = RecordingSink(log_path, session_dir)

    async def notify(content: str, author=None) -> None:
        # Mirrors server/api.py: user-authored notifications become answer events.
        sink.record({"type": "answer" if author == "user" else "info", "content": content})

    async def ask_user(prompt=None) -> str:
        # Only reached if the human simulator is unavailable; fail loudly instead
        # of blocking a headless run on input nobody will provide.
        raise RuntimeError(
            "Simulated stakeholder unavailable - demo recording needs SIMULATE_HUMAN=true "
            f"and a working {args.human_model} lane."
        )

    workflow = await create_workflow(ask_user, notify, session_id)
    workflow["session_id"] = session_id  # pin the folder, as the API server does

    try:
        result = await run_workflow(workflow, task, sink)
    except Exception as e:
        result = {"session_id": session_id, "stop_reason": None, "error": f"{type(e).__name__}: {e}"}
        await sink.error(result["error"])

    if not result.get("error"):
        try:
            agents_tools_helpers.finalize_deliverables(str(session_dir))
        except Exception as e:
            sink.record({"type": "info", "content": f"Deliverables finalization warning: {type(e).__name__}: {e}"})

    # The authoritative download list, same event the live UI receives last.
    sink.record({"type": "artifacts", "artifacts": list_artifacts(session_dir)})

    ended = datetime.now(timezone.utc)
    meta = {
        "session_id": session_id,
        "task": task,
        "lanes": {
            "model_client": os.getenv("MODEL_CLIENT", "openai"),
            "model_client_tools": os.getenv("MODEL_CLIENT_TOOLS", "openai"),
            "human_model": os.getenv("HUMAN_MODEL", "opencode"),
        },
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "wall_duration_s": round((ended - started).total_seconds()),
        "event_count": len(sink.events),
        "event_counts": dict(sink.counts),
        "sources": sorted(e["source"] for e in sink.events if e.get("type") in ("message", "chunk")),
        "stop_reason": result.get("stop_reason"),
        "error": result.get("error"),
        "artifacts": list_artifacts(session_dir),
    }
    (session_dir / "replay_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(meta, indent=2, ensure_ascii=False))
    if result.get("error"):
        print(f"run failed: {result['error']}", file=sys.stderr)
        return 1
    print(f"OK: {len(sink.events)} events, {sink.counts['message']} messages, "
          f"{sink.counts['chunk']} chunks, {sink.counts['answer']} stakeholder answers")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""FastAPI backend for the React web UI.

One workflow, two front-ends: this server drives the same ``lib.pipeline`` team
that ``app2.py`` drives through Chainlit. Chainlit stays the operator/debug
view; this is the product UI.

Run:
    python -m uvicorn server.api:app --port 8000
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.quiet_deprecations import suppress_third_party_deprecations

suppress_third_party_deprecations()

from lib import agents_tools_helpers
from lib.pipeline import PROJECT_ROOT, STAGES, create_workflow, run_workflow

CONV_ROOT = Path(PROJECT_ROOT) / "conversation"
UI_DIST = Path(PROJECT_ROOT) / "ui" / "dist"

ARTIFACT_KINDS = {
    "functional_specification.pdf": "pdf",
    "functional_specification.html": "html",
    "functional_specification.md": "markdown",
    "functional_specification.formatted.md": "markdown",
    "interview.jsonl": "jsonl",
    "process_diagram.mmd": "mermaid",
}


def _title_of(text: str) -> str:
    """First heading or first non-empty line, for the session list."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if line:
                return line[:120]
        return line[:120]
    return "untitled run"


def _kind(name: str) -> str:
    if name in ARTIFACT_KINDS:
        return ARTIFACT_KINDS[name]
    if name.startswith("process_diagram") and name.endswith(".png"):
        return "png"
    return "file"


_STOP_ANSWER = object()


class Session:
    """One workflow run plus the event log the UI replays on reconnect."""

    def __init__(self, session_id: str, task: str):
        self.id = session_id
        self.task = task
        self.status = "running"
        self.started_at = datetime.now(timezone.utc)
        self.events: List[dict] = []
        self.clients: set[WebSocket] = set()
        self.workflow: Optional[dict] = None
        self.answers: asyncio.Queue = asyncio.Queue()
        self.messages: int = 0
        self.error: Optional[str] = None

    def record(self, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        self.events.append(event)
        for ws in list(self.clients):
            try:
                asyncio.create_task(ws.send_json(event))
            except Exception:
                self.clients.discard(ws)

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "title": _title_of(self.task),
            "updated_at": self.started_at.isoformat(),
            "status": self.status,
            "artifact_count": len(self.artifacts()),
            "messages": self.messages,
        }

    def session_dir(self) -> Path:
        return CONV_ROOT / self.id

    def artifacts(self) -> List[dict]:
        d = self.session_dir()
        if not d.is_dir():
            return []
        out = []
        for f in sorted(d.iterdir()):
            if f.is_file():
                out.append({
                    "name": f.name,
                    "kind": _kind(f.name),
                    "size": f.stat().st_size,
                    "url": f"/api/files/{self.id}/{f.name}",
                })
        return out

    def stages(self) -> List[dict]:
        spoken = {e.get("source") for e in self.events if e.get("type") == "message"}
        ready = {e.get("source") for e in self.events
                 if e.get("type") == "message" and "READY" in (e.get("content") or "")}
        out = []
        for key, label, agent in STAGES:
            if agent in ready or self.status == "done":
                state = "done"
            elif agent in spoken:
                state = "active"
            else:
                state = "pending"
            out.append({"key": key, "label": label, "agent": agent, "state": state})
        return out


SESSIONS: Dict[str, Session] = {}


def _persisted_sessions() -> List[dict]:
    """Runs from previous days that only exist on disk."""
    if not CONV_ROOT.is_dir():
        return []
    out = []
    for d in sorted(CONV_ROOT.iterdir(), reverse=True):
        if not d.is_dir() or d.name in SESSIONS:
            continue
        files = [f for f in d.iterdir() if f.is_file()]
        if not files:
            continue
        updated = max(f.stat().st_mtime for f in files)
        has_pdf = (d / "functional_specification.pdf").is_file()
        out.append({
            "id": d.name,
            "task": (d / "functional_specification.md").read_text(encoding="utf-8", errors="ignore")[:400]
            if (d / "functional_specification.md").is_file() else "previous run",
            "title": _title_of((d / "functional_specification.md").read_text(encoding="utf-8", errors="ignore")
                               if (d / "functional_specification.md").is_file() else d.name),
            "updated_at": datetime.fromtimestamp(updated, tz=timezone.utc).isoformat(),
            "status": "done" if has_pdf else "unknown",
            "artifact_count": len(files),
            "messages": 0,
        })
    return out


app = FastAPI(title="TFM BA GPT API", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "lanes": {
            "model_client": os.getenv("MODEL_CLIENT", "openai"),
            "model_client_tools": os.getenv("MODEL_CLIENT_TOOLS", "openai_npt"),
            "human_model": os.getenv("HUMAN_MODEL", "opencode"),
        },
        "simulate_human": os.getenv("SIMULATE_HUMAN", "").strip().lower() in ("1", "true", "yes"),
        "ui_build": UI_DIST.is_dir(),
    }


@app.get("/api/sessions")
def list_sessions() -> dict:
    live = [s.to_summary() for s in SESSIONS.values()]
    return {"sessions": live + _persisted_sessions()}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {**s.to_summary(), "events": s.events, "stages": s.stages(), "artifacts": s.artifacts()}


async def _start_run(session: Session) -> None:
    async def ask_user(prompt: Optional[str] = None) -> str:
        # Blocking on the queue is how the UI answers an interview question.
        session.status = "awaiting_answer"
        while True:
            answer = await session.answers.get()
            if answer is _STOP_ANSWER:
                return ""
            if answer:
                session.status = "running"
                return answer
            session.record({"type": "error", "content": "Input cannot be empty. Please reply with some text."})

    async def notify(content: str, author: Optional[str] = None) -> None:
        session.record({"type": "answer" if author == "user" else "info", "content": content})

    try:
        session.workflow = await create_workflow(ask_user, notify)
    except Exception as e:
        session.status = "failed"
        session.error = f"Could not build the team: {type(e).__name__}: {e}"
        session.record({"type": "error", "content": session.error})
        return

    if session.status == "stopped":
        session.record({"type": "artifacts", "artifacts": session.artifacts()})
        return

    class Sink:
        async def info(self, content: str) -> None:
            session.record({"type": "info", "content": content})

        async def message(self, source: str, content: str) -> None:
            session.record({"type": "message", "source": source, "content": content})

        async def stream(self, source: str, content: str) -> None:
            session.record({"type": "chunk", "source": source, "content": content})

        async def flush(self) -> None:
            pass

        async def complete(self, stop_reason: Any) -> None:
            session.record({"type": "complete", "stop_reason": str(stop_reason)})

        async def error(self, content: str) -> None:
            session.record({"type": "error", "content": content})

    try:
        result = await run_workflow(session.workflow, session.task, Sink())
    except Exception as e:  # a crash inside the run must surface in the UI, not vanish
        result = {"error": f"{type(e).__name__}: {e}", "stop_reason": None}
    session.messages = session.workflow.get("messages", 0)
    session.error = result.get("error")
    if session.status != "stopped":
        session.status = "done" if result.get("stop_reason") and not result.get("error") else "failed"

    if session.status == "done":
        # Make sure the PDF/HTML actually exist before the UI offers them.
        try:
            agents_tools_helpers.finalize_deliverables(str(session.session_dir()))
        except Exception as e:
            session.record({"type": "error", "content": f"Deliverables incomplete: {type(e).__name__}: {e}"})
    session.record({"type": "artifacts", "artifacts": session.artifacts()})


@app.post("/api/sessions")
async def create_session(payload: dict) -> dict:
    task = (payload.get("task") or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="task is required")

    session_id = "sess-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    session = Session(session_id, task)
    SESSIONS[session_id] = session
    # The run is a background task so the WS connection stays free for answers.
    asyncio.create_task(_start_run(session))
    return {"session_id": session_id}


def _handle_client_message(session: Session, msg: dict) -> None:
    """The UI sends two things over the socket: an answer, or a stop request."""
    kind = msg.get("type")
    if kind == "answer":
        session.answers.put_nowait(str(msg.get("content", "")))
    elif kind == "stop":
        token = (session.workflow or {}).get("cancellation_token")
        if token is not None:
            token.cancel()
        session.answers.put_nowait(_STOP_ANSWER)
        session.status = "stopped"
        session.record({"type": "info", "content": "Run stopped by the user."})


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: str) -> dict:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    token = (session.workflow or {}).get("cancellation_token")
    if token is not None:
        token.cancel()
    session.answers.put_nowait(_STOP_ANSWER)
    session.status = "stopped"
    session.record({"type": "info", "content": "Run stopped by the user."})
    return {"session_id": session_id, "status": session.status}


@app.get("/api/sessions/{session_id}/artifacts")
def session_artifacts(session_id: str) -> dict:
    session = SESSIONS.get(session_id)
    if session is not None:
        files = session.artifacts()
    else:
        d = CONV_ROOT / "".join(c for c in session_id if c.isalnum() or c in "-_")
        files = [{"name": f.name, "kind": _kind(f.name), "size": f.stat().st_size,
                  "url": f"/api/files/{session_id}/{f.name}"}
                 for f in sorted(d.iterdir()) if f.is_file()] if d.is_dir() else []
    return {"artifacts": files}


@app.get("/api/files/{session_id}/{name}")
def get_file(session_id: str, name: str):
    # Session id and name come from the client: reject anything that could walk
    # out of conversation/<SESSION_ID>/.
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
    safe_name = Path(name).name
    path = CONV_ROOT / safe_id / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, filename=safe_name)


@app.websocket("/ws/sessions/{session_id}")
async def session_ws(ws: WebSocket, session_id: str) -> None:
    session = SESSIONS.get(session_id)
    if session is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    session.clients.add(ws)
    try:
        for event in session.events:  # replay, so a reconnect shows the whole run
            await ws.send_json(event)
        while True:
            _handle_client_message(session, await ws.receive_json())
    except WebSocketDisconnect:
        session.clients.discard(ws)


if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")
else:
    @app.get("/")
    def index() -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "hint": "The web UI is not built yet. Run `npm run build` in ui/, "
                    "or use the Chainlit app with `chainlit run app2.py`.",
        })

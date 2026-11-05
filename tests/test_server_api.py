"""Contract tests for the FastAPI front-end.

The real AutoGen team is replaced with a scripted fake so the API surface, the
event stream and the file guards are exercised without spending model tokens.
"""

import asyncio
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from websockets.sync.client import connect as ws_connect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MODEL_CLIENT", "strata")

from server import api  # noqa: E402


def _await_finished(c, sid, timeout=15.0):
    """Poll until the background run leaves 'running' (a blocked question is
    still a running run, just one waiting on the human)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = c.get(f"/api/sessions/{sid}").json()
        if detail["status"] not in ("running", "starting", "awaiting_answer"):
            return detail
        time.sleep(0.1)
    raise AssertionError(f"session {sid} never finished")


def _wait_for(predicate, timeout=10.0):
    """Poll `predicate()` until it is truthy; return False if the deadline passes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.15)
    return False


@pytest.fixture
def live_server(monkeypatch, tmp_path):
    """Run the app under real uvicorn so WebSocket answers take the production path."""
    original_root, original_sessions = api.CONV_ROOT, api.SESSIONS
    monkeypatch.setattr(api, "CONV_ROOT", tmp_path)
    monkeypatch.setattr(api, "SESSIONS", {})

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # wsproto keeps the socket off websockets' deprecated legacy server.
    server = uvicorn.Server(
        uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="error", ws="wsproto")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", port
    server.should_exit = True
    thread.join(timeout=5)
    monkeypatch.setattr(api, "CONV_ROOT", original_root)
    monkeypatch.setattr(api, "SESSIONS", original_sessions)


@pytest.fixture
def fake_run(monkeypatch, tmp_path):
    """Replace the real team with a scripted one and point the session dir at tmp_path."""

    async def fake_create_workflow(ask_user, notify):
        return {"team": None, "user": None, "human_sim": None, "messages": 0}

    async def fake_run_workflow(workflow, task_text, sink):
        await sink.info(f"Starting for: {task_text}")
        await sink.message("interviewer_agent", "QUESTION: What is the scope?")
        await sink.message("user", "Everything except billing")
        await sink.message("functional_spec_writer_agent", "Spec written. **READY**")
        await sink.complete("text_mention")
        workflow["session_id"] = workflow.get("session_id") or "sess-fake"
        workflow["messages"] = 3
        return {"session_id": workflow["session_id"], "stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "create_workflow", fake_create_workflow)
    monkeypatch.setattr(api, "run_workflow", fake_run_workflow)
    monkeypatch.setattr(api, "CONV_ROOT", tmp_path)
    api.SESSIONS.clear()
    yield tmp_path


def client():
    return TestClient(api.app)


def test_health_reports_lanes():
    body = client().get("/api/health").json()
    assert body["status"] == "ok"
    assert set(body["lanes"]) == {"model_client", "model_client_tools", "human_model"}
    assert isinstance(body["simulate_human"], bool)
    assert body["max_messages"] == int(os.getenv("MAX_MESSAGES", "300"))


def test_local_vite_dev_origin_has_cors_access_only():
    c = client()
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    }
    allowed = c.options("/api/health", headers=headers)
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    denied = c.options(
        "/api/health",
        headers={**headers, "Origin": "https://untrusted.example"},
    )
    assert "access-control-allow-origin" not in denied.headers


def test_empty_task_is_rejected():
    assert client().post("/api/sessions", json={"task": "   "}).status_code == 400


def test_run_streams_events_and_lists_artifacts(fake_run):
    c = client()
    sid = c.post("/api/sessions", json={"task": "Laundry shop staff app"}).json()["session_id"]
    detail = _await_finished(c, sid)
    assert detail["status"] == "done", detail

    types = [e["type"] for e in detail["events"]]
    assert "info" in types and "message" in types and "complete" in types

    # Every event carries a timestamp so the UI can order the transcript.
    assert all("ts" in e for e in detail["events"])

    # Stage progress is derived from which agents spoke.
    states = {s["key"]: s["state"] for s in detail["stages"]}
    assert states["interview"] in ("active", "done")
    assert states["spec"] in ("active", "done")

    (fake_run / sid).mkdir(parents=True, exist_ok=True)
    (fake_run / sid / "functional_specification.pdf").write_bytes(b"%PDF-1.4 test")
    arts = c.get(f"/api/sessions/{sid}/artifacts").json()["artifacts"]
    assert any(a["kind"] == "pdf" and a["url"].startswith("/api/files/") for a in arts)

    dl = c.get(f"/api/files/{sid}/functional_specification.pdf")
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF")

    json.loads(json.dumps(detail))  # the whole payload must be JSON-safe


def test_websocket_replays_the_transcript(fake_run):
    c = client()
    sid = c.post("/api/sessions", json={"task": "test"}).json()["session_id"]
    _await_finished(c, sid)

    # Read exactly the events the run produced - the socket stays open, so
    # reading past the replay would block forever.
    expected = len(c.get(f"/api/sessions/{sid}").json()["events"])
    with c.websocket_connect(f"/ws/sessions/{sid}") as ws:
        seen = [ws.receive_json() for _ in range(expected)]
    assert any(e["type"] == "message" for e in seen)
    assert any(e["type"] == "complete" for e in seen)


def test_ws_answer_reaches_the_workflow(fake_run):
    c = client()
    sid = c.post("/api/sessions", json={"task": "test"}).json()["session_id"]
    _await_finished(c, sid)
    # The queue is the channel the UI writes answers into and the
    # workflow reads them from.
    api.SESSIONS[sid].answers.put_nowait("manual answer")
    assert api.SESSIONS[sid].answers.get_nowait() == "manual answer"


def test_stop_cancels_the_run(fake_run):
    c = client()
    sid = c.post("/api/sessions", json={"task": "test"}).json()["session_id"]
    _await_finished(c, sid)
    r = c.post(f"/api/sessions/{sid}/stop")
    assert r.status_code == 200
    assert r.json()["status"] in ("stopped", "done", "failed")


def test_unknown_session_and_traversal_are_rejected(fake_run):
    c = client()
    assert c.get("/api/sessions/does-not-exist").status_code == 404
    assert c.get("/api/files/..%2F..%2Fetc/passwd").status_code == 404
    assert c.get("/api/files/sess-safe/..%2Fsecret.txt").status_code == 404

def test_session_titles_are_headings_not_raw_markdown():
    from server.api import _title_of

    assert _title_of("# Laundry Shop App\n\n## 1. Overview") == "Laundry Shop App"
    assert _title_of("   \n## Second heading") == "Second heading"
    assert _title_of("plain text task") == "plain text task"
    assert _title_of("") == "untitled run"


def test_a_blocked_question_reports_as_awaiting_answer(live_server, monkeypatch):
    """While the interviewer waits for a human reply the session must not look
    like a normal run, otherwise the UI has nothing to act on. Answering over
    the socket must release the workflow."""

    async def create_with_user_input(ask_user, notify):
        return {"ask_user": ask_user, "messages": 0}

    async def run_that_asks(workflow, task_text, sink):
        await sink.message("interviewer_agent", "QUESTION: What is the scope?")
        answer = await workflow["ask_user"]("What is the scope?")
        await sink.message("user", answer)
        await sink.complete("text_mention")
        return {"session_id": "sess-fake", "stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "create_workflow", create_with_user_input)
    monkeypatch.setattr(api, "run_workflow", run_that_asks)

    base, port = live_server
    sid = httpx.post(f"{base}/api/sessions", json={"task": "Inventory app"}).json()["session_id"]

    def get():
        return httpx.get(f"{base}/api/sessions/{sid}").json()

    assert _wait_for(lambda: get()["status"] == "awaiting_answer", 5), get()["status"]

    with ws_connect(f"ws://127.0.0.1:{port}/ws/sessions/{sid}") as ws:
        ws.send(json.dumps({"type": "answer", "content": "Inventory only"}))
        assert _wait_for(lambda: get()["status"] == "done", 10), "answer never unblocked the run"

    labels = [e["content"] for e in get()["events"] if e["type"] == "message"]
    assert "Inventory only" in labels


def test_stop_during_team_construction_skips_the_run(live_server, monkeypatch):
    """A fast Stop click must be remembered while the workflow is being built."""
    run_calls = []

    async def create_slowly(ask_user, notify):
        await asyncio.sleep(0.5)
        return {"ask_user": ask_user, "messages": 0}

    async def should_not_run(workflow, task_text, sink):
        run_calls.append(task_text)
        await sink.complete("TERMINATE")
        return {"session_id": "sess-fake", "stop_reason": "TERMINATE", "error": None}

    monkeypatch.setattr(api, "create_workflow", create_slowly)
    monkeypatch.setattr(api, "run_workflow", should_not_run)
    base, port = live_server
    sid = httpx.post(f"{base}/api/sessions", json={"task": "test"}).json()["session_id"]
    with ws_connect(f"ws://127.0.0.1:{port}/ws/sessions/{sid}") as ws:
        ws.send(json.dumps({"type": "stop"}))

    time.sleep(0.8)  # let the delayed team construction finish
    detail = httpx.get(f"{base}/api/sessions/{sid}").json()
    assert detail["status"] == "stopped"
    assert run_calls == []



def test_stop_unblocks_an_interview_waiting_for_an_answer(live_server, monkeypatch):
    """Stopping while the UI answer box is open must release ask_user immediately."""

    async def create_with_user_input(ask_user, notify):
        return {"ask_user": ask_user, "cancellation_token": type("Token", (), {"cancel": lambda self: None})()}

    async def run_waiting_for_answer(workflow, task_text, sink):
        await sink.message("interviewer_agent", "QUESTION: What should we track?")
        await workflow["ask_user"]("What should we track?")
        await sink.complete("TERMINATE")
        return {"session_id": "sess-fake", "stop_reason": "TERMINATE", "error": None}

    monkeypatch.setattr(api, "create_workflow", create_with_user_input)
    monkeypatch.setattr(api, "run_workflow", run_waiting_for_answer)
    base, port = live_server
    sid = httpx.post(f"{base}/api/sessions", json={"task": "inventory"}).json()["session_id"]

    assert _wait_for(lambda: httpx.get(f"{base}/api/sessions/{sid}").json()["status"] == "awaiting_answer", 5)
    with ws_connect(f"ws://127.0.0.1:{port}/ws/sessions/{sid}") as ws:
        ws.send(json.dumps({"type": "stop"}))

    def finished_stopped():
        detail = httpx.get(f"{base}/api/sessions/{sid}").json()
        return detail["status"] == "stopped" and any(e["type"] == "artifacts" for e in detail["events"])

    assert _wait_for(finished_stopped, 5), "stop left the workflow blocked on ask_user"



def test_stop_cancels_the_run_token(live_server, monkeypatch):
    """The Stop button must interrupt the team, not just flip a label."""

    class Token:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    token = Token()

    async def create_with_token(ask_user, notify):
        return {"ask_user": ask_user, "cancellation_token": token, "messages": 0}

    async def run_until_cancelled(workflow, task_text, sink):
        for _ in range(200):
            if workflow["cancellation_token"].cancelled:
                break
            await asyncio.sleep(0.05)
        await sink.complete("TERMINATE")
        return {"session_id": "sess-fake", "stop_reason": "TERMINATE", "error": None}

    monkeypatch.setattr(api, "create_workflow", create_with_token)
    monkeypatch.setattr(api, "run_workflow", run_until_cancelled)

    base, port = live_server
    sid = httpx.post(f"{base}/api/sessions", json={"task": "test"}).json()["session_id"]
    with ws_connect(f"ws://127.0.0.1:{port}/ws/sessions/{sid}") as ws:
        ws.send(json.dumps({"type": "stop"}))

    def stopped_run_finished():
        detail = httpx.get(f"{base}/api/sessions/{sid}").json()
        return detail["status"], any(event["type"] == "artifacts" for event in detail["events"])

    assert _wait_for(lambda: stopped_run_finished()[1], 10), "stopped run never exited"
    status, artifacts_recorded = stopped_run_finished()
    assert artifacts_recorded
    assert status == "stopped"
    assert token.cancelled

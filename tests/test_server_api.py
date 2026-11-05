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

    async def fake_create_workflow(ask_user, notify, session_id=None):
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


def test_health_human_lane_is_a_model_only_when_simulating(monkeypatch):
    monkeypatch.setenv("SIMULATE_HUMAN", "true")
    monkeypatch.setenv("HUMAN_MODEL", "opencode")
    body = client().get("/api/health").json()
    assert body["simulate_human"] is True
    assert body["lanes"]["human_model"] == "opencode"

    monkeypatch.delenv("SIMULATE_HUMAN", raising=False)
    body = client().get("/api/health").json()
    assert body["simulate_human"] is False
    assert body["lanes"]["human_model"] == "user"


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

    # The completion carries the artifact snapshot and is followed by the
    # authoritative artifacts event; without both the UI shows no downloads.
    completes = [e for e in detail["events"] if e["type"] == "complete"]
    assert completes and "artifacts" in completes[-1]
    assert "artifacts" in types

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


def test_create_session_responds_before_workflow_initialization(live_server, monkeypatch):
    """Workflow/model setup may block the event loop; POST must return first so
    the client does not time out and repeat a non-idempotent create request."""
    started = threading.Event()
    release = threading.Event()

    async def slow_create_workflow(ask_user, notify, session_id=None):
        started.set()
        release.wait(timeout=3)
        return {"messages": 0}

    async def finish(workflow, task, sink):
        await sink.complete("text_mention")
        return {"stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "create_workflow", slow_create_workflow)
    monkeypatch.setattr(api, "run_workflow", finish)
    monkeypatch.setattr(api.agents_tools_helpers, "finalize_deliverables", lambda *_: {})
    base, _ = live_server

    try:
        started_at = time.monotonic()
        response = httpx.post(f"{base}/api/sessions", json={"task": "Inventory app"}, timeout=1.0)
        elapsed = time.monotonic() - started_at
        assert response.status_code == 200
        assert elapsed < 1.0, f"POST waited {elapsed:.2f}s for workflow initialization"
        assert started.wait(1), "background workflow did not start"
    finally:
        release.set()

    sid = response.json()["session_id"]
    assert _wait_for(lambda: httpx.get(f"{base}/api/sessions/{sid}").json()["status"] == "done", 5)


def test_a_blocked_question_reports_as_awaiting_answer(live_server, monkeypatch):
    """While the interviewer waits for a human reply the session must not look
    like a normal run, otherwise the UI has nothing to act on. Answering over
    the socket must release the workflow."""

    async def create_with_user_input(ask_user, notify, session_id=None):
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


def test_turn_counter_moves_while_the_run_is_in_progress(live_server, monkeypatch):
    """The UI's "N of M turns used" line reads session.messages. It was only
    assigned after the workflow returned, so every live run read "No turns used
    yet." even with dozens of messages in the transcript.
    """

    async def create(ask_user, notify, session_id=None):
        return {"ask_user": ask_user, "messages": 0}

    async def run_that_waits(workflow, task_text, sink):
        await sink.message("interviewer_agent", "QUESTION: What is the scope?")
        await sink.message("planning_agent", "Task state: - user: pending")
        await sink.message("interviewer_agent", "QUESTION: Who are the users?")
        await sink.message("summarizer_agent", "Summary drafted. **READY**")
        answer = await workflow["ask_user"]("Confirm the summary")
        await sink.message("user", answer)
        await sink.complete("text_mention")
        return {"session_id": "sess-fake", "stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "create_workflow", create)
    monkeypatch.setattr(api, "run_workflow", run_that_waits)

    base, port = live_server
    sid = httpx.post(f"{base}/api/sessions", json={"task": "Inventory app"}).json()["session_id"]

    def detail():
        return httpx.get(f"{base}/api/sessions/{sid}").json()

    assert _wait_for(lambda: detail()["messages"] >= 4, 10), detail()
    assert detail()["status"] in ("running", "awaiting_answer"), "run finished too early"

    with ws_connect(f"ws://127.0.0.1:{port}/ws/sessions/{sid}") as ws:
        ws.send(json.dumps({"type": "answer", "content": "Inventory only"}))
        assert _wait_for(lambda: detail()["status"] == "done", 10)
    assert detail()["messages"] == 5, detail()["messages"]


def test_stop_during_team_construction_skips_the_run(live_server, monkeypatch):
    """A fast Stop click must be remembered while the workflow is being built."""
    run_calls = []

    async def create_slowly(ask_user, notify, session_id=None):
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

    async def create_with_user_input(ask_user, notify, session_id=None):
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

    async def create_with_token(ask_user, notify, session_id=None):
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

def test_deliverables_land_in_the_folder_the_ui_serves(fake_run, monkeypatch):
    """lib/pipeline.py invents a `sess-<timestamp>` folder when the workflow has no
    id, which put the PDF/HTML in a directory the artifacts endpoint never reads:
    a finished run with zero downloads (seen live on sess-20261105051520)."""
    monkeypatch.setattr(api.agents_tools_helpers, "finalize_deliverables", lambda d: {})

    async def fake_run_workflow(workflow, task_text, sink):
        session_id = workflow.get("session_id")
        if not session_id:
            session_id = "sess-invented"
            workflow["session_id"] = session_id
        folder = api.CONV_ROOT / session_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "functional_specification.md").write_text("# Invented run", encoding="utf-8")
        return {"session_id": session_id, "stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "run_workflow", fake_run_workflow)
    c = client()
    sid = c.post("/api/sessions", json={"task": "Laundry shop staff app"}).json()["session_id"]
    assert _await_finished(c, sid)["status"] == "done"

    arts = c.get(f"/api/sessions/{sid}/artifacts").json()["artifacts"]
    assert any(a["name"] == "functional_specification.md" for a in arts), arts
    assert not (fake_run / "sess-invented").exists(), "the run wrote to a folder the UI cannot read"

def test_finalize_closes_the_template_and_flags_hollow_sections(fake_run, monkeypatch):
    """A completed run must export a structurally complete document.

    Sections the writer skipped are assembled from the spec's own material; a
    section with nothing to say gets a fill-in marker and is reported in the
    transcript as an advisory, not as a failed run.
    """

    async def run_with_spec(workflow, task_text, sink):
        # _start_run pins workflow["session_id"] to the id the API tracks.
        sess = fake_run / workflow["session_id"]
        sess.mkdir(parents=True, exist_ok=True)
        (sess / "functional_specification.md").write_text(
            "# Order App\n\n## 1. Introduction\nTrack orders.\n\n"
            "## 2. Scope\nOnly intake is in scope.\n\n"
            "## 3. Functional Requirements\n"
            "**FR-001: Accept an order**\n"
            "Staff take an order at the counter and mark it Received.\n",
            encoding="utf-8",
        )
        workflow["messages"] = 1
        return {"session_id": workflow["session_id"], "stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "run_workflow", run_with_spec)
    c = client()
    sid = c.post("/api/sessions", json={"task": "Order app"}).json()["session_id"]
    _await_finished(c, sid)

    detail = c.get(f"/api/sessions/{sid}").json()
    assert detail["status"] == "done"
    notices = [e["content"] for e in detail["events"] if e["type"] == "info"]
    assert any("Template completeness" in n for n in notices)

    md = (fake_run / sid / "functional_specification.md").read_text(encoding="utf-8")
    assert "## 8. Glossary" in md
    assert "FR-001 Accept an order" in md
    assert "Fill it in before sign-off" in md

"""Feature 3 (session continuation) and Feature 4 (meeting transcript to spec)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import continuation, transcript_loader  # noqa: E402

SPEC = """# Warehouse Traceability Spec

| Version | v1.0 |
|---|---|

## Functional Requirements
FR-01 The system shall record every pallet move.

## Non-Functional Requirements
NFR-01 The audit trail must be retained for 5 years.
"""


# ---- continuation ----

def test_apply_supplement_merges_and_bumps_version(tmp_path):
    session = tmp_path / "sess-CONT"
    session.mkdir()
    (session / "functional_specification.md").write_text(SPEC, encoding="utf-8")

    def fake_complete(prompt: str) -> str:
        assert "NEW INFORMATION FROM THE CLIENT" in prompt
        return SPEC.replace(
            "NFR-01 The audit trail must be retained for 5 years.",
            "NFR-01 The audit trail must be retained for 5 years.\nFR-02 The system shall scan pallets at the gate.",
        )

    result = asyncio.run(continuation.apply_supplement(session, "Add gate scanning.", complete=fake_complete))
    updated = (session / "functional_specification.md").read_text(encoding="utf-8")
    assert "FR-02" in updated
    assert "| Version | v1.1 |" in updated
    assert result["merged"] == "model"
    line = json.loads((session / "supplements.jsonl").read_text(encoding="utf-8"))
    assert line["supplement"] == "Add gate scanning."


def test_bad_model_output_falls_back_to_addendum(tmp_path):
    session = tmp_path / "sess-FALLBACK"
    session.mkdir()
    (session / "functional_specification.md").write_text(SPEC, encoding="utf-8")

    def bad_complete(prompt: str) -> str:
        return "I could not update the spec."

    result = asyncio.run(continuation.apply_supplement(session, "Add gate scanning.", complete=bad_complete))
    updated = (session / "functional_specification.md").read_text(encoding="utf-8")
    assert result["merged"] == "fallback"
    assert "## Addendum (client supplement)" in updated
    assert "FR-01" in updated  # original content preserved


def test_bump_version_variants():
    assert "| Version | v1.3 (draft) |" in continuation._bump_version("| Version | v1.2 (draft) |")
    assert "v2.1" in continuation._bump_version("**Version:** v2.0")
    bumped = continuation._bump_version("# Title\n\nBody")
    assert "**Version:** v1.1" in bumped


# ---- transcript loader ----

def test_extract_plain_text():
    text = transcript_loader.extract_trans_text("meeting.txt", "BA: We need SLAs. Eng: 4 hours.")
    assert "4 hours" in text


def test_extract_strips_vtt_and_srt_timings():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nWe need real-time tracking.\n\n1\n00:00:06.000 --> 00:00:09.000\nAlerts by SMS."
    srt = "1\n00:00:01,000 --> 00:00:05,000\nWe need real-time tracking."
    assert "real-time tracking" in transcript_loader.extract_trans_text("cap.vtt", vtt)
    assert "real-time tracking" in transcript_loader.extract_trans_text("cap.srt", srt)
    assert "-->" not in transcript_loader.extract_trans_text("cap.vtt", vtt)


def test_extract_docx_uses_existing_readers(tmp_path):
    # A minimal valid docx is hard to craft inline; the extractor must at least
    # reject unknown formats.
    with pytest.raises(ValueError):
        transcript_loader.extract_trans_text("meeting.xyz", "whatever")


def test_task_with_transcript_seeds_instructions():
    task = transcript_loader.build_task_with_transcript("Cold chain", "BA: we need temperature alerts.")
    assert "MEETING TRANSCRIPT" in task
    assert "temperature alerts" in task
    assert "only to fill gaps" in task


# ---- API surface ----

@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    from server import api

    async def fake_create_workflow(ask_user, notify, session_id=None):
        return {"team": None, "user": None, "human_sim": None, "messages": 0}

    monkeypatch.setattr(api, "create_workflow", fake_create_workflow)
    monkeypatch.setattr(api, "CONV_ROOT", tmp_path)
    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    api.SESSIONS.clear()
    yield api, tmp_path
    api.SESSIONS.clear()


def test_session_with_transcript_seeds_task(fake_api, monkeypatch):
    from fastapi.testclient import TestClient

    api, tmp_path = fake_api
    captured = {}

    async def fake_run_workflow(workflow, task_text, sink):
        captured["task_text"] = task_text
        await sink.complete("text_mention")
        return {"session_id": "sess-fake", "stop_reason": "text_mention", "error": None}

    monkeypatch.setattr(api, "run_workflow", fake_run_workflow)

    transcript = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nThe ERP team wants pallet scan at every gate."
    payload = {
        "task": "Gate scanning",
        "transcript_name": "meeting.vtt",
        "transcript_base64": base64.b64encode(transcript.encode()).decode(),
    }
    client = TestClient(api.app)
    resp = client.post("/api/sessions", json=payload)
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    assert "MEETING TRANSCRIPT" in captured.get("task_text", "")
    assert "pallet scan at every gate" in captured.get("task_text", "")
    saved = tmp_path / sid / "source_transcript.txt"
    assert saved.is_file() and "-->" not in saved.read_text(encoding="utf-8")


def test_bad_transcript_format_is_rejected(fake_api):
    from fastapi.testclient import TestClient

    api, _ = fake_api
    client = TestClient(api.app)
    resp = client.post("/api/sessions", json={
        "task": "x", "transcript_name": "meeting.xyz",
        "transcript_base64": base64.b64encode(b"hello").decode(),
    })
    assert resp.status_code == 400


def test_continue_endpoint_updates_spec(fake_api, monkeypatch):
    from fastapi.testclient import TestClient
    from lib import continuation

    api, tmp_path = fake_api
    sid = "sess-CONT-API"
    session_dir = tmp_path / sid
    session_dir.mkdir()
    (session_dir / "functional_specification.md").write_text(SPEC, encoding="utf-8")

    monkeypatch.setattr(continuation, "_model_complete",
                        lambda prompt: SPEC + "\n\nFR-03 The system shall send SMS alerts.\n")

    client = TestClient(api.app)
    resp = client.post(f"/api/sessions/{sid}/continue", json={"supplement": "Add SMS alerts."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["merged"] == "model"
    updated = (session_dir / "functional_specification.md").read_text(encoding="utf-8")
    assert "FR-03" in updated and "v1.1" in updated


def test_continue_requires_supplement(fake_api):
    from fastapi.testclient import TestClient

    api, tmp_path = fake_api
    (tmp_path / "sess-X").mkdir()
    client = TestClient(api.app)
    assert client.post("/api/sessions/sess-X/continue", json={"supplement": ""}).status_code == 400
    assert client.post("/api/sessions/does-not-exist/continue", json={"supplement": "y"}).status_code == 404

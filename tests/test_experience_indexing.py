"""Feature 1: reinforcement learning from user-approved sessions.

Indexing is exercised with the deterministic HashEmbedder against a tmp
ChromaDB so no model download is involved.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import experience_indexer  # noqa: E402


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Redirect ledger/fine-tune/feedback/chroma into tmp_path."""
    monkeypatch.setattr(experience_indexer, "_LEDGER", tmp_path / "experiences" / "reinforcement_learning.md")
    monkeypatch.setattr(experience_indexer, "_FINE_TUNE_DIR", tmp_path / "experiences" / "fine_tune")
    monkeypatch.setattr(experience_indexer, "_FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(experience_indexer, "chroma_dir", lambda: tmp_path / "chroma")
    monkeypatch.setattr(experience_indexer, "_default_embedder", lambda: experience_indexer.HashEmbedder())
    monkeypatch.setenv("FEEDBACK_ENABLED", "true")
    return tmp_path


def _fake_session(tmp_path):
    session = tmp_path / "sess-TEST"
    session.mkdir()
    spec = "# Warehouse Spec\n\n## Functional Requirements\n" + "\n".join(
        f"FR-{i:02d} The system shall track pallet {i} with an audit trail and a source note."
        for i in range(12)
    )
    (session / "functional_specification.md").write_text(spec, encoding="utf-8")
    (session / "process_diagram.mmd").write_text("graph TB\n  A --> B\n", encoding="utf-8")
    pairs = [
        {"speaker": "interviewer", "message": "What is the SLA?", "subject": "ops", "q_index": 0},
        {"speaker": "user", "message": "Four hours end to end.", "subject": "ops", "q_index": 0},
        {"speaker": "interviewer", "message": "Who approves exceptions?", "subject": "ops", "q_index": 1},
        {"speaker": "user", "message": "The shift supervisor.", "subject": "ops", "q_index": 1},
        {"speaker": "interviewer", "message": "unanswered?", "subject": "ops", "q_index": 2},
    ]
    (session / "interview.jsonl").write_text(
        "\n".join(json.dumps(p) for p in pairs), encoding="utf-8"
    )
    return session


def test_session_documents_include_spec_diagram_and_answered_qa(sandbox):
    session = _fake_session(sandbox)
    docs = experience_indexer.session_documents(session, "sess-TEST", "warehouse spec")
    sources = {meta["source_file"] for _, meta in docs}
    assert "functional_specification.md" in sources
    assert "process_diagram.mmd" in sources
    qa = [text for text, meta in docs if meta["source_file"] == "interview.jsonl"]
    assert len(qa) == 2  # the third pair has no answer and is dropped
    assert all(text.startswith("Q:") for text in qa)


def test_indexing_is_idempotent(sandbox):
    session = _fake_session(sandbox)
    first = experience_indexer.index_approved_deliverables(session, "sess-TEST", "warehouse spec")
    second = experience_indexer.index_approved_deliverables(session, "sess-TEST", "warehouse spec")
    assert first["indexed"] == second["indexed"]
    import chromadb

    collection = chromadb.PersistentClient(path=str(experience_indexer.chroma_dir())).get_collection(
        "approved_experiences"
    )
    assert collection.count() == first["indexed"]


def test_happy_feedback_writes_ledger_fine_tune_and_rag(sandbox):
    session = _fake_session(sandbox)
    result = experience_indexer.process_feedback(
        session, "sess-TEST", "warehouse spec", True, "excellent work"
    )
    assert result["action"] == "indexed" and result["indexed"] > 0
    ledger = sandbox / "experiences" / "reinforcement_learning.md"
    assert ledger.is_file() and "sess-TEST" in ledger.read_text(encoding="utf-8")
    fine_tune = sandbox / "experiences" / "fine_tune" / "sess-TEST.jsonl"
    example = json.loads(fine_tune.read_text(encoding="utf-8"))
    assert "The system shall track pallet 0" in example["output"]
    assert "warehouse spec" in example["instruction"]


def test_unhappy_feedback_stores_critique_and_indexes_nothing(sandbox):
    session = _fake_session(sandbox)
    result = experience_indexer.process_feedback(
        session, "sess-TEST", "warehouse spec", False, "tables overflow the page"
    )
    assert result["action"] == "feedback_saved"
    md = sandbox / "feedback" / "sess-TEST.md"
    assert "tables overflow the page" in md.read_text(encoding="utf-8")
    payload = json.loads((sandbox / "feedback" / "sess-TEST.json").read_text(encoding="utf-8"))
    assert payload["satisfied"] is False
    import chromadb

    with pytest.raises(Exception):
        # The approved collection must not even exist when nothing was approved.
        chromadb.PersistentClient(path=str(experience_indexer.chroma_dir())).get_collection(
            "approved_experiences"
        )
    assert not (sandbox / "experiences" / "reinforcement_learning.md").exists()


def test_disabled_flag_short_circuits_everything(sandbox, monkeypatch):
    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    session = _fake_session(sandbox)
    assert experience_indexer.process_feedback(session, "sess-TEST", "t", True, "") == {"action": "disabled"}
    assert not (sandbox / "feedback").exists()
    assert not (sandbox / "experiences").exists()


def test_silence_is_not_satisfaction(sandbox):
    # The server never infers happiness: only an explicit satisfied=True indexes.
    session = _fake_session(sandbox)
    result = experience_indexer.process_feedback(session, "sess-TEST", "t", False, "")
    assert result["action"] == "feedback_saved"
    import chromadb

    with pytest.raises(Exception):
        chromadb.PersistentClient(path=str(experience_indexer.chroma_dir())).get_collection(
            "approved_experiences"
        )

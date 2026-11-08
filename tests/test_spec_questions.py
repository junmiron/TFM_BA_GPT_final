"""Pending-question dialog for existing sessions: questions come from the
finished spec's open items, not from a hardcoded empty list."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from lib import spec_questions
from server import api

SAMPLE_SPEC = Path(__file__).resolve().parent.parent / "examples" / "sample_session" / "functional_specification.md"


def test_sample_spec_yields_real_questions():
    questions = spec_questions.extract_open_questions(SAMPLE_SPEC.read_text(encoding="utf-8"))
    assert questions, "the sample spec has an Open Items section; extraction must find it"
    titles = {t for t, _ in questions}
    assert "Staff permission boundaries" in titles
    assert "Payment timing" in titles
    # Each open item appears once even though it lives in both the prose list
    # and the assumptions table.
    assert len(titles) == len(questions)
    assert len(questions) <= spec_questions._MAX_QUESTIONS


def test_answered_items_are_filtered_by_supplements(tmp_path):
    spec = tmp_path / "functional_specification.md"
    spec.write_text(
        "## 14. Open Items Requiring Confirmation\n"
        "1. **Payment timing.** Default is weekly settlement. Confirm or amend.\n"
        "2. **Audit trail length.** Default 12 months. Confirm or amend.\n",
        encoding="utf-8",
    )
    supplements = tmp_path / "supplements.jsonl"
    supplements.write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00", "supplement_text": "Payment timing is fine as weekly."}) + "\n",
        encoding="utf-8",
    )
    pending = spec_questions.pending_questions(tmp_path)
    assert len(pending) == 1
    assert "Audit trail length" in pending[0]


def test_decision_table_and_owner_paragraphs_are_sources(tmp_path):
    spec = tmp_path / "functional_specification.md"
    spec.write_text(
        "## 10. Revised Assumptions, Dependencies and Risks\n"
        "| # | Assumption or Dependency | Default Assumption Adopted | Decision Required |\n"
        "|---|---|---|---|\n"
        "| 1 | Staffing levels for v1 pilot | 2 shop staff for pilot phase. | Confirm or amend | \n\n"
        "## 14. Open Items Requiring Confirmation\n"
        "Confirmation required from Operations Manager: Shift scheduling window.\n",
        encoding="utf-8",
    )
    questions = [q for _, q in spec_questions.extract_open_questions(spec.read_text(encoding="utf-8"))]
    assert len(questions) == 2
    assert any("Staffing levels" in q for q in questions)
    assert any("Shift scheduling window" in q for q in questions)


def test_open_questions_plain_bullets_are_extracted(tmp_path):
    """Specs can use "Open Questions" headings with plain (non-bold) bullets."""
    spec = tmp_path / "functional_specification.md"
    spec.write_text(
        "## 11. Open Questions / Future Considerations (v1 Deferrals)\n"
        "- Whether the mobile app should support limited offline queuing in later versions.\n"
        "- Whether automatic scheduled backups are needed.\n",
        encoding="utf-8",
    )
    questions = spec_questions.pending_questions(tmp_path)
    assert len(questions) == 2
    assert any("offline queuing" in q for q in questions)
    assert any("scheduled backups" in q for q in questions)


def test_no_spec_returns_no_questions(tmp_path):
    assert spec_questions.pending_questions(tmp_path) == []


def test_open_items_table_with_ids_is_extracted(tmp_path):
    """Real specs use "| O1 | item | assumption | needed by |" tables under an
    "Open Items" heading of any level (e.g. "# 7. Open Items ...")."""
    spec = tmp_path / "functional_specification.md"
    spec.write_text(
        "# 7. Open Items Requiring Business Owner Input\n"
        "| # | Open Item | Current assumption | Needed by |\n"
        "|---|---|---|---|\n"
        "| O1 | Home return delivery in v1? | No - customer collection only | Week 2 |\n"
        "| O2 | Refund workflow | Admin approves | Week 3 |\n",
        encoding="utf-8",
    )
    questions = spec_questions.pending_questions(tmp_path)
    assert len(questions) == 2
    assert any("Home return delivery" in q for q in questions)
    assert any("Refund workflow" in q for q in questions)


def test_existing_session_endpoint_reports_pending_questions(monkeypatch, tmp_path):
    """The dialog's data source: GET /api/sessions/{id}/pending-questions for a
    persisted (non-live) session folder."""
    monkeypatch.setattr(api, "CONV_ROOT", tmp_path)
    client = TestClient(api.app)
    session_dir = tmp_path / "sess-old"
    session_dir.mkdir()
    (session_dir / "functional_specification.md").write_text(
        "## 14. Open Items Requiring Confirmation\n"
        "1. **Audit trail length.** Default 12 months. Confirm or amend.\n",
        encoding="utf-8",
    )
    response = client.get("/api/sessions/sess-old/pending-questions")
    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 1
    assert "Audit trail length" in questions[0]


def test_endpoint_on_missing_session_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "CONV_ROOT", tmp_path)
    client = TestClient(api.app)
    response = client.get("/api/sessions/does-not-exist/pending-questions")
    assert response.status_code == 200
    assert response.json()["questions"] == []

"""Routing tests for the simulated-stakeholder interview.
The team routes every interviewer QUESTION through planning_agent before the user
answers, so AutoGen hands input_func the planner's status line. These tests pin the
two helpers that fix that and the async contract of the selector wrapper.
Run with:  python -m pytest -q
"""
import asyncio
import inspect
import sys
from pathlib import Path
from autogen_agentchat.messages import TextMessage
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from agents_tools_helpers import (  # noqa: E402
    INTERVIEWER,
    PLANNING,
    USER,
    WRITER,
    current_round,
    latest_question,
    question_from_coverage,
    question_from_planner,
    question_for_user,
    selector_func,
)
from pipeline import question_aware_selector  # noqa: E402


def _msg(source, content):
    return TextMessage(content=content, source=source)


def test_latest_question_walks_back_over_the_planner_turn():
    history = [
        _msg(INTERVIEWER, "QUESTION: Is v1 offline-capable or does it need a connection?"),
        _msg(PLANNING, "Task state: - interviewer_agent: done - user: pending"),
    ]
    assert latest_question(history) == (
        "QUESTION: Is v1 offline-capable or does it need a connection?"
    )


def test_latest_question_ignores_planner_status():
    assert latest_question([_msg(PLANNING, "Task state: - user: pending")]) == ""


def test_latest_question_survives_repeated_planner_turns():
    """selector_func runs before every turn, so the same question is re-captured each
    time the planner is selected; the run must not lose it or grab an unrelated one."""
    history = [
        _msg(INTERVIEWER, "QUESTION: Is v1 offline-capable or does it need a connection?"),
        _msg(PLANNING, "Task state: - interviewer_agent: done - user: pending"),
        _msg(PLANNING, "Task state: - user: pending"),
    ]
    captured = latest_question(history)
    assert captured == "QUESTION: Is v1 offline-capable or does it need a connection?"
    assert latest_question(history + [_msg(PLANNING, "Task state: - writer: pending")]) == captured
    assert latest_question([_msg(WRITER, "The summary looks complete.")]) == ""


def test_question_for_user_answers_the_question_not_the_planner_status():
    question = "QUESTION: Is v1 offline-capable or does it need a connection?"
    assert question_for_user("Task state: - user: pending", question) == question
    assert question_for_user(question, "QUESTION: stale one") == question
    assert question_for_user("Do you approve the summary?", "") == "Do you approve the summary?"
    assert question_for_user("", "") == "Please describe how this should work."


def test_question_aware_selector_is_async_and_captures_the_question():
    """AutoGen decides sync-vs-async with inspect.iscoroutinefunction when the team is
    built, so a sync wrapper that returns a coroutine aborts the run with 'Selector
    function returned an invalid speaker name'. AutoGen also calls it as
    selector(thread), so the pending store must be closed over rather than bound as the
    first positional argument (that passes the dict as the message list and raises
    KeyError: -1 inside SelectorGroupChat)."""
    pending = {"text": ""}
    selector = question_aware_selector(selector_func, pending)
    assert inspect.iscoroutinefunction(selector), "selector wrapper must be async"
    history = [
        _msg(INTERVIEWER, "QUESTION: Which devices will staff use?"),
        _msg(PLANNING, "Task state: - interviewer_agent: done - user: pending"),
    ]
    speaker = asyncio.run(selector(history))
    assert isinstance(speaker, str), f"selector returned {speaker!r}"
    assert speaker == PLANNING, f"selector chose {speaker}, expected the planner"
    assert pending["text"] == "QUESTION: Which devices will staff use?"


def test_question_aware_selector_passes_through_a_none_route():
    """The wrapper only records the question; it must not invent a speaker when the
    wrapped selector defers to AutoGen's model-based selection (returns None)."""
    async def defer(messages):
        return None
    pending = {"text": ""}
    selector = question_aware_selector(defer, pending)
    assert asyncio.run(selector([_msg(INTERVIEWER, "QUESTION: any?")])) is None
    assert pending["text"] == "QUESTION: any?"


def test_pipeline_wires_the_capture_into_the_selector_and_the_input_func():
    """The two halves have to meet: the selector captures, the input function consumes.
    A sync wrapper or a positional partial breaks the team at construction, so pin the
    exact wiring the live run depends on."""
    source = (PROJECT_ROOT / "lib" / "pipeline.py").read_text(encoding="utf-8")
    assert "selector_func=question_aware_selector(selector_func, pending_question)" in source
    assert 'pending_question.pop("text", "")' in source
    assert "question_for_user(\n                    prompt, pending_question.pop(\"text\", \"\")\n                )" in source


def test_latest_question_does_not_reach_into_a_previous_round():
    """The interviewer's turn in a round is often just a status line. Walking the
    whole history then returns the question from the round before, which is how the
    simulated stakeholder re-answered the intake-volume question three times."""
    history = [
        _msg(INTERVIEWER, "QUESTION: What is the daily intake volume?"),
        _msg(USER, "About 40 orders a day."),
        _msg(INTERVIEWER, "Product Overview asked=1, status=done; KPI asked=1, status=pending"),
        _msg(PLANNING, "1 user : Answer the interviewer's question about measurable success criteria for v1"),
    ]
    assert latest_question(history) == ""
    assert current_round(history)[-1].content.startswith("1 user :")


def test_question_from_planner_recovers_a_status_only_round():
    history = [
        _msg(USER, "About 40 orders a day."),
        _msg(INTERVIEWER, "Product Overview asked=1, status=done; KPI asked=1, status=pending"),
        _msg(PLANNING, "1 user : Answer the interviewer's question about measurable success criteria for v1, such as % of orders tracked via QR"),
    ]
    assert question_from_planner(history) == (
        "QUESTION: measurable success criteria for v1, such as % of orders tracked via QR"
    )


def test_question_from_planner_is_empty_when_the_round_has_nothing():
    assert question_from_planner([_msg(PLANNING, "Task state: - user: pending")]) == ""


def test_coverage_table_becomes_the_next_question():
    """The interviewer often emits only its progress table, so the stakeholder is
    asked about the first subject still open rather than the table itself."""
    history = [
        _msg(USER, "About 40 orders a day."),
        _msg(INTERVIEWER,
            "Product Overview asked=1, status=done KPI & Success Metrics asked=0, status=not started"),
    ]
    question = question_from_coverage(history)
    assert question.startswith("QUESTION:")
    assert "KPI & Success Metrics" in question


def test_status_line_prompt_never_reaches_the_stakeholder():
    status = "Task tracking: - interviewer_agent: pending - user: pending"
    assert question_for_user(status, "") == "Please describe how this should work in your shop."
    assert question_for_user(status, "QUESTION: which devices?") == "QUESTION: which devices?"


def test_latest_question_finds_a_question_after_a_status_table():
    """The interviewer keeps its subject table in the same turn as the question,
    so the question is not at the start of the message."""
    history = [
        _msg(USER, "About 40 orders a day."),
        _msg(
            INTERVIEWER,
            "Product Overview asked=1, status=done\n"
            "User Roles & Personas asked=0, status=not started\n"
            "QUESTION: Which staff roles can scan tags and change status?",
        ),
    ]
    assert latest_question(history) == "QUESTION: Which staff roles can scan tags and change status?"


def test_coverage_table_fills_a_round_with_no_question_text():
    history = [
        _msg(USER, "About 40 orders a day."),
        _msg(INTERVIEWER, "Product Overview asked=1, status=done KPI & Success Metrics asked=0, status=not started"),
        _msg(PLANNING, "Task tracking: - interviewer_agent: pending - user: pending"),
    ]
    assert latest_question(history) == ""
    assert question_from_planner(history) == ""
    question = question_from_coverage(history)
    assert question.startswith("QUESTION:") and "KPI & Success Metrics" in question

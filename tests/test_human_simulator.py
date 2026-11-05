"""The roleplay human lane: answers the live question, falls back safely."""

import asyncio
import os
import sys



_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "test"))

from human_simulator import HumanSimulator, PERSONA, TASK_BRIEF


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeClient:
    """Records the messages it was sent so history threading can be asserted."""

    def __init__(self, content="Mocked stakeholder answer.", raise_on=None):
        self._content = content
        self._raise_on = raise_on
        self.calls = []

    async def create(self, messages):
        self.calls.append(messages)
        if self._raise_on and len(self.calls) >= self._raise_on:
            raise RuntimeError("upstream human lane is down")
        return _FakeResult(self._content)


def _sim(client, brief=TASK_BRIEF):
    return HumanSimulator(client=client, brief=brief)


def test_first_answer_is_grounded_in_the_brief():
    client = _FakeClient()
    sim = _sim(client)

    answer = None
    import asyncio
    answer = asyncio.run(sim.ask("QUESTION: What hurts most today?"))

    assert answer == "Mocked stakeholder answer."
    prompt = client.calls[0]
    assert "human_simulator" in PERSONA or "product owner" in PERSONA
    joined = " ".join(str(m.content) for m in prompt)
    assert "QR" in joined  # brief is carried into the first turn


def test_prior_answers_are_carried_forward():
    client = _FakeClient()
    sim = _sim(client)

    import asyncio
    asyncio.run(sim.ask("QUESTION: How many orders per day?"))
    asyncio.run(sim.ask("QUESTION: Which staff roles exist?"))

    second = client.calls[1]
    joined = " ".join(str(m.content) for m in second)
    assert "Context already established" in joined
    assert "How many orders per day" not in joined  # the question itself, not echoed


def test_upstream_failure_does_not_kill_the_run():
    client = _FakeClient(raise_on=1)
    sim = _sim(client)

    import asyncio
    answer = asyncio.run(sim.ask("QUESTION: Anything about shelving?"))
    assert answer.startswith("(fallback)")


def test_set_brief_grounds_the_first_turn():
    client = _FakeClient()
    sim = _sim(client, brief="")
    sim.set_brief("Build a warehouse pallet tracker.")
    asyncio.run(sim.ask("QUESTION: What is the scope?"))
    joined = " ".join(str(m.content) for m in client.calls[0])
    assert "warehouse pallet tracker" in joined


def test_persona_forbids_meta_commentary():
    assert "role-play" in PERSONA or "role play" in PERSONA
    assert "Do not mention that you are an AI" in PERSONA


def test_task_brief_is_not_empty():
    assert len(TASK_BRIEF) > 100


def test_lib_simulator_imports_the_loader_from_src():
    """`uvicorn server.api:app` does not put src/ on sys.path, so the library
    simulator must import the loader as `src.model_loader`, not bare `model_loader`.
    A bare import makes the simulated stakeholder silently unavailable and the
    web UI hangs waiting for a human answer."""
    from pathlib import Path

    source = Path("lib/human_simulator.py").read_text(encoding="utf-8")
    assert "from src.model_loader import load_model_client" in source
    assert "from model_loader import" not in source

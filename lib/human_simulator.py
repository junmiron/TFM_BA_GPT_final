"""Simulated stakeholder for the interview.

The agent pipeline runs on the local model (Strata/LM Studio); the human side of
the interview is answered on a separate remote lane (opencode-go by default) so
the two halves never compete for the same capacity or a provider's tokens/min
ceiling.

Enable in the app with `SIMULATE_HUMAN=true`; otherwise the interview is answered
by a real person in the Chainlit UI.
"""

from __future__ import annotations

import os
from typing import Optional

from autogen_core.models import SystemMessage, UserMessage


DEFAULT_PERSONA = """You are the product owner of a small business commissioning a
software project. You are not a technical expert, but you know your day-to-day
operations well. Answer the business analyst's question in first person,
concretely and briefly (3-6 sentences or a short bullet list). Give realistic
numbers and examples. Do not mention that you are an AI or that this is a
role-play. Stay consistent with what you have already said.
"""


class HumanSimulator:
    """One round-trip per interview question, against the configured remote lane."""

    def __init__(self, model_name: Optional[str] = None, brief: str = "", client=None) -> None:
        if client is None:
            from model_loader import load_model_client
            client = load_model_client(model_name or os.getenv("HUMAN_MODEL", "opencode"))
        self._client = client
        self._persona = os.getenv("HUMAN_PERSONA", DEFAULT_PERSONA)
        self._brief = brief
        self._history: list[str] = []

    def set_brief(self, brief: str) -> None:
        self._brief = brief

    def reset(self) -> None:
        self._history = []

    async def ask(self, question: str) -> str:
        persona = getattr(self, "_persona", DEFAULT_PERSONA)
        # SystemMessage takes only `content`; passing `source` is silently dropped
        # by pydantic and made the history assertions misleading.
        messages = [SystemMessage(content=persona)]
        brief = getattr(self, "_brief", "")
        history = getattr(self, "_history", [])
        if history:
            prior = "\n".join(f"- {h}" for h in history[-8:])
            content = f"Context already established:\n{prior}\n\n{question}"
        else:
            content = f"{brief}\n\n{question}" if brief else question
        messages.append(UserMessage(content=content, source="interviewer"))

        try:
            result = await self._client.create(messages)
        except Exception as exc:
            # Never let the human lane kill the run: fall back to a neutral
            # answer so the interview can still progress.
            return f"(fallback) {question[:120]} - as described in the brief."

        text = str(result.content).strip()
        if not text:
            return "(fallback) proceed as described in the brief."
        self._history.append(text[:300])
        return text


def build_human_simulator(model_name: Optional[str] = None, brief: str = "") -> HumanSimulator:
    return HumanSimulator(model_name, brief)

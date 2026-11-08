"""Open items in a finished specification that still need stakeholder input.

The spec writer records unconfirmed assumptions in dedicated structures:

* ``## N. Open Items Requiring Confirmation`` - numbered list of items.
* ``Revised Assumptions, Dependencies and Risks`` - a table whose last column
  says what decision is needed ("Confirm or amend", "Provide names...").
* ``Confirmation required from owner: ...`` paragraphs.

``extract_open_questions`` returns ``(title, question)`` pairs, de-duplicated
by title. ``pending_questions`` drops items the user already answered through
the continuation mechanism (supplements.jsonl), so the dialog does not keep
re-asking a question that was already settled.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

# Heading of any level whose text mentions open items/questions, body until the next heading.
_OPEN_SECTION_RE = re.compile(
    r"^#{1,4}\s*[^\n]*(?:[Oo]pen [Ii]tems|[Oo]pen [Qq]uestions)[^\n]*\n(.*?)(?=^#{1,4}\s|^-{3,}$|\Z)",
    re.M | re.S,
)
# Any bullet line in an open-items section: numbered or dash, bold-titled or plain.
_BULLET_RE = re.compile(r"^\s*(?:\d+\.|[-*])\s+(.+)$", re.M)
_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*[:.]?\s*(.*)$")
# Table row with at least three cells: | id | item | detail... |
_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|", re.M)
# "| 3 | Payment timing | Default adopted | Decision needed |"
_DECISION_ROW_RE = re.compile(
    r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", re.M
)
_DECISIONISH_RE = re.compile(r"confirm|provide|name the|decision|validate|ratif|sign-off", re.I)
_OWNER_CONFIRM_RE = re.compile(
    r"Confirmation required from [^\n:]+:\s*(.+?)(?=\n\n|\Z)", re.S
)
_MAX_QUESTIONS = 12


def _norm(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower()).strip().rstrip(".:;?")


def extract_open_questions(md_text: str) -> List[Tuple[str, str]]:
    """Return (title, question) pairs for every open item in the spec."""
    items: List[Tuple[str, str]] = []
    seen = set()

    def add(title: str, question: str) -> None:
        title = re.sub(r"\s+", " ", title.replace("**", "")).strip().rstrip(".:;?")
        key = _norm(title)
        if not key or key in seen or len(key) < 4:
            return
        seen.add(key)
        items.append((title, question.strip()))

    for section in _OPEN_SECTION_RE.finditer(md_text):
        body = section.group(1)
        for bullet in _BULLET_RE.findall(body):
            bold = _BOLD_RE.match(bullet)
            if bold:
                title, detail = bold.group(1), bold.group(2)
                question = f"{title.rstrip('.')}. {detail}".strip() if detail else f"{title.rstrip('.')}?"
            else:
                title = bullet
                question = bullet if bullet.endswith(("?", ".")) else f"{bullet}?"
            add(title, question)
        for first, second, rest in _ROW_RE.findall(body):
            # Skip header rows ("| # | Open Item | ... |") and separator rows.
            if re.fullmatch(r"#|[-\s]+", first):
                continue
            add(second, f"{second}: {rest.replace('|', ' - ')}")

    for title, default, decision in _DECISION_ROW_RE.findall(md_text):
        if not _DECISIONISH_RE.search(decision):
            continue
        add(title, f"{title}: default '{default.rstrip('.')}'. {decision.strip()}")

    for match in _OWNER_CONFIRM_RE.findall(md_text):
        detail = " ".join(match.split())
        add(detail.split(":")[0], f"Confirmation required: {detail}")

    return items[:_MAX_QUESTIONS]


def _supplement_text(session_dir: Path) -> str:
    """All supplements the user fed into this spec, joined for substring checks."""
    supplements = Path(session_dir) / "supplements.jsonl"
    if not supplements.is_file():
        return ""
    text = ""
    for line in supplements.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        text += str(record.get("supplement_text", record.get("supplement", ""))) + "\n"
    return text


def pending_questions(session_dir: Path) -> List[str]:
    """Open items still awaiting confirmation, as displayable question strings."""
    session_dir = Path(session_dir)
    spec = session_dir / "functional_specification.md"
    if not spec.is_file():
        return []
    items = extract_open_questions(spec.read_text(encoding="utf-8", errors="ignore"))
    answered = _supplement_text(session_dir).lower()
    return [
        question
        for title, question in items
        if _norm(title) not in answered
    ]

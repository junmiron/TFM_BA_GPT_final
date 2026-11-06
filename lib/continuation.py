"""Session continuation (Feature 3): add new information to an existing
functional specification without re-running the whole interview.

The supplement is appended to the spec by the writer model; a deterministic
guard refuses a rewrite that drops existing headings and falls back to a
plain "Addendum" section instead. The spec version is bumped and the
deliverables (PDF/HTML/MD) are re-rendered in place.
"""

import inspect
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

_VERSION_ROW = re.compile(r"^\|\s*Version\s*\|\s*(v?\d+(?:\.\d+)?)\s*(.*?)\|\s*$", re.M | re.I)
_VERSION_BOLD = re.compile(r"\*\*Version:\*\*\s*(v?\d+(?:\.\d+)?)", re.I)


def _bump_version(text: str) -> str:
    """v1.2 -> v1.3, v1 -> v1.1. Adds a metadata row if none exists."""
    def _bump(value: str) -> str:
        parts = value.lstrip("vV").split(".")
        if len(parts) == 1:
            return f"v{parts[0]}.1"
        return f"v{parts[0]}.{int(parts[1]) + 1}"

    match = _VERSION_ROW.search(text)
    if match:
        rest = match.group(2).strip()
        bumped = _bump(match.group(1))
        return (text[: match.start()] + f"| Version | {bumped}{' ' + rest if rest else ''} |" + text[match.end():])
    match = _VERSION_BOLD.search(text)
    if match:
        return text[: match.start()] + f"**Version:** {_bump(match.group(1))}" + text[match.end():]
    lines = text.splitlines()
    insert_at = 1
    for i, line in enumerate(lines):
        if line.startswith("# "):
            insert_at = i + 1
            break
    lines.insert(insert_at, f"**Version:** v1.1")
    return "\n".join(lines)


def _headings(text: str) -> set:
    return {h.strip() for h in re.findall(r"^#{1,3} .+$", text, re.M)}


async def _model_complete(prompt: str) -> str:
    from autogen_core.models import SystemMessage, UserMessage
    from src.model_loader import load_model_client

    client = load_model_client(os.getenv("MODEL_CLIENT", "openai"))
    response = await client.create(
        [
            SystemMessage(
                content=(
                    "You are a meticulous business analyst maintaining a functional "
                    "specification. Integrate the new information into the right "
                    "sections, keep every existing section intact, and return the "
                    "complete updated Markdown document only."
                )
            ),
            UserMessage(content=prompt, source="continuation"),
        ]
    )
    return str(response.content)


async def apply_supplement(session_dir: Path, supplement: str,
                           complete: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Merge a supplement into the spec, bump the version, re-render deliverables."""
    session_dir = Path(session_dir)
    spec_path = session_dir / "functional_specification.md"
    if not spec_path.is_file():
        raise FileNotFoundError(f"No functional_specification.md in {session_dir}")

    supplement = supplement.strip()
    if not supplement:
        raise ValueError("supplement is empty")

    # Audit trail first - supplements are never lost even if the merge fails.
    with (session_dir / "supplements.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(
            {"date": datetime.now(timezone.utc).isoformat(), "supplement": supplement},
            ensure_ascii=False,
        ) + "\n")

    spec = spec_path.read_text(encoding="utf-8", errors="ignore")
    func = complete or _model_complete
    try:
        result = func(
            f"CURRENT SPECIFICATION:\n\n{spec}\n\n"
            f"NEW INFORMATION FROM THE CLIENT:\n\n{supplement}\n\n"
            "Return the complete updated specification as Markdown."
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        logger.warning("model merge failed, using deterministic addendum: %s", exc)
        result = ""
    updated = str(result or "").strip()

    original_headings = _headings(spec)
    valid = (
        updated
        and len(updated) >= len(spec) * 0.5
        and original_headings.issubset(_headings(updated))
    )
    if not valid:
        # Deterministic fallback: never lose the original content.
        updated = (
            spec.rstrip()
            + "\n\n## Addendum (client supplement)\n\n"
            + supplement
            + "\n"
        )

    updated = _bump_version(updated)
    spec_path.write_text(updated, encoding="utf-8")

    from lib import agents_tools_helpers

    render = {}
    try:
        render = agents_tools_helpers.finalize_deliverables(str(session_dir))
    except Exception:
        render = {}

    version_match = re.search(r"v\d+(?:\.\d+)?", updated)
    return {
        "version": version_match.group(0) if version_match else "updated",
        "merged": "model" if valid else "fallback",
        "pdf": render.get("pdf"),
        "html": render.get("html"),
        "supplements_file": str(session_dir / "supplements.jsonl"),
    }

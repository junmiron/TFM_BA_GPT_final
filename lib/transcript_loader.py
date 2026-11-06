"""Meeting-transcript ingestion (Feature 4).

Turns an uploaded transcript into plain text that seeds a session: the
spec is written from what the meeting actually said, and the interview
only fills the gaps. Supported formats: .txt, .md, .docx, .pdf, .vtt, .srt.
"""

import re
from pathlib import Path
from typing import Union

SUPPORTED_EXTENSIONS = {".txt", ".md", ".vtt", ".srt", ".docx", ".pdf"}

_VTT_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d{3})?\s+-->.*$", re.M)
_CUE_INDEX = re.compile(r"^\d+$", re.M)


def _strip_captions(text: str) -> str:
    """Drop VTT/SRT headers, cue numbers and timestamp lines, keep speech."""
    text = re.sub(r"^WEBVTT.*$", "", text, flags=re.M)
    text = _VTT_TIME.sub("", text)
    text = _CUE_INDEX.sub("", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def extract_trans_text(name: str, data: Union[bytes, str]) -> str:
    """Extract readable text from transcript bytes for a given filename."""
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported transcript format {ext or '(none)'}; "
            "use one of: " + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    if isinstance(data, bytes):
        if ext == ".pdf":
            from lib.rag_helpers import _read_pdf
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
                path = tmp.name
            try:
                pages = _read_pdf(path)
            finally:
                Path(path).unlink(missing_ok=True)
            return "\n\n".join(pages).strip()
        if ext == ".docx":
            from lib.rag_helpers import _read_docx
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(data)
                path = tmp.name
            try:
                lines = _read_docx(path)
            finally:
                Path(path).unlink(missing_ok=True)
            return "\n".join(lines).strip()
        text = data.decode("utf-8", errors="ignore")
    else:
        text = data

    if ext in (".vtt", ".srt"):
        text = _strip_captions(text)
    return text.strip()


def build_task_with_transcript(task: str, transcript: str, max_chars: int = 20000) -> str:
    """Compose the run task so the team treats the transcript as the source."""
    task = (task or "").strip() or "Functional specification from meeting transcript"
    excerpt = transcript[:max_chars]
    truncated = len(transcript) > max_chars
    note = (
        "\n\nMEETING TRANSCRIPT (primary source for this specification):\n"
        + excerpt
        + ("\n[transcript truncated - the full file is saved in the session folder as source_transcript.txt]"
           if truncated else "")
        + "\n\nUse the transcript as the source of truth: pull requirements, decisions "
        "and process steps directly from it. Interview the stakeholder only to fill "
        "gaps the transcript does not cover; do not re-ask what the transcript already "
        "answers."
    )
    return task + note

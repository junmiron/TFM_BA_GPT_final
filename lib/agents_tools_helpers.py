"""
This module provides agent tools.
"""
import os
import json
import uuid
import time
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union, Sequence, Tuple
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage


DEFAULT_JSONL_PATH = "../conversation/interview.jsonl"
DEFAULT_MD_PATH = "../conversation/final_summary.md"
DEFAULT_MD_SPEC_PATH = "../conversation/functional_specification.md"
DEFAULT_MERMAID_PATH = "../conversation/process_diagram.mmd"

ISO8601 = "%Y-%m-%dT%H:%M:%S.%fZ"

PLANNING = "planning_agent"
INTERVIEWER = "interviewer_agent"
USER = "user"

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime(ISO8601)


class FileLock:
    """
    Cross-platform lock using a sidecar .lock file created with O_CREAT|O_EXCL.
    Prevents concurrent writers from clobbering each other.
    """
    def __init__(self, target_path: Path, poll_interval: float = 0.05) -> None:
        self.lock_path = Path(str(target_path) + ".lock")
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None

    def acquire(self, timeout: float = 5.0) -> None:
        start = time.time()
        while True:
            try:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self._fd, str(uuid.uuid4()).encode("utf-8"))
                return
            except FileExistsError:
                if (time.time() - start) >= timeout:
                    raise TimeoutError(f"Could not acquire lock: {self.lock_path}")
                time.sleep(self.poll_interval)

    def release(self) -> None:
        try:
            if self._fd is not None:
                os.close(self._fd)
            if self.lock_path.exists():
                os.unlink(self.lock_path)
        finally:
            self._fd = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl_lines(path: Path, lines: List[str]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for line in lines:
            if not line.endswith("\n"):
                line += "\n"
            f.write(line)


def _with_timestamps(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stamped = []
    now = _now_iso()
    for r in records:
        r2 = dict(r)
        if "timestamp" not in r2 or not r2["timestamp"]:
            r2["timestamp"] = now
        stamped.append(r2)
    return stamped


def save_records(
    path: str | Path,
    records: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    retries: int = 2,
    backoff_seconds: float = 0.2,
) -> str:
    """
    Append a list of records to a JSONL file atomically with a lock and retries.
    If session_id is provided, a metadata header is prepended before the records.
    """
    p = Path(path)
    _ensure_parent_dir(p)
    stamped = _with_timestamps(records)

    lines = []
    if session_id:
        meta = {"_meta": {"session_id": session_id, "ts": _now_iso(), "n_records": len(stamped)}}
        lines.append(json.dumps(meta, ensure_ascii=False))

    for rec in stamped:
        lines.append(json.dumps(rec, ensure_ascii=False))

    attempt = 0
    while True:
        try:
            with FileLock(p):
                _append_jsonl_lines(p, lines)
            return f"Wrote {len(stamped)} record(s) to {p}"
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(backoff_seconds * attempt)


def save_conversation_pair(
    path: str | Path,
    question_text: str,
    answer_text: str,
    subject: str,
    q_index: int,
    session_id: Optional[str] = None,
    extra_question_fields: Optional[Dict[str, Any]] = None,
    extra_answer_fields: Optional[Dict[str, Any]] = None,
    retries: int = 2,
    backoff_seconds: float = 0.2,
) -> None:
    """
    Convenience wrapper to log a Q&A pair with a shared q_index.
    Writes exactly two JSONL records: one for the interviewer, one for the user.
    """
    q = {
        "speaker": "interviewer",
        "message": question_text,
        "subject": subject,
        "q_index": int(q_index),
    }
    a = {
        "speaker": "user",
        "message": answer_text,
        "subject": subject,
        "q_index": int(q_index),
    }
    if extra_question_fields:
        q.update(extra_question_fields)
    if extra_answer_fields:
        a.update(extra_answer_fields)

    save_records(
        path=path,
        records=[q, a],
        session_id=session_id,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )


# --- replace the function signature + a tiny return tweak ---
def save_conversation_to_jsonl(
    speaker_or_records: Union[List[Dict[str, Any]], str],  # ✅ add type
    message: Optional[str] = None,                         # ✅ make Optional[str]
    file_path: str = DEFAULT_JSONL_PATH,
    *,
    subject: Optional[str] = None,                         # ✅ add Optional
    q_index: Optional[int] = None,                         # ✅ add Optional
    session_id: Optional[str] = None                       # ✅ add Optional
) -> str:                                                  # ✅ explicit return type
    """
    Saves either:
    1) A Q&A pair (interviewer + user) in one atomic JSONL write, OR
    2) A generic list of records.
    """
    try:
        path = Path(file_path)

        # Case 1: Already a list of records
        if isinstance(speaker_or_records, list):
            save_records(path, speaker_or_records, session_id=session_id)
            return f"Saved {len(speaker_or_records)} record(s) to {file_path}"  # ✅ always return str

        # Case 2: Single speaker/message (buffer Q until A, then write both)
        if not hasattr(save_conversation_to_jsonl, "_pending_pair"):
            save_conversation_to_jsonl._pending_pair = {}

        pair_buffer = save_conversation_to_jsonl._pending_pair
        key = (subject, q_index, session_id)

        if speaker_or_records == "interviewer":
            pair_buffer[key] = {
                "interviewer": {
                    "speaker": "interviewer",
                    "message": message,
                    "subject": subject,
                    "q_index": q_index,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            return f"Stored interviewer question for subject={subject}, q_index={q_index}"

        elif speaker_or_records == "user":
            if key not in pair_buffer or "interviewer" not in pair_buffer[key]:
                return "Error: No matching interviewer question stored for this answer."

            interviewer_rec = pair_buffer[key]["interviewer"]
            user_rec = {
                "speaker": "user",
                "message": message,
                "subject": subject,
                "q_index": q_index,
                "timestamp": datetime.utcnow().isoformat()
            }

            save_records(path, [interviewer_rec, user_rec], session_id=session_id)
            del pair_buffer[key]
            return f"Saved Q&A pair for subject={subject}, q_index={q_index} to {file_path}"

        else:
            return "Error: speaker_or_records must be 'interviewer', 'user', or a list of records."

    except Exception as e:
        return f"Error saving conversation: {e}"



def write_md_file_tool(content: str, file_path: str = DEFAULT_MD_SPEC_PATH) -> str:
    """
    Writes the functional specification to a Markdown file.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Markdown spec successfully written to {file_path}"
    except Exception as e:
        return f"Error writing Markdown spec: {e}"


def read_md_file_tool(file_path: str = DEFAULT_MD_SPEC_PATH) -> str:
    """
    Reads the entire content of a Markdown file and returns it as a string.

    Args:
        file_path (str): Optional path to the Markdown spec (defaults to DEFAULT_MD_SPEC_PATH).

    Returns:
        str: The full text content of the Markdown file, or an error message.
    """
    import os
    try:
        if not os.path.exists(file_path):
            return f"Error: Markdown file not found at {file_path}"

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content if content.strip() else "Markdown file is empty — no readable text found."
    except Exception as e:
        return f"Error reading Markdown file: {e}"


def write_mermaid_to_file_tool(mermaid_code: str, file_path: str = DEFAULT_MERMAID_PATH) -> str:
    """
    Writes Mermaid diagram code to a .mmd file with proper formatting.

    Args:
        mermaid_code (str): The Mermaid syntax/code to write.
        file_path (str): Optional path for saving. Defaults to DEFAULT_MERMAID_PATH.

    Returns:
        str: Confirmation or error message.
    """

    try:
        # Ensure the folder exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Validate file extension
        if not file_path.endswith('.mmd'):
            return "Error: Filename must end with '.mmd'"

        # Write the Mermaid code into a fenced code block
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write("```mermaid\n")
            file.write(mermaid_code)
            file.write("\n```")

        return f"Mermaid diagram successfully written to {file_path}"
    except Exception as e:
        return f"Error writing Mermaid file: {e}"


# ---- Constants (ensure defined once) ----
PLANNING = "planning_agent"
INTERVIEWER = "interviewer_agent"
USER = "user"
SUMMARIZER = "summarizer_agent"
WRITER = "functional_spec_writer_agent"
CHECKER = "functional_spec_checker_agent"
DIAGRAM = "diagram_creator_agent"
MERMAID = "mermaid_code_reviewer_agent"
TERMINATE = "terminate_agent"

READY_TOKEN = re.compile(r"^\s*\*{0,2}READY\*{0,2}\s*$", re.I)
QUESTION_PREFIX = "QUESTION:"
STATUS_PREFIX = "STATUS:"

ASSIGNMENT_MARKER = re.compile(
    r'^\[ASSIGNMENT\]\s+agent=(?P<agent>[a-z_]+)\s+task="[^"]*"\s+awaiting_user_reply=(?P<await>true|false)\s*$',
    re.M
)

def _to_text(content: Any) -> str:
    """
    Normalize message content to a single string.
    Handles:
      - str
      - list[str]
      - list[dict|objects] (tries 'text' or 'content' fields)
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict):
                # common structured part
                if "text" in c and isinstance(c["text"], str):
                    parts.append(c["text"])
                elif "content" in c and isinstance(c["content"], str):
                    parts.append(c["content"])
            else:
                # fallback: try .text or .content attr
                txt = getattr(c, "text", None) or getattr(c, "content", None)
                if isinstance(txt, str):
                    parts.append(txt)
        return "\n".join(parts)
    # fallback: attempt str()
    try:
        return str(content)
    except Exception:
        return ""

def _src(m): 
    return getattr(m, "source", getattr(m, "sender", None))

def _txt(m) -> str:
    raw = getattr(m, "content", "")
    return _to_text(raw).strip()

def _last(messages: Sequence):
    if not messages:
        return None, ""
    return _src(messages[-1]), _txt(messages[-1])

def _latest_assignment(messages: Sequence):
    for m in reversed(messages):
        if _src(m) == PLANNING:
            mt = ASSIGNMENT_MARKER.search(_txt(m))
            if mt:
                return mt.group("agent"), (mt.group("await") == "true")
    return None, None

def _agent_has_ready(messages: Sequence, agent: str) -> bool:
    for m in reversed(messages):
        if _src(m) == agent:
            if READY_TOKEN.match(_txt(m)):
                return True
    return False

def _phase(messages: Sequence) -> int:
    # 0 interviewing; 1 summarizing; 2 writing; 3+ post-writer linear
    if not _agent_has_ready(messages, INTERVIEWER):
        return 0
    if not _agent_has_ready(messages, SUMMARIZER):
        return 1
    if not _agent_has_ready(messages, WRITER):
        return 2
    return 3

def _prev_agent_question(messages: Sequence, agent: str) -> bool:
    for m in reversed(messages):
        s = _src(m)
        if s == agent:
            return _txt(m).startswith(QUESTION_PREFIX)
    return False

def _is_question(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if t.lower().startswith("question:"):
        return True
    # Be forgiving if the agent forgot the prefix but clearly asks a question
    if t.endswith("?") and len(t) < 400:  # heuristic to avoid long bodies
        return True
    return False


def _latest_assignment_from_last_planner(messages: Sequence) -> tuple[str | None, bool | None]:
    # Return assignment from the most recent planning_agent message only (if present)
    for m in reversed(messages):
        if _src(m) == PLANNING:
            mt = ASSIGNMENT_MARKER.search(_txt(m))
            if mt:
                return mt.group("agent"), (mt.group("await") == "true")
            break
    return None, None


async def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]):
    """
    Strict, planner-gated selector with robust interview/summarizer loops:
    - Always let planning_agent assign before any role switch.
    - Obey explicit [ASSIGNMENT] markers from planning_agent.
    - After any 'QUESTION:' to the user, pick planning_agent next (so it assigns 'user').
    - After a user reply, pick planning_agent next (so it assigns interviewer to process/save).
    - After any **READY**, pick planning_agent to assign the next task.
    - Handle checker 'NEEDS_INFO' by routing back to planning_agent.
    """
    if not messages:
        return PLANNING

    last_src, last_txt = _last(messages)

    # If the last message is from planner and includes a valid assignment, follow it strictly.
    if last_src == PLANNING:
        ag, awaiting = _latest_assignment_from_last_planner(messages)
        if ag:
            return ag
        # If planner didn't provide a valid marker, keep the floor to planner until it does.
        return PLANNING

    # USER messages must always be followed by planner for routing next steps.
    if last_src == USER:
        return PLANNING

    # INTERVIEWER loop: after QUESTION -> planner assigns user; after READY -> planner
    if last_src == INTERVIEWER:
        if READY_TOKEN.match(last_txt):
            return PLANNING
        if _is_question(last_txt):
            return PLANNING
        # Default: keep planner in control between interviewer turns
        return PLANNING

    # SUMMARIZER loop: after QUESTION (approval) -> planner (it will assign interviewer/user as needed)
    if last_src == SUMMARIZER:
        if READY_TOKEN.match(last_txt):
            return PLANNING
        if _is_question(last_txt):
            return PLANNING
        return PLANNING

    # WRITER: after READY -> planner; otherwise planner re-assigns until READY
    if last_src == WRITER:
        if READY_TOKEN.match(last_txt):
            return PLANNING
        return PLANNING

    # CHECKER: if NEEDS_INFO -> planner (to send interviewer loop); READY -> planner
    if last_src == CHECKER:
        if "NEEDS_INFO" in last_txt:
            return PLANNING
        if READY_TOKEN.match(last_txt):
            return PLANNING
        return PLANNING

    # DIAGRAM and MERMAID reviewer: READY -> planner; otherwise planner keeps assigning next step
    if last_src == DIAGRAM:
        if READY_TOKEN.match(last_txt):
            return PLANNING
        return PLANNING

    if last_src == MERMAID:
        # The reviewer says "Diagram code complete" then READY; always hand control to planner
        return PLANNING if READY_TOKEN.match(last_txt) or True else PLANNING

    # TERMINATE: nothing else to pick; but return planner to finalize loop if needed
    if last_src == TERMINATE:
        return PLANNING

    # Fallback: always give control to planner
    return PLANNING

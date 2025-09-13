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


VALID_AGENT_NAMES = {
    "planning_agent",
    "interviewer_agent",
    "summarizer_agent",
    "functional_spec_writer_agent",
    "functional_spec_checker_agent",
    "diagram_creator_agent",
    "mermaid_code_reviewer_agent",
    "terminate_agent",
    USER,
}

ASSIGNMENT_RE = re.compile(
    r"""(?mx)            # multiline, verbose
    ^\s*                 # start of line, optional spaces
    (?P<num>\d+)\.?      # leading number with optional dot (1 or 1.)
    \s+                  # spaces
    (?P<agent>[a-z_]+)   # agent name
    \s*:\s*              # colon with spaces
    (?P<task>.+?)        # task text (non-greedy)
    \s*$                 # end of line
    """
)

def _src_txt(m: BaseAgentEvent | BaseChatMessage) -> Tuple[Optional[str], str]:
    src = getattr(m, "source", None) or getattr(m, "name", None)
    txt = getattr(m, "text", None) or getattr(m, "content", None) or ""
    if isinstance(txt, list):
        txt = "\n".join(str(t) for t in txt if t)
    return src, str(txt)

def _last(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> Tuple[Optional[str], str]:
    if not messages:
        return None, ""
    return _src_txt(messages[-1])

def _last_from(messages, agent_name: str) -> Optional[str]:
    for m in reversed(messages):
        src, txt = _src_txt(m)
        if src == agent_name:
            return txt
    return None

def _parse_single_assignment(text: Optional[str]) -> Optional[str]:
    """
    Return the assigned agent IF there is exactly one well-formed assignment line,
    and the agent name is valid. Otherwise return None.
    """
    if not text:
        return None
    matches = list(ASSIGNMENT_RE.finditer(text))
    if len(matches) != 1:
        return None
    agent = matches[0].group("agent")
    return agent if agent in VALID_AGENT_NAMES else None


# --- add near other globals ---
AWAIT_RE = re.compile(r"awaiting[_\s]*user[_\s]*reply\s*=\s*(true|1)\b", re.I)
APPROVE_TOKEN = re.compile(r"\bAPPROVE SUMMARY\b", re.I)

def _last_n_src_txt(messages, n: int = 8):
    for m in reversed(messages[-n:]):
        yield _src_txt(m)

# --- replace selector_func with the following ---
async def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> Optional[str]:
    # If no history, start with planner
    if not messages:
        return PLANNING

    last_src, last_txt = _last(messages)
    last_interviewer_txt = _last_from(messages, INTERVIEWER)
    last_planner_txt = _last_from(messages, PLANNING)  # re-enable

    
    # 1) If planner indicates awaiting user anywhere in the recent tail → USER
    for src, txt in _last_n_src_txt(messages, n=8):
        # accept both planner chunks and echoed [ASSIGNMENT] text
        if AWAIT_RE.search(txt or ""):
            return USER

    # 2) Any agent showing a QUESTION: → USER
    if (last_txt or "").strip().startswith("QUESTION:"):
        return USER

    # 3) interviewer asked a question → USER (kept for clarity/intent)
    if last_src == INTERVIEWER and (last_txt or "").strip().startswith("QUESTION:"):
        return USER

    # 4) user replied to interviewer’s question → back to interviewer
    if last_src == USER and last_interviewer_txt and "QUESTION:" in (last_interviewer_txt or ""):
        return INTERVIEWER

    # 5) summarizer asked for approval (contains APPROVE SUMMARY in its *own* text)
    #    unless user already approved exactly, force USER
    if last_src == "summarizer_agent" and APPROVE_TOKEN.search(last_txt or ""):
        last_user_txt = _last_from(messages, USER)
        if not (last_user_txt and re.fullmatch(r"\s*APPROVE SUMMARY\s*", last_user_txt, re.I)):
            return USER

    # 6) user approved exactly → give summarizer the turn to emit READY
    if last_src == USER and re.fullmatch(r"\s*APPROVE SUMMARY\s*", last_txt or "", re.I):
        return "summarizer_agent"

    # 7) any agent signaled READY → go to planner to assign next task
    if re.search(r"\bREADY\b", last_txt or "", re.I):
        return PLANNING
    
    # 8) Planner explicit single assignment → obey immediately
    assigned_agent = _parse_single_assignment(last_planner_txt)
    if assigned_agent:
        return assigned_agent

    # 9) otherwise, let the model choose
    return None

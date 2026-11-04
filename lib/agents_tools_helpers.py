"""
This module provides agent tools.
"""
import os
import json
import shutil
import uuid
import time
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union, Sequence, Tuple
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- session-scoped outputs ---------------------------------------------------
# Every run writes its deliverables into conversation/<SESSION_ID>/ so runs
# never clobber or read each other's files. The session id is set once at
# workflow start (set_session) and every tool default resolves through it.
_ACTIVE_SESSION: Optional[str] = None


def set_session(session_id: str) -> str:
    """Set the active session id (used by all tool default paths)."""
    global _ACTIVE_SESSION
    _ACTIVE_SESSION = session_id
    _ensure_parent_dir(_PROJECT_ROOT / "conversation" / session_id)
    return session_id


def get_session() -> Optional[str]:
    return _ACTIVE_SESSION


def _session_dir() -> Path:
    if _ACTIVE_SESSION:
        return (_PROJECT_ROOT / "conversation" / _ACTIVE_SESSION).resolve()
    return (_PROJECT_ROOT / "conversation").resolve()


def _normalize_project_relative(p: str | Path) -> Path:
    """Resolve conversation files relative to the project root, not CWD.

    Robust to the Linux/Windows host mismatch that caused the "writes land
    somewhere the reader never looks" bug: an agent may pass an absolute path
    copied from another OS (e.g. ``D:\\Code\\...\\conversation\\spec.md``) or a
    ``project_root/...`` prefix. Whenever the path contains a ``conversation``
    segment we re-anchor it to this project's ``conversation/`` folder, then
    redirect flat files into the active session subfolder so per-run outputs
    never collide with a previous run's files.
    """
    # Convert any Windows-style separators to POSIX so the tail-split works
    # regardless of host OS.
    if isinstance(p, Path):
        if p.is_absolute():
            p_str = str(p)
        else:
            p_str = str(p)
    else:
        p_str = str(p)
    p_str = p_str.replace("\\", "/")

    # Re-anchor any path that references the conversation folder.
    if "conversation" in p_str:
        tail = p_str.split("conversation", 1)[1].lstrip("/")
        conv_root = (_PROJECT_ROOT / "conversation").resolve()
        resolved = (conv_root / tail).resolve() if tail else conv_root
    else:
        # Normalize common relative prefixes used in YAML/notebook.
        if p_str.startswith("../"):
            p_str = p_str[3:]
        elif p_str.startswith("./"):
            p_str = p_str[2:]
        if isinstance(p, Path) and p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (_PROJECT_ROOT / p_str).resolve()

    # Redirect flat conversation files into the active session folder.
    if _ACTIVE_SESSION:
        conv_root = (_PROJECT_ROOT / "conversation").resolve()
        try:
            rel = resolved.relative_to(conv_root)
        except ValueError:
            return resolved
        # Already session-scoped: the agent passed a path such as
        # conversation/<SESSION_ID> or conversation/<SESSION_ID>/foo.mmd from
        # get_session_dir_tool. Redirecting that onto _session_dir() would
        # create conversation/<SESSION_ID>/<SESSION_ID>/ and orphan the file.
        if rel.parts and rel.parts[0] == _ACTIVE_SESSION:
            return resolved
        # rel is like 'functional_specification.md' (not already session-scoped)
        if len(rel.parts) == 1:
            return (_session_dir() / rel.parts[0]).resolve()
    return resolved


def default_jsonl_path() -> str:
    return str((_session_dir() / "interview.jsonl").resolve())


def default_spec_path() -> str:
    return str((_session_dir() / "functional_specification.md").resolve())


def default_mermaid_path() -> str:
    return str((_session_dir() / "process_diagram.mmd").resolve())


def default_summary_path() -> str:
    return str((_session_dir() / "final_summary.md").resolve())

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
    p = _normalize_project_relative(path)
    _ensure_parent_dir(p)
    stamped = _with_timestamps(records)

    lines = []
    effective_session = _ACTIVE_SESSION or session_id
    if effective_session:
        meta = {"_meta": {"session_id": effective_session, "ts": _now_iso(), "n_records": len(stamped)}}
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
    file_path: Optional[str] = None,
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
        path = _normalize_project_relative(file_path or default_jsonl_path())

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
                    "timestamp": datetime.now(timezone.utc).isoformat()
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
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            save_records(path, [interviewer_rec, user_rec], session_id=session_id)
            del pair_buffer[key]
            return f"Saved Q&A pair for subject={subject}, q_index={q_index} to {file_path}"

        else:
            return "Error: speaker_or_records must be 'interviewer', 'user', or a list of records."

    except Exception as e:
        return f"Error saving conversation: {e}"



def write_md_file_tool(content: str, file_path: Optional[str] = None) -> str:
    """
    Writes the functional specification to a Markdown file (truncates first).
    """
    try:
        abs_path = _normalize_project_relative(file_path or default_spec_path())
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Markdown spec successfully written to {abs_path}"
    except Exception as e:
        return f"Error writing Markdown spec: {e}"


def append_md_file_tool(content: str, file_path: Optional[str] = None) -> str:
    """
    Appends a chunk of Markdown to the functional specification file.

    Used together with write_md_file_tool to build large documents in chunks:
    one giant tool argument makes local models emit malformed calls that never
    execute, so the writer saves section groups one at a time instead.

    Dedup guard: if every top-level (##) heading in the chunk is already present
    in the file, the append is skipped. This prevents the duplicated-section
    corruption seen when a model re-sends the same chunk after a retry.
    """
    try:
        abs_path = _normalize_project_relative(file_path or default_spec_path())
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        existing = ""
        if os.path.exists(abs_path):
            with open(abs_path, "r", encoding="utf-8") as f:
                existing = f.read()

        new_headers = re.findall(r"^##\s+.+$", content, flags=re.MULTILINE)
        if new_headers and all(h in existing for h in new_headers):
            return (
                f"Skipped duplicate append to {abs_path}: section(s) "
                f"{', '.join(new_headers)} already present."
            )

        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Markdown chunk appended to {abs_path}"
    except Exception as e:
        return f"Error appending Markdown spec: {e}"


def read_md_file_tool(file_path: Optional[str] = None) -> str:
    """
    Reads the entire content of a Markdown file and returns it as a string.

    Args:
        file_path (str): Optional path to the Markdown spec (defaults to the
            active session's functional_specification.md).

    Returns:
        str: The full text content of the Markdown file, or an error message.
    """
    import os
    try:
        abs_path = _normalize_project_relative(file_path or default_spec_path())
        if not os.path.exists(abs_path):
            return f"Error: Markdown file not found at {abs_path}"

        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content if content.strip() else "Markdown file is empty — no readable text found."
    except Exception as e:
        return f"Error reading Markdown file: {e}"


def write_mermaid_to_file_tool(mermaid_code: str, file_path: Optional[str] = None) -> str:
    """
    Writes Mermaid diagram code to a .mmd file with proper formatting.

    Args:
        mermaid_code (str): The Mermaid syntax/code to write.
        file_path (str): Optional path for saving. Defaults to the active session's
            process_diagram.mmd.

    Returns:
        str: Confirmation or error message.
    """

    try:
        abs_path = _normalize_project_relative(file_path or default_mermaid_path())
        # Ensure the folder exists
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        # Validate file extension
        if not abs_path.as_posix().endswith('.mmd'):
            return "Error: Filename must end with '.mmd'"

        # Write the Mermaid code into a fenced code block
        with open(abs_path, 'w', encoding='utf-8') as file:
            file.write("```mermaid\n")
            file.write(mermaid_code)
            file.write("\n```")

        return f"Mermaid diagram successfully written to {abs_path}"
    except Exception as e:
        return f"Error writing Mermaid file: {e}"


def move_file_tool(source_path: str, destination_path: str) -> str:
    """Move/rename a file inside the project (used by terminate_agent).

    Replaces the external PyMCP-FS `move_file` tool with a project-scoped one.
    """
    try:
        src = _normalize_project_relative(source_path)
        dst = _normalize_project_relative(destination_path)
        if not src.exists():
            return f"Error: source file not found: {src}"
        _ensure_parent_dir(dst)
        shutil.move(str(src), str(dst))
        return f"Moved {src} -> {dst}"
    except Exception as e:
        return f"Error moving file: {e}"


def ensure_dir_tool(dir_path: str) -> str:
    """Create a directory (relative to the project root) if it does not exist."""
    try:
        target = _normalize_project_relative(dir_path)
        target.mkdir(parents=True, exist_ok=True)
        return f"Directory ready: {target}"
    except Exception as e:
        return f"Error creating directory: {e}"


def get_session_dir_tool() -> str:
    """Return the absolute path of the current run's session folder.

    The terminate agent must not guess the folder: every deliverable of this
    run lives in conversation/<SESSION_ID>/, and this tool is the single
    source of truth for that path.
    """
    session_dir = _session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)


def mirror_canvas_to_disk(update_file_tool):
    """Make every canvas write land in the session folder as a real file.

    TextCanvasMemory is in-memory only, so a diagram "saved as
    canvas_diagram.md" never exists on disk. The Mermaid MCP tools read from
    disk, so `check_mermaid`/`clean_mermaid` on that path raise
    FileNotFoundError and the terminate stage stumbles. Wrapping the tool
    mirrors each revision into conversation/<SESSION_ID>/.
    """
    original_run = update_file_tool.run

    async def run(args, cancellation_token=None):
        result = await original_run(args, cancellation_token)
        try:
            filename = getattr(args, "filename", None)
            content = getattr(args, "new_content", None)
            if filename and isinstance(content, str):
                target = _session_dir() / Path(str(filename)).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        except Exception as exc:
            print(f"⚠️  Canvas mirror failed: {type(exc).__name__}: {exc}")
        return result

    update_file_tool.run = run
    return update_file_tool


# ---- deterministic deliverable completion -----------------------------------
# Local models can stop the terminate stage early (or answer "READY" without
# ever calling the write tool). These functions finish the artifacts without a
# model, so the run always ends with a rendered diagram and a PDF.
_LIFECYCLE_STATUSES = ["Check-In", "Received", "In Cleaning", "Quality Check",
                       "Ready for Pickup", "Picked Up", "Check-Out"]


def _pdf_server_module():
    """Load the PDF MCP server module as a plain library (no MCP transport)."""
    import importlib.util
    path = _PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py"
    spec = importlib.util.spec_from_file_location("pdf_format_mcp_server", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_diagram_source(session_dir: Path) -> Optional[Path]:
    """Write a Mermaid source for the lifecycle if the diagram agents produced none."""
    session_dir = Path(session_dir)
    mmd = session_dir / "process_diagram.mmd"
    if mmd.is_file():
        return mmd
    spec = session_dir / "functional_specification.md"
    if not spec.is_file():
        return None
    try:
        text = spec.read_text(encoding="utf-8")
    except OSError:
        return None
    statuses = [s for s in _LIFECYCLE_STATUSES if re.search(rf"\b{s}\b", text, re.IGNORECASE)]
    if len(statuses) < 2:
        return None
    lines = ["%% Auto-derived from the status lifecycle in functional_specification.md",
             "flowchart TD"]
    for i, name in enumerate(statuses):
        node = chr(65 + i)
        lines.append(f"    {node}[{name}]")
        if i:
            lines.append(f"    {chr(65 + i - 1)} --> {node}")
    mmd.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mmd


def render_diagram_png(session_dir: Path) -> Optional[Path]:
    """Render process_diagram.mmd to PNG with mmdc (no model involved).

    If the agent-written diagram is syntactically broken (mmdc exits with a
    parser error), it is replaced with the status-lifecycle diagram derived
    from the spec so the deliverable still contains a diagram.
    """
    import subprocess
    session_dir = Path(session_dir)
    png = session_dir / "process_diagram.png"
    if png.is_file():
        return png
    mmd = ensure_diagram_source(session_dir)
    if not mmd:
        return None
    exe = shutil.which("mmdc")  # resolves to mmdc.cmd on Windows; bare name fails there
    if not exe:
        return None

    def _try(source: Path) -> bool:
        raw = source.read_text(encoding="utf-8").strip()
        if raw.startswith("```"):  # mmdc cannot parse ```mermaid fences
            raw = raw.split("\n", 1)[1] if "\n" in raw else ""
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        clean = session_dir / "process_diagram.clean.mmd"
        clean.write_text(raw.strip() + "\n", encoding="utf-8")
        try:
            subprocess.run([exe, "-i", str(clean), "-o", str(png)], check=True, timeout=120,
                           capture_output=True, stdin=subprocess.DEVNULL)
        except Exception:
            return False
        return png.is_file()

    if _try(mmd):
        return png
    # The diagram the model wrote does not parse - derive one from the spec.
    derived = session_dir / "process_diagram.derived.mmd"
    statuses = []
    spec = session_dir / "functional_specification.md"
    if spec.is_file():
        try:
            text = spec.read_text(encoding="utf-8")
            statuses = [s for s in _LIFECYCLE_STATUSES if re.search(rf"\b{s}\b", text, re.IGNORECASE)]
        except OSError:
            statuses = []
    if len(statuses) < 2:
        statuses = list(_LIFECYCLE_STATUSES)
    lines = ["flowchart TD"]
    for i, name in enumerate(statuses):
        node = chr(65 + i)
        lines.append(f"    {node}[{name}]")
        if i:
            lines.append(f"    {chr(65 + i - 1)} --> {node}")
    derived.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if _try(derived):
        mmd.write_text(derived.read_text(encoding="utf-8"), encoding="utf-8")
        return png
    return None


def export_deliverable_pdf(session_dir: Path) -> Optional[Path]:
    """Build deliverable.pdf with the PyMuPDF exporter if it is absent or has no diagram."""
    session_dir = Path(session_dir)
    pdf = session_dir / "deliverable.pdf"
    diagram = session_dir / "process_diagram.png"
    spec = session_dir / "functional_specification.md"
    if not spec.is_file():
        return pdf if pdf.is_file() else None
    if pdf.is_file():
        complete = not diagram.is_file() or (_pdf_has_image(pdf) and _pdf_has_outline(pdf))
        # A PDF not newer than the spec is stale: the terminate agent can report
        # PASS against a deliverable from a previous run. Equality counts as
        # stale because filesystem clock resolution can make both writes land
        # in the same tick.
        stale = spec.stat().st_mtime >= pdf.stat().st_mtime
        if complete and not stale:
            return pdf
    module = _pdf_server_module()
    if module is None:
        return pdf if pdf.is_file() else None
    try:
        module.format_document(spec.parent, "functional_specification.md", "process_diagram.png",
                               "functional_specification.formatted.md")
        module._pymupdf_export(spec.parent / "functional_specification.formatted.md",
                               diagram if diagram.is_file() else None,
                               pdf,
                               title=module._extract_title(spec))
        return pdf if pdf.is_file() else None
    except Exception:
        return pdf if pdf.is_file() else None


def _pdf_has_outline(pdf_path: Path) -> bool:
    """True when the PDF has PDF bookmarks, not just a rendered Contents block."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        has = bool(doc.get_toc())
        doc.close()
        return has
    except Exception:
        return True  # can't inspect it - leave the existing PDF alone


def _pdf_has_image(pdf_path: Path) -> bool:
    """True when the PDF already embeds at least one image (the diagram)."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        count = sum(len(page.get_images()) for page in doc)
        doc.close()
        return count > 0
    except Exception:
        return True  # can't inspect it - leave the existing PDF alone


def finalize_deliverables(session_dir: Optional[str] = None) -> Dict[str, Any]:
    """Ensure the diagram PNG and deliverable.pdf exist for this run."""
    sd = Path(session_dir) if session_dir else _session_dir()
    png = render_diagram_png(sd)
    pdf = export_deliverable_pdf(sd)
    return {
        "session_dir": str(sd),
        "diagram_png": str(png) if png else None,
        "pdf": str(pdf) if pdf else None,
    }


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
MISSING_WRITER_SECTIONS = re.compile(
    r"\b("  # key sections the writer must generate
    r"use\s*cases?|"          # Use Case / Use Cases
    r"user\s*stor(?:y|ies)|"  # User Story / User Stories
    r"glossar(?:y|ies)"       # Glossary / Glossaries
    r")\b",
    re.IGNORECASE,
)

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
    - Handle checker 'NEEDS_INFO' by routing back to planning_agent,
      EXCEPT when missing sections are Use Cases, User Stories, or Glossary;
      in that case select functional_spec_writer_agent to generate them.
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

    # CHECKER: if NEEDS_INFO ->
    #   - If the missing items are Use Cases/User Stories/Glossary, route to WRITER to generate them.
    #   - Otherwise hand control to PLANNING (it will run the interviewer loop with the user).
    if last_src == CHECKER:
        if "NEEDS_INFO" in last_txt:
            if MISSING_WRITER_SECTIONS.search(last_txt or ""):
                return WRITER
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

    # TERMINATE: keep control with terminate_agent until it outputs explicit TERMINATE
    if last_src == TERMINATE:
        if re.search(r"\bTERMINATE\b", last_txt):
            return PLANNING
        return TERMINATE

    # Fallback: always give control to planner
    return PLANNING

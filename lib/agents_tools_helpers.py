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


_PDF_SERVER_CACHE: Dict[str, Any] = {}


def _pdf_server_module():
    """Load the PDF MCP server module as a plain library (no MCP transport).

    Cached: re-executing the file on every call cost ~40s (it pulls in
    sentence_transformers), so finalize_deliverables - which calls this five
    times - could take minutes for no reason.
    """
    if "module" in _PDF_SERVER_CACHE:
        return _PDF_SERVER_CACHE["module"]
    import importlib.util
    path = _PROJECT_ROOT / "mcp_servers" / "Final_deliverable_MCP_server" / "PDF_format_mcp_server.py"
    spec = importlib.util.spec_from_file_location("pdf_format_mcp_server", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PDF_SERVER_CACHE["module"] = module
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


def _mmdc_puppeteer_flags() -> List[str]:
    """mmdc needs '-p <config>' on GitHub runners: Ubuntu 24.04+ blocks
    Chrome's sandbox via AppArmor, so rendering fails without --no-sandbox.
    Local runs keep mmdc's defaults.
    """
    if os.environ.get("CI"):
        cfg = _PROJECT_ROOT / "mcp_servers" / "Mermaid-MCP" / "puppeteer-ci.json"
        if cfg.exists():
            return ["-p", str(cfg)]
    return []

def _mermaid_repair(source: str) -> str:
    """Second chance for a diagram mmdc rejects.

    Mermaid reads ';' as a statement separator, so a semicolon inside a
    sequence-diagram message - "Open bag record; same actions allowed as after a
    scan" - parses as a second, dangling statement and the whole diagram fails.
    A comma keeps the text as one message. Only message lines (arrow + colon)
    are touched, so classDef and flowchart separators survive.
    """
    out = []
    for line in source.splitlines():
        head, colon, tail = line.partition(":")
        if colon and ";" in tail and re.search(r"->|>>|<-|\.\.", head):
            line = head + colon + tail.replace(";", ",")
        out.append(line)
    return "\n".join(out) + "\n"


def _run_mmdc(exe: str, clean: Path, png: Path) -> bool:
    import subprocess
    try:
        subprocess.run([exe, "-i", str(clean), "-o", str(png)] + _mmdc_puppeteer_flags(),
                       check=True, timeout=120, capture_output=True, stdin=subprocess.DEVNULL)
    except Exception:
        return False
    return png.is_file()


def _render_one_mmdc(exe: str, session_dir: Path, source_text: str, png: Path, tag: str) -> bool:
    """Render one Mermaid body with mmdc. Returns True when the PNG lands."""
    clean = session_dir / f"{tag}.clean.mmd"
    clean.write_text(source_text.strip() + "\n", encoding="utf-8")
    if _run_mmdc(exe, clean, png):
        return True
    repaired = _mermaid_repair(source_text)
    if repaired.strip() == source_text.strip():
        return False
    clean.write_text(repaired.strip() + "\n", encoding="utf-8")
    return _run_mmdc(exe, clean, png)


def _derived_lifecycle_source(session_dir: Path) -> str:
    """A status-lifecycle flowchart derived from the spec.

    Used when nothing in the agent-written canvas parses, so the deliverable
    still carries a diagram.
    """
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
    out = ["flowchart TD"]
    for i, name in enumerate(statuses):
        node = chr(65 + i)
        out.append(f"    {node}[{name}]")
        if i:
            out.append(f"    {chr(65 + i - 1)} --> {node}")
    return "\n".join(out) + "\n"


def render_diagram_pngs(session_dir: Path) -> List[Path]:
    """Render every Mermaid diagram in the canvas to its own PNG.

    The canvas is a Markdown document with one fence per diagram, and mmdc
    renders exactly one diagram per invocation - a ten-diagram canvas needs ten
    calls. The first is `process_diagram.png` (the one the PDF and HTML call
    "the process diagram"); the rest are `process_diagram_2.png`,
    `process_diagram_3.png`, ...
    """
    session_dir = Path(session_dir)
    first = session_dir / "process_diagram.png"
    exe = shutil.which("mmdc")  # resolves to mmdc.cmd on Windows; bare name fails there
    if not exe:
        return [first] if first.is_file() else []

    mmd = ensure_diagram_source(session_dir)
    if not mmd:
        return [first] if first.is_file() else []

    diagrams = _pdf_server_module().canvas_diagrams(_mermaid_source(session_dir) or "")
    if not diagrams:
        diagrams = [{"title": "Process Diagram", "source": mmd.read_text(encoding="utf-8")}]

    rendered: List[Path] = []
    for index, diagram in enumerate(diagrams):
        tag = "process_diagram" if index == 0 else f"process_diagram_{index + 1}"
        png = session_dir / f"{tag}.png"
        if png.is_file() or _render_one_mmdc(exe, session_dir, diagram["source"], png, tag):
            rendered.append(png)

    # A canvas that shrank between runs leaves orphan PNGs behind; the Markdown
    # embedder walks `process_diagram_2.png`, `process_diagram_3.png`, ... in
    # order, so an orphan would attach a diagram that is no longer in the canvas.
    keep = {png.name for png in rendered}
    if keep:
        for stale in session_dir.glob("process_diagram*.png"):
            if stale.name not in keep:
                stale.unlink()

    if rendered:
        return rendered

    # Nothing in the canvas parsed - derive a lifecycle diagram instead.
    derived = session_dir / "process_diagram.derived.mmd"
    derived.write_text(_derived_lifecycle_source(session_dir), encoding="utf-8")
    if _render_one_mmdc(exe, session_dir, derived.read_text(encoding="utf-8"), first, "process_diagram"):
        mmd.write_text(derived.read_text(encoding="utf-8"), encoding="utf-8")
        return [first]
    return []


def render_diagram_png(session_dir: Path) -> Optional[Path]:
    """Render the process diagram to PNG with mmdc (no model involved).

    Returns the main diagram only; `render_diagram_pngs` renders them all.
    """
    pngs = render_diagram_pngs(session_dir)
    return pngs[0] if pngs else None


def _mermaid_source(session_dir: Path) -> Optional[str]:
    """The diagram source, if the agents wrote one."""
    for name in ("process_diagram.mmd", "process_diagram.derived.mmd", "canvas_diagram.md"):
        path = session_dir / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                continue
    return None


def _diagram_png_names(session_dir: Path) -> List[Optional[str]]:
    """One slot per canvas diagram, `None` where mmdc failed to render.

    Positional on purpose. `render_diagram_pngs` returns only the PNGs that
    exist, so a compacted list puts `process_diagram_6.png` under the fifth
    diagram's heading and loses the last diagram entirely. `_diagram_block`
    pairs the list with the canvas by index, so a missing render must stay a
    slot - the heading keeps its Mermaid source and simply gets no image.
    """
    server = _pdf_server_module()
    if server is None:
        return [p.name for p in render_diagram_pngs(session_dir)] or ["process_diagram.png"]
    names = server._diagram_png_names(Path(session_dir))
    return names or ["process_diagram.png"]


def embed_diagram_in_markdown(session_dir: Path) -> bool:
    """Put every rendered diagram and its Mermaid source into functional_specification.md.

    The specification the agents write never mentions the diagrams - only the
    PDF does - so the .md deliverable used to ship without them. Writing them
    into the Markdown makes the .md a real deliverable: the PNG inline plus a
    ```mermaid fence, which GitHub and most Markdown viewers render natively.
    """
    session_dir = Path(session_dir)
    spec = session_dir / "functional_specification.md"
    if not spec.is_file():
        return False
    try:
        md = spec.read_text(encoding="utf-8")
        updated = _pdf_server_module().embed_diagram(
            md, _diagram_png_names(session_dir), _mermaid_source(session_dir)
        )
        if updated == md:
            return True
        spec.write_text(updated, encoding="utf-8")
        return True
    except Exception:
        return False


def _html_has_image(html_path: Path) -> bool:
    try:
        return "<img" in html_path.read_text(encoding="utf-8")
    except OSError:
        return True


def export_deliverable_html(session_dir: Path) -> Optional[Path]:
    """Build the self-contained functional_specification.html next to the PDF."""
    session_dir = Path(session_dir)
    html = session_dir / "functional_specification.html"
    spec = session_dir / "functional_specification.md"
    diagram = session_dir / "process_diagram.png"
    if not spec.is_file():
        return html if html.is_file() else None
    if html.is_file():
        complete = not diagram.is_file() or _html_has_image(html)
        stale = spec.stat().st_mtime >= html.stat().st_mtime
        if complete and not stale:
            return html
    module = _pdf_server_module()
    if module is None:
        return html if html.is_file() else None
    try:
        formatted = session_dir / "functional_specification.formatted.md"
        if not formatted.is_file() or formatted.stat().st_mtime < spec.stat().st_mtime:
            module.format_document(session_dir, "functional_specification.md",
                                   "process_diagram.png", "functional_specification.formatted.md")
        module.build_html_deliverable(
            session_dir,
            "functional_specification.formatted.md",
            "functional_specification.html",
            title=module._extract_title(spec),
        )
        return html if html.is_file() else None
    except Exception:
        return html if html.is_file() else None


def export_deliverable_pdf(session_dir: Path) -> Optional[Path]:
    """Build functional_specification.pdf with the PyMuPDF exporter if it is absent or has no diagram."""
    session_dir = Path(session_dir)
    pdf = session_dir / "functional_specification.pdf"
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
        # Typst when the binaries are installed, PyMuPDF fallback otherwise -
        # same entry point the export_pdf MCP tool uses.
        module.render_pdf_deliverable(spec.parent, "functional_specification.formatted.md",
                                      "functional_specification.pdf")
        return pdf if pdf.is_file() else None
    except Exception:
        return pdf if pdf.is_file() else None


def _pdf_has_outline(pdf_path: Path) -> bool:
    """True when the PDF has PDF bookmarks, not just a rendered Contents block."""
    try:
        import pymupdf as fitz  # `fitz` is the deprecated PyMuPDF alias
        doc = fitz.open(str(pdf_path))
        has = bool(doc.get_toc())
        doc.close()
        return has
    except Exception:
        return True  # can't inspect it - leave the existing PDF alone


def _pdf_has_image(pdf_path: Path) -> bool:
    """True when the PDF already embeds at least one image (the diagram)."""
    try:
        import pymupdf as fitz  # `fitz` is the deprecated PyMuPDF alias
        doc = fitz.open(str(pdf_path))
        count = sum(len(page.get_images()) for page in doc)
        doc.close()
        return count > 0
    except Exception:
        return True  # can't inspect it - leave the existing PDF alone


def migrate_legacy_deliverable_names(session_dir: Path) -> List[str]:
    """Rename the pre-v1.1 `deliverable.pdf` / `deliverable.html` in place.

    Older runs wrote the PDF as deliverable.pdf. A session folder that still has
    one would otherwise end up with two copies of the same spec under different
    names. Only renames when the new name is absent, so a partial migration
    never overwrites a real deliverable.
    """
    session_dir = Path(session_dir)
    renamed = []
    for old, new in (("deliverable.pdf", "functional_specification.pdf"),
                     ("deliverable.html", "functional_specification.html")):
        src, dst = session_dir / old, session_dir / new
        if src.is_file() and not dst.is_file():
            try:
                src.rename(dst)
                renamed.append(f"{old} -> {new}")
            except OSError:
                pass
    return renamed


def normalize_markdown_headings(session_dir: Path) -> int:
    """Split headings glued onto the end of a paragraph, in place.

    `functional_specification.md` is the writer's own file, and the writer
    sometimes appends `## 4. Functional Requirements` straight after the previous
    sentence with no newline. Markdown then never sees a heading, so the section
    is missing from every rendered deliverable. Fix the source file once so the
    .md, .html and .pdf all agree.
    """
    module = _pdf_server_module()
    spec = Path(session_dir) / "functional_specification.md"
    if module is None or not spec.is_file():
        return 0
    text = spec.read_text(encoding="utf-8")
    fixed, splits = module.split_glued_headings(text)
    if splits:
        spec.write_text(fixed, encoding="utf-8")
    return splits


# The writer's document template, as the checker is told to verify. Finalize
# reports the sections that never made it to disk so the operator and the UI can
# see a truncated spec instead of a silently short one.
TEMPLATE_SECTIONS = [
    ("Title Page", r"title\s*page"),
    ("Introduction", r"introduction|overview"),
    ("Scope", r"scope"),
    ("Functional Requirements", r"functional\s*requirements"),
    ("Non-Functional Requirements", r"non[\s-]*functional\s*requirements"),
    ("User Roles & Personas", r"user\s*roles|personas|roles?\s*(?:and|&)\s*responsibilities"),
    ("Assumptions & Constraints", r"assumptions|constraints"),
    ("Use Cases", r"use\s*cases|user\s*stor(?:y|ies)"),
    ("Glossary", r"glossar(?:y|ies)"),
]


def missing_template_sections(session_dir: Path) -> List[str]:
    """Heading names from the template that the spec does not contain."""
    spec = Path(session_dir) / "functional_specification.md"
    if not spec.is_file():
        return [name for name, _ in TEMPLATE_SECTIONS]
    headings = [line.strip() for line in spec.read_text(encoding="utf-8", errors="ignore").splitlines()
                if re.match(r"^\s*#{1,6}\s+\S", line)]
    blob = " \n".join(headings).lower()
    missing = []
    for name, pattern in TEMPLATE_SECTIONS:
        # The writer commonly uses its project name as the document's H1 instead
        # of a literal "Title Page" heading; that is a valid title page.
        present = (bool(re.search(pattern, blob)) if name != "Title Page" else
                   bool(re.search(pattern, blob)) or any(re.match(r"^#\s+\S", h) for h in headings))
        if not present:
            missing.append(name)
    return missing


def _sentences(text: str) -> List[str]:
    """Split a Markdown run into sentences, ignoring markup noise."""
    text = re.sub(r"[|*_#]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 12]


def _glossary_rows(md: str) -> List[List[str]]:
    """Terms the document defines itself: requirement titles, explicit
    `**Term**: definition` lines, two-column term tables and status names."""
    rows: List[List[str]] = []
    seen: set = set()

    document_metadata = {
        "date", "author", "authors", "author(s)", "sponsor", "version",
        "document status", "owner", "related area", "requirements source", "status",
    }

    def add(term: str, definition: str) -> None:
        term = term.strip().strip("*: ").strip()
        definition = " ".join(definition.split()).lstrip("- ").strip()
        key = term.lower()
        if not term or len(definition) < 10 or key in seen or key in document_metadata:
            return
        seen.add(key)
        rows.append([term, definition[:220]])

    lines = md.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*(?:\*\*)?((?:FR|BR|NFR|UC)-\d+):\s*([^*\n]+)", line)
        if match:
            definition = ""
            for follow in lines[index + 1:]:
                if follow.strip().startswith(("|", "#", "```")):
                    break
                if follow.strip():
                    definition = follow.strip()
                    break
            add(f"{match.group(1)} {match.group(2).strip()}", definition)
            continue
        match = re.match(r"^\s*\*\*([^*]{3,40})\*\*:\s*(.+)$", line)
        if match:
            add(match.group(1), match.group(2))
            continue
        cells = [c.strip() for c in re.split(r"\s*\|\s*", line.strip("|")) if c.strip()]
        if len(cells) == 2 and not set(cells[0]) <= {"-", " "} and cells[0].lower() != "term":
            add(cells[0], cells[1])

    sentences = _sentences(md)
    for status in _LIFECYCLE_STATUSES:
        if re.search(rf"\b{re.escape(status)}\b", md, re.I):
            for sentence in sentences:
                if re.search(rf"\b{re.escape(status)}\b", sentence, re.I):
                    add(status, sentence)
                    break
    return rows


def _role_rows(md: str) -> List[List[str]]:
    """Roles named in the requirements, with what the document says they do."""
    roles = {}
    for sentence in _sentences(md):
        for match in re.findall(
            r"\b((?:Counter|Floor|Shop|Shift|Senior|Junior)?\s?(?:Staff|Supervisor|Manager|"
            r"Administrator|Operator|Cashier|Technician|Cleaner|Driver|Customer))\b", sentence):
            role = " ".join(match.split())
            if role.lower() not in roles:
                roles[role.lower()] = (role, [])
            if len(roles[role.lower()][1]) < 3:
                roles[role.lower()][1].append(sentence[:200])
    return [[role, "; ".join(citations)] for role, citations in roles.values()]


def _assumption_lines(md: str) -> List[str]:
    markers = re.compile(
        r"(?i)\b(assume|assumes|constraint|limitation|must not|cannot|unable to|no internet|"
        r"offline|only when|requires? that|is not available|depends on)\b"
    )
    lines = []
    for sentence in _sentences(md):
        if markers.search(sentence) and len(lines) < 15:
            lines.append(sentence)
    return lines


def _section_filler(name: str, md: str) -> Optional[str]:
    """Build the section from text already in the document. Returns None when
    there is nothing grounded to say - inventing content is worse than a gap."""
    if name == "Introduction":
        body = md.split("\n", 1)[1] if md.startswith("#") else md
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        if not paragraphs:
            return None
        return "\n\n".join(paragraphs[:2])

    if name == "Scope":
        hits = [s for s in _sentences(md) if re.search(r"(?i)\b(in scope|out of scope|scope)\b", s)]
        return "\n".join(f"- {s}" for s in hits[:10]) if hits else None

    if name in ("Functional Requirements", "Non-Functional Requirements"):
        ids = "FR" if name == "Functional Requirements" else "NFR|BR"
        pattern = rf"^\s*(?:\*\*)?(({ids})-\d+):\s*([^*\n]+)"
        items = [f"- **{m.group(1)}: {m.group(2).strip()}**" for m in re.finditer(pattern, md, re.M)]
        return "\n".join(items[:20]) if items else None

    if name == "User Roles & Personas":
        rows = _role_rows(md)
        if not rows:
            return None
        table = ["| Role | Responsibilities in this specification |", "|---|---|"]
        table += [f"| {role} | {citations} |" for role, citations in rows]
        return "\n".join(table)

    if name == "Assumptions & Constraints":
        lines = _assumption_lines(md)
        return "\n".join(f"- {s}" for s in lines) if lines else None

    if name == "Use Cases":
        items = re.findall(r"^\s*(?:\*\*)?((?:UC|US)-\d+[^*\n]*?)(?:\*\*)?\s*$", md, re.M)
        if not items:
            items = [f"{m.group(1)} {m.group(2).strip()}"
                    for m in re.finditer(r"^\s*(?:\*\*)?(FR-\d+):\s*([^*\n]+)", md, re.M)]
        if not items:
            return None
        return "\n".join(f"- {item.strip()}" for item in items[:15])

    if name == "Glossary":
        rows = _glossary_rows(md)
        if not rows:
            return None
        table = ["| Term | Definition |", "|---|---|"]
        table += [f"| {term} | {definition} |" for term, definition in rows]
        return "\n".join(table)

    return None


def ensure_template_sections(session_dir: Path) -> Dict[str, List[str]]:
    """Close the template: every section of the document exists when we export.

    The checker gives the writer MAX_CHECKER_ROUNDS passes to fill a gap. When a
    section is still missing afterwards it is assembled from text already in the
    document - never invented by a model. If there is genuinely nothing to say,
    the heading is still written with an explicit 'fill this in' marker so the
    deliverable is structurally complete and the hole is visible to a human
    instead of silently absent.

    Returns {"grounded": [...], "placeholder": [...]}.
    """
    session_dir = Path(session_dir)
    spec = session_dir / "functional_specification.md"
    if not spec.is_file():
        return {"grounded": [], "placeholder": []}
    md = spec.read_text(encoding="utf-8")
    missing = missing_template_sections(session_dir)
    grounded: List[str] = []
    placeholder: List[str] = []
    number = max([int(m.group(1)) for m in re.finditer(r"^##\s+(\d+)\.", md, re.M)] or [0])
    blocks = []
    for name in missing:
        number += 1
        body = _section_filler(name, md)
        if body:
            grounded.append(name)
            blocks.append(f"## {number}. {name}\n\n_{name} derived from the material already "
                         f"in this document; the writer did not produce it._\n\n{body}\n")
        else:
            placeholder.append(name)
            blocks.append(f"## {number}. {name}\n\n_No material for this section in this run - "
                         f"the interview and the writer produced nothing that belongs here. "
                         f"Fill it in before sign-off.\n")
    if not blocks:
        return {"grounded": grounded, "placeholder": placeholder}
    block = "\n".join(blocks)
    diagram = md.find("\n## Process Diagram")
    if diagram != -1:
        md = md[:diagram].rstrip() + "\n\n" + block + md[diagram:]
    else:
        md = md.rstrip() + "\n\n" + block
    spec.write_text(md, encoding="utf-8")
    return {"grounded": grounded, "placeholder": placeholder}


def finalize_deliverables(session_dir: Optional[str] = None) -> Dict[str, Any]:
    """Ensure the diagram PNG, the Markdown, functional_specification.html and functional_specification.pdf exist."""
    sd = Path(session_dir) if session_dir else _session_dir()
    renamed = migrate_legacy_deliverable_names(sd)
    glued = normalize_markdown_headings(sd)
    fill = ensure_template_sections(sd)
    pngs = render_diagram_pngs(sd)
    embed_diagram_in_markdown(sd)
    pdf = export_deliverable_pdf(sd)
    html = export_deliverable_html(sd)
    return {
        "session_dir": str(sd),
        "diagram_png": str(pngs[0]) if pngs else None,
        "diagram_pngs": [str(x) for x in pngs],
        "renamed": renamed,
        "glued_headings_split": glued,
        "auto_filled_sections": fill["grounded"],
        "placeholder_sections": fill["placeholder"],
        "missing_sections": missing_template_sections(sd),
        "markdown": str(sd / "functional_specification.md"),
        "pdf": str(pdf) if pdf else None,
        "html": str(html) if html else None,
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
# The planner names the question it wants the stakeholder to answer
# ("Answer the interviewer's question about measurable KPIs..."). The
# interviewer's own turn in a round is often only a status line, so this is
# the only place the current question is written down.
_PLANNER_QUESTION_RE = re.compile(
    r"question[^.\n]{0,60}?(?:about|regarding|on)\s+([^.\n;]+)", re.I
)
# How many NEEDS_INFO rounds the checker may force before the pipeline moves on
# to the diagram stage. Each round is a full writer pass plus a checker pass.
MAX_CHECKER_ROUNDS = int(os.environ.get("MAX_CHECKER_ROUNDS", "3"))


def current_round(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> list:
    """The turns since the stakeholder's previous answer.

    Scanning the whole history makes latest_question return a question from an
    earlier round whenever the interviewer's current turn was only a status
    line, which is how the simulated stakeholder ends up re-answering a question
    it already answered.
    """
    items = list(messages)
    for i in range(len(items) - 1, -1, -1):
        if (getattr(items[i], "source", "") or "").strip().lower() == USER:
            return items[i + 1:]
    return items


def _extract_question(content: str) -> str:
    """Pull the 'QUESTION:' line out of a turn that also carries other text.

    The interviewer keeps its subject-status table in the same turn as the
    question, so the question is rarely the first thing in the message:
    "Product Overview asked=1, status=done ... QUESTION: On what devices ...".
    Matching only a leading 'QUESTION:' drops it and the stakeholder is then
    handed the status table as its prompt.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(QUESTION_PREFIX):
            return stripped
    index = content.find(QUESTION_PREFIX)
    if index >= 0:
        return content[index:].strip()
    return ""


def latest_question(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str:
    """Return this round's 'QUESTION:' turn, looking past the planner's turn.

    The selector routes every interviewer question through planning_agent before
    the user answers, so AutoGen's input_func receives the planner's
    "Task state:" line rather than the question. Anything that needs the real
    question - the simulated stakeholder above all - has to walk back over it.
    """
    for m in reversed(current_round(messages)):
        content = getattr(m, "content", "")
        if isinstance(content, str):
            question = _extract_question(content)
            if question:
                return question
    return ""


def question_from_planner(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str:
    """Recover the question the planner asked the stakeholder to answer.

    Used when the interviewer emitted only a status line this round: the planner's
    instruction is the only text that states what is being asked.
    """
    for m in reversed(current_round(messages)):
        content = getattr(m, "content", "")
        if not isinstance(content, str):
            continue
        match = _PLANNER_QUESTION_RE.search(content)
        if match:
            return f"{QUESTION_PREFIX} {match.group(1).strip()}"
    return ""


_COVERAGE_RE = re.compile(
    r"([A-Za-z][A-Za-z &,-]{3,40}?)\s*asked=(\d+),\s*status=([a-z ]+)"
)
_STATUSISH_RE = re.compile(r"task (state|tracking)|asked=\d|assign|pending|not started", re.I)


def question_from_coverage(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str:
    """Turn the interviewer's coverage table into the question it is about to ask.

    The interviewer often emits only a progress line
    ("Product Overview asked=1, status=done  KPI & Success Metrics asked=0,
    status=not started") and the actual question arrives in the next turn. The
    first subject still open is what the stakeholder is being asked about, so the
    simulated stakeholder gets a real question instead of the status line.
    """
    for m in reversed(current_round(messages)):
        content = getattr(m, "content", "")
        if not isinstance(content, str) or "asked=" not in content:
            continue
        for subject, asked, status in _COVERAGE_RE.findall(content):
            if asked == "0" and "done" not in status and "skipped" not in status:
                return f"QUESTION: {subject.strip()} - what does this look like in your day-to-day operation?"
    return ""


def question_for_user(prompt: str | None, captured: str = "") -> str:
    """Choose what the stakeholder is actually being asked.

    Planner turns ("Task state:" / "Task tracking:") and interviewer progress
    tables carry no question, so a captured question wins over them; a genuine
    QUESTION prompt is used as-is.
    """
    text = (prompt or "").strip()
    if text.startswith(QUESTION_PREFIX):
        return text
    if _STATUSISH_RE.search(text):
        return captured or "Please describe how this should work in your shop."
    return text or captured or "Please describe how this should work."

# Every section of the writer's document template. When the checker reports one
# of these as missing, the fix belongs with the writer (it has the save tools),
# not with the interviewer - sending it to planning just re-asks the user for
# information the document already has.
def checker_flags_missing_section(text: str) -> bool:
    """True when the checker's NEEDS_INFO list names a section of the template.

    A bare mention of a section word is not enough - "the scope needs the
    customer's SLA" is a question for the user. Only a line that calls a section
    missing/absent/incomplete sends the work back to the writer, which is the
    agent that owns the document and its save tools.
    """
    for line in (text or "").splitlines():
        low = line.lower()
        if not re.search(r"\b(missing|absent|not present|lacking|incomplete|omitted)\b", low):
            continue
        if any(re.search(pattern, low) for _, pattern in TEMPLATE_SECTIONS):
            return True
    return False

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
            # Each NEEDS_INFO round costs a full writer + checker pass against a
            # remote lane. Without a cap the same section can be requested
            # forever and the run dies on MAX_MESSAGES instead of finishing.
            rounds = sum(1 for m in messages
                         if _src(m) == CHECKER and "NEEDS_INFO" in _txt(m))
            # rounds counts the flags already raised; the writer gets one pass
            # per flag up to the cap, and the cap closes the loop after that.
            if rounds > MAX_CHECKER_ROUNDS:
                return DIAGRAM
            if checker_flags_missing_section(last_txt):
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

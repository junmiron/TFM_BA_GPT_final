"""Reinforcement learning from sessions the user explicitly rated as good.

After a run completes the user is asked whether they are happy with the
deliverables:

- happy  -> the deliverables are indexed into a dedicated ChromaDB collection
            (`approved_experiences`) that the interview/writer agents query,
            the session is appended to `experiences/reinforcement_learning.md`,
            and a task -> full-spec JSONL example is written under
            `experiences/fine_tune/` for later model fine-tuning;
- not happy -> the critique is stored in `feedback/<session_id>.md` (plus a
            machine-readable .json) and NOTHING is indexed.

The whole loop is controlled by FEEDBACK_ENABLED in .env. Indexing is
deterministic (no model calls) and upsert-safe: re-indexing the same session
never duplicates documents.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from lib.rag_helpers import split_text

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_LEDGER = _PROJECT_ROOT / "experiences" / "reinforcement_learning.md"
_FINE_TUNE_DIR = _PROJECT_ROOT / "experiences" / "fine_tune"
_FEEDBACK_DIR = _PROJECT_ROOT / "feedback"


def _flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "yes", "on")


def feedback_enabled() -> bool:
    return _flag("FEEDBACK_ENABLED", "true")


def feedback_timeout_s() -> int:
    try:
        return max(30, int(os.getenv("FEEDBACK_TIMEOUT_S", "300")))
    except ValueError:
        return 600


def approved_collection() -> str:
    return os.getenv("RAG_APPROVED_COLLECTION", "approved_experiences").strip() or "approved_experiences"


def chroma_dir() -> Path:
    """Same persistent store the web-RAG collection lives in."""
    config_path = _PROJECT_ROOT / "lib" / "rag_config.yaml"
    chroma_dir = "chromadb_storage"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        chroma_dir = config.get("CHROMA_DIR", chroma_dir)
    except Exception:
        pass
    path = Path(chroma_dir)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path


class HashEmbedder:
    """Deterministic tiny embedder used by the tests (and as a last-resort
    fallback when SentenceTransformer is unavailable). Vectors are a 64-bucket
    token-count histogram - good enough for smoke tests, not for production
    retrieval quality."""

    @classmethod
    def name(cls) -> str:
        return "hash-embedder"

    def dimension(self) -> int:
        return 64

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list:
        return ["cosine", "l2", "ip"]

    @staticmethod
    def build_from_config(config: dict):
        return HashEmbedder()

    def get_config(self) -> dict:
        return {"name": "hash-embedder"}

    def embed(self, documents: List[str]) -> List[List[float]]:
        out = []
        for doc in documents:
            buckets = [0] * 64
            for token in doc.lower().split():
                buckets[sum(map(ord, token)) % 64] += 1
            out.append([float(b) for b in buckets])
        return out

    def __call__(self, input: List[str]) -> List[List[float]]:
        return self.embed(list(input))


def _default_embedder():
    try:
        from chromadb.utils import embedding_functions

        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-mpnet-base-v2"
        )
    except Exception:
        return HashEmbedder()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def session_documents(session_dir: Path, session_id: str, task: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Every chunk of approved output worth indexing: (text, metadata)."""
    session_dir = Path(session_dir)
    docs: List[Tuple[str, Dict[str, Any]]] = []
    base = {
        "session_id": session_id,
        "task": task,
        "kind": "approved-deliverable",
        "date": datetime.now(timezone.utc).isoformat(),
    }

    spec = session_dir / "functional_specification.md"
    spec_text = _read(spec)
    if spec_text:
        for i, chunk in enumerate(split_text(spec_text, chunk_size=500, chunk_overlap=50)):
            docs.append((chunk, {**base, "source_file": spec.name, "chunk_index": i}))

    formatted = _read(session_dir / "functional_specification.formatted.md")
    if formatted and formatted != spec_text:
        for i, chunk in enumerate(split_text(formatted, chunk_size=500, chunk_overlap=50)):
            docs.append((chunk, {**base, "source_file": "functional_specification.formatted.md", "chunk_index": i}))

    for mmd_name in ("process_diagram.mmd", "process_diagram.clean.mmd"):
        mmd = _read(session_dir / mmd_name)
        if mmd:
            docs.append((mmd, {**base, "source_file": mmd_name, "chunk_index": 0}))

    interview_path = session_dir / "interview.jsonl"
    if interview_path.is_file():
        pairs: Dict[Any, Dict[str, Any]] = {}
        for line in interview_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            index = record.get("q_index", len(pairs))
            pair = pairs.setdefault(index, {})
            if record.get("speaker") == "interviewer":
                pair["question"] = record.get("message", "")
            elif record.get("speaker") == "user":
                pair["answer"] = record.get("message", "")
        i = 0
        for pair in pairs.values():
            if pair.get("question") and pair.get("answer"):
                text = f"Q: {pair['question']}\nA: {pair['answer']}"
                docs.append((text, {**base, "source_file": "interview.jsonl", "chunk_index": i}))
                i += 1

    return docs


def index_approved_deliverables(session_dir: Path, session_id: str, task: str,
                                embedder: Optional[Any] = None) -> Dict[str, Any]:
    """Upsert the session's deliverables into the approved-experiences collection.
    Deterministic, idempotent, never raises for missing files."""
    import chromadb

    docs = session_documents(Path(session_dir), session_id, task)
    if not docs:
        return {"indexed": 0, "collection": approved_collection(), "reason": "no deliverable content found"}

    client = chromadb.PersistentClient(path=str(chroma_dir()))
    collection = client.get_or_create_collection(
        name=approved_collection(),
        embedding_function=embedder or _default_embedder(),
    )
    ids = [f"{session_id}-{meta['source_file']}-{meta['chunk_index']}" for _, meta in docs]
    texts = [text for text, _ in docs]
    metas = [meta for _, meta in docs]
    collection.upsert(ids=ids, documents=texts, metadatas=metas)
    return {"indexed": len(docs), "collection": approved_collection()}


def append_ledger(session_id: str, task: str, comment: str, indexed_chunks: int) -> Path:
    """Append one row to the reinforcement-learning ledger (Markdown table)."""
    _LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if not _LEDGER.is_file():
        _LEDGER.write_text(
            "# Reinforcement Learning Ledger\n\n"
            "Sessions the user explicitly rated as good. Source of truth for the\n"
            "fine-tuning corpus in `experiences/fine_tune/` and the approved RAG\n"
            "collection. Do not delete rows; add one per approved run.\n\n"
            "| Session | Date | Task | Chunks indexed | Feedback |\n"
            "|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    clean_task = (task or "").replace("|", "/").replace("\n", " ")[:120]
    clean_comment = (comment or "").replace("|", "/").replace("\n", " ")[:160]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(f"| {session_id} | {date} | {clean_task} | {indexed_chunks} | {clean_comment} |\n")
    return _LEDGER


def write_fine_tune_example(session_id: str, task: str, spec_text: str) -> Path:
    """One JSONL line: instruction (the task) -> output (the approved spec)."""
    _FINE_TUNE_DIR.mkdir(parents=True, exist_ok=True)
    path = _FINE_TUNE_DIR / f"{session_id}.jsonl"
    example = {
        "session": session_id,
        "date": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "instruction": f"Write a functional specification for: {task}",
        "output": spec_text,
    }
    path.write_text(json.dumps(example, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_feedback(session_id: str, task: str, comment: str, artifacts: List[Dict[str, Any]]) -> Tuple[Path, Path]:
    """Store the critique for later system improvement. Nothing is indexed."""
    _FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _FEEDBACK_DIR / f"{session_id}.md"
    json_path = _FEEDBACK_DIR / f"{session_id}.json"
    date = datetime.now(timezone.utc).isoformat()
    md_path.write_text(
        f"# Feedback for {session_id}\n\n"
        f"- Date: {date}\n"
        f"- Satisfied: no\n"
        f"- Task: {task}\n"
        f"- What went wrong: {comment or '(no comment provided)'}\n"
        f"- Artifacts at the time: {', '.join(a.get('name', '') for a in artifacts) or 'none'}\n",
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps({"session": session_id, "task": task, "date": date, "satisfied": False,
                    "comment": comment, "artifacts": artifacts}, ensure_ascii=False),
        encoding="utf-8",
    )
    return md_path, json_path


def process_feedback(session_dir: Path, session_id: str, task: str, satisfied: bool,
                     comment: str = "", embedder: Optional[Any] = None) -> Dict[str, Any]:
    """Route one feedback answer: happy -> RAG + ledger + fine-tune corpus;
    unhappy -> feedback folder only."""
    if not feedback_enabled():
        return {"action": "disabled"}
    if satisfied:
        result = index_approved_deliverables(session_dir, session_id, task, embedder=embedder)
        append_ledger(session_id, task, comment, result.get("indexed", 0))
        spec_text = _read(Path(session_dir) / "functional_specification.md")
        if spec_text:
            write_fine_tune_example(session_id, task, spec_text)
        return {"action": "indexed", **result}
    md_path, json_path = write_feedback(session_id, task, comment, [])
    return {"action": "feedback_saved", "files": [str(md_path), str(json_path)]}

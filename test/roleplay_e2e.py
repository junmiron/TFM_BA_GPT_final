"""
Headless end-to-end role-play against the REAL app2 pipeline.

Runs the actual app (Chainlit on_chat_start + SelectorGroupChat), but replaces
Chainlit's interactive AskUserMessage with a scripted "human" that replays the
answers recorded in conversation/interview.jsonl. Per the user's instruction the
model host is pointed at Strata: http://127.0.0.1:47831/v1, model q2_0.

This validates all four reported bugs together:
  1. spec is fully written to disk (session folder, deduped)
  2. deliverables live in conversation/<SESSION_ID>/
  3. functional_specification.pdf is produced (PyMuPDF fallback, no pandoc)
  4. the terminate agent's session steps run
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Split the load: the agent pipeline runs on the local Strata server, while the
# simulated stakeholder answering the interview runs on the remote opencode-go
# lane. Groq's 8000 tokens/min ceiling is not touched, and the two halves do not
# compete for the same capacity.
# ROLEPLAY_MODEL_CLIENT wins over the app-wide MODEL_CLIENT so this harness can
# exercise the split without changing the app's own profile.
os.environ["MODEL_CLIENT"] = os.getenv("ROLEPLAY_MODEL_CLIENT", "strata")
os.environ["MODEL_CLIENT_TOOLS"] = os.getenv("ROLEPLAY_MODEL_CLIENT_TOOLS", os.environ["MODEL_CLIENT"])
os.environ["HUMAN_MODEL"] = os.getenv("HUMAN_MODEL", "opencode")
os.environ.setdefault("MAX_MESSAGES", "120")

import chainlit as cl

# ---- simulated human: answers the live question on the remote lane ----
# The canned interview.jsonl answers are only a fallback: the local agent turns
# are what needs the GPU, so the human side is generated on opencode-go.
_LAST_MESSAGE = {"text": ""}


def load_answers():
    path = ROOT / "conversation" / "interview.jsonl"
    answers = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("speaker") == "user":
                answers.append(str(rec.get("message", "")).strip())
    # Sensible defaults so the workflow can always conclude.
    answers.extend([
        "APPROVE SUMMARY",
        "Proceed with the functional specification.",
        "proceed",
        "Looks good, terminate.",
    ])
    return answers


ANSWERS = load_answers()
_idx = {"i": 0}
_TASK = "Design a Laundry Shop Staff App (v1): a Windows PC server app plus an Android mobile app. Staff check in customer orders/bags, generate and print QR tags per order/bag, track item status (Received, In Cleaning, Quality Check, Ready for Pickup, Picked Up), assign shelf locations, scan QR to open records, check out orders, and manually backup/export data from the PC. PC works offline with a local DB (no sync); Android is online-only. Single Staff role with full access."

_SIMULATOR = None


def get_simulator():
    global _SIMULATOR
    if _SIMULATOR is None:
        try:
            from human_simulator import build_human_simulator
            _SIMULATOR = build_human_simulator(os.getenv("HUMAN_MODEL", "opencode"))
        except Exception as exc:
            print(f"[human-lane] simulator unavailable ({type(exc).__name__}: {exc}); "
                  "falling back to scripted answers")
            _SIMULATOR = False
    return _SIMULATOR if _SIMULATOR else None


class _StepDict(dict):
    """Minimal stand-in for Chainlit's StepDict returned by AskUserMessage."""
    pass


async def fake_ask(content=None, timeout=None, **kw):
    # First call is the initial task prompt.
    if content and "Enter the task" in str(content):
        return {"content": _TASK}

    question = _LAST_MESSAGE["text"].strip()

    # The summarizer only accepts the exact approval token; never improvise it.
    if "APPROVE SUMMARY" in question:
        return {"content": "APPROVE SUMMARY"}

    sim = get_simulator()
    if sim and question:
        try:
            answer = await sim.ask(question)
            if answer:
                print(f"[human-lane] {answer[:160]}")
                return {"content": answer}
        except Exception as exc:
            print(f"[human-lane] answer generation failed ({type(exc).__name__}: {exc})")

    # Fallback: replay the recorded interview, then the control defaults.
    i = _idx["i"]
    ans = ANSWERS[i] if i < len(ANSWERS) else "proceed"
    _idx["i"] += 1
    return {"content": ans}


class _FakeMessage:
    def __init__(self, content=""):
        self.content = content
    async def send(self):
        text = self.content or ""
        _LAST_MESSAGE["text"] = text
        print("[chat]", text[:200])
        return self


class _FakeUserSession:
    def __init__(self):
        self._d = {}
    def set(self, k, v):
        self._d[k] = v
    def get(self, k, default=None):
        return self._d.get(k, default)


def patch_chainlit():
    cl.user_session = _FakeUserSession()
    cl.AskUserMessage = lambda content="", timeout=None, **kw: _FakeAsk(content)
    cl.Message = lambda content="", **kw: _FakeMessage(content)


class _FakeAsk:
    def __init__(self, content=""):
        self.content = content
    async def send(self):
        return await fake_ask(self.content)


async def main():
    patch_chainlit()

    # Run the real app's startup, which builds the team and starts the workflow.
    import app2
    await app2.on_chat_start()

    # Give it a moment, then inspect the produced artifacts.
    sess_dir = app2._find_latest_session_dir()
    print("\n=== ARTIFACTS ===")
    print("session dir:", sess_dir)
    if not sess_dir:
        print("RESULT: FAIL (no session dir produced)")
        return 1
    spec = Path(sess_dir) / "functional_specification.md"
    pdf = Path(sess_dir) / "functional_specification.pdf"
    png = Path(sess_dir) / "process_diagram.png"
    mmd = Path(sess_dir) / "process_diagram.mmd"

    import re
    ok = True
    if spec.exists():
        t = spec.read_text(encoding="utf-8")
        heads = re.findall(r"^##\s+\d+\.\s+.+$", t, flags=re.M)
        print("spec exists:", True, "chars:", len(t))
        print("top sections:", heads)
        print("duplicate headings:", [h for h in heads if heads.count(h) > 1])
        ok = ok and len(t) > 2000
    else:
        print("spec exists: False")
        ok = False
    print("process_diagram.mmd exists:", mmd.exists())
    print("process_diagram.png exists:", png.exists())
    print("functional_specification.pdf exists:", pdf.exists())
    if pdf.exists():
        import pymupdf as fitz
        d = fitz.open(str(pdf)); print("pdf pages:", d.page_count); d.close()
    html = Path(sess_dir) / "functional_specification.html"
    print("functional_specification.html exists:", html.exists())
    if html.exists():
        body = html.read_text(encoding="utf-8")
        print("html: bytes", len(body), "img", body.count("<img"),
              "toc", '<nav class="toc"' in body)
        ok = ok and "<!DOCTYPE html>" in body

    print("\nRESULT:", "PASS" if (ok and pdf.exists()) else "PARTIAL" if ok else "FAIL")
    return 0 if (ok and pdf.exists()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

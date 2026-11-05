# app2.py - Chainlit front-end for the multi-agent business-analyst workflow.
#
# The team itself lives in lib/pipeline.py so the Chainlit UI and the React web
# UI (server/api.py) run exactly the same workflow. This file only adapts
# AutoGen events to Chainlit messages.

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
LIB_PATH = os.path.join(PROJECT_ROOT, "lib")
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
sys.path.append(LIB_PATH)
sys.path.append(SRC_PATH)

# Must run before chainlit/fastmcp are imported: the deprecation warnings are
# emitted during those imports.
from quiet_deprecations import suppress_third_party_deprecations

suppress_third_party_deprecations()

import chainlit as cl
from chainlit.element import File as ClFile, Image as ClImage, Pdf as ClPdf

from lib import agents_tools_helpers
from lib.pipeline import create_workflow, run_workflow


async def chainlit_ask_user(prompt=None, cancellation_token=None):
    resp = await cl.AskUserMessage(content=prompt or " ", timeout=3600).send()
    # Chainlit returns the answer under "output" (StepDict); accept legacy keys
    # too. Reading only "content" made every valid answer look empty and
    # re-asked forever.
    text = None
    if resp:
        text = resp.get("content") or resp.get("output") or resp.get("text")
    return (text or "").strip()


async def notify(content: str, author=None):
    await cl.Message(content=content, author=author).send()


class ChainlitSink:
    """Buffer streaming chunks into one Chainlit message per agent turn."""

    def __init__(self):
        self.current = None
        self.source = None

    async def info(self, content: str) -> None:
        await cl.Message(content=content).send()

    async def message(self, source: str, content: str) -> None:
        await cl.Message(content=content, author=source).send()

    async def stream(self, source: str, content: str) -> None:
        if self.source != source or self.current is None:
            await self.flush()
            self.source = source
            self.current = cl.Message(content="", author=source)
        if content:
            await self.current.stream_token(content)

    async def flush(self) -> None:
        if self.current is not None:
            await self.current.send()
            self.current = None
            self.source = None

    async def complete(self, stop_reason) -> None:
        await self.flush()
        await cl.Message(content=f"Workflow complete: {stop_reason}").send()
        try:
            await _present_final_artifacts()
        except Exception as e:  # presentation must never break run completion
            print(f"⚠️  Could not present final artifacts ({type(e).__name__}: {e})")

    async def error(self, content: str) -> None:
        await self.flush()
        await cl.Message(content=f"⚠️ {content}").send()


def _find_latest_session_dir():
    """Return this run's conversation/<SESSION_ID>/ dir.

    The active session (set by the pipeline) wins. The mtime scan is only a
    fallback for when the session was never set - without that guard a stale
    fixture folder from an earlier run silently supplies the artifacts, so the
    checker reports another run's spec.
    """
    conv_root = os.path.join(PROJECT_ROOT, "conversation")
    if not os.path.isdir(conv_root):
        return None

    active = agents_tools_helpers.get_session()
    if active:
        d = os.path.join(conv_root, active)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "functional_specification.md")):
            return d

    best_mtime, best_dir = 0.0, None
    for name in os.listdir(conv_root):
        d = os.path.join(conv_root, name)
        spec = os.path.join(d, "functional_specification.md")
        if os.path.isdir(d) and os.path.isfile(spec):
            mtime = os.path.getmtime(spec)
            if mtime > best_mtime:
                best_mtime, best_dir = mtime, d
    return best_dir


async def _present_final_artifacts():
    """After a completed run, present the full specification + diagrams in chat."""
    session_dir = _find_latest_session_dir()
    if session_dir:
        spec_path = os.path.join(session_dir, "functional_specification.md")
    else:
        # terminate_agent may not have moved the files (or failed to) - fall back
        # to conversation/
        fallback = os.path.join(PROJECT_ROOT, "conversation", "functional_specification.md")
        if os.path.isfile(fallback):
            spec_path, session_dir = fallback, os.path.dirname(fallback)
        else:
            await cl.Message(
                content="⚠️ The workflow finished but no functional specification file was found on disk."
            ).send()
            return

    try:
        with open(spec_path, encoding="utf-8") as f:
            spec_md = f.read()
    except OSError as e:
        await cl.Message(content=f"⚠️ The workflow finished but the specification could not be read ({e}).").send()
        return

    elements = []
    artifacts = agents_tools_helpers.finalize_deliverables(session_dir)
    # Attach every diagram the canvas produced, not just the first one.
    for png in artifacts.get("diagram_pngs") or []:
        if os.path.isfile(png):
            elements.append(ClImage(path=png, name=os.path.basename(png), display="inline"))
    deliverable_pdf = os.path.join(session_dir, "functional_specification.pdf")
    if os.path.isfile(deliverable_pdf):
        elements.append(ClPdf(path=deliverable_pdf, name="functional_specification.pdf"))
    deliverable_html = os.path.join(session_dir, "functional_specification.html")
    if os.path.isfile(deliverable_html):
        elements.append(ClFile(path=deliverable_html, name="functional_specification.html"))
    if not artifacts["diagram_png"] or not artifacts["pdf"] or not artifacts["html"]:
        missing = [n for n, v in (("process_diagram.png", artifacts["diagram_png"]),
                                 ("functional_specification.pdf", artifacts["pdf"]),
                                 ("functional_specification.html", artifacts["html"])) if not v]
        await cl.Message(content=f"⚠️ Could not produce: {', '.join(missing)}").send()
    elements.append(ClFile(path=spec_path, name="functional_specification.md"))

    headline = "## ✅ Final deliverables"
    rel = os.path.relpath(session_dir, PROJECT_ROOT)
    await cl.Message(
        content=f"{headline}\n\nFull functional specification (saved in `{rel}/`):\n\n---\n\n{spec_md}",
        author="Final Deliverables",
        elements=elements,
    ).send()


@cl.on_chat_start
async def on_chat_start():
    try:
        workflow = await create_workflow(chainlit_ask_user, notify)
    except Exception as e:
        await cl.Message(content=f"⚠️ Could not start the workflow: {type(e).__name__}: {e}").send()
        return
    cl.user_session.set("workflow", workflow)

    resp = await cl.AskUserMessage(content="Enter the task for the multi-agent workflow:", timeout=600).send()

    task_text = None
    if isinstance(resp, dict):
        task_text = resp.get("content") or resp.get("output")
    elif isinstance(resp, list) and resp:
        first = resp[0]
        if isinstance(first, dict):
            task_text = first.get("content") or first.get("output")

    if not task_text or not task_text.strip():
        await cl.Message(content="No task provided. You can type it in chat to start later.").send()
        return

    workflow["running"] = True
    try:
        await run_workflow(workflow, task_text.strip(), ChainlitSink())
    finally:
        workflow["running"] = False


@cl.on_message
async def on_message(msg: cl.Message):
    workflow = cl.user_session.get("workflow")
    if not workflow:
        return

    if workflow.get("running"):
        # Workflow already running; replies go through the question box above.
        await cl.Message(content="The workflow is running — please answer in the question box above.").send()
        return

    task_text = (msg.content or "").strip()
    if not task_text:
        await cl.Message(content="Please type a task to start the workflow.").send()
        return

    workflow["running"] = True
    try:
        await run_workflow(workflow, task_text, ChainlitSink())
    finally:
        workflow["running"] = False

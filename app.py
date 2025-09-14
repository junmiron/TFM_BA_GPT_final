import os
import sys
import types
import asyncio

import chainlit as cl
import logging
import re


# Ensure project paths are importable when running via `chainlit run app.py`
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
LIB_PATH = os.path.join(PROJECT_ROOT, "lib")
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
sys.path.append(LIB_PATH)
sys.path.append(SRC_PATH)


@cl.on_chat_start
async def on_chat_start():
    # Optional: mirror notebook env toggles for telemetry
    os.environ.setdefault("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "true")
    os.environ.setdefault("AZURE_SDK_TRACING_IMPLEMENTATION", "opentelemetry")

    from autogen_core import SingleThreadedAgentRuntime
    from autogen_agentchat.conditions import (
        MaxMessageTermination,
        TextMentionTermination,
    )
    from autogen_agentchat.teams import SelectorGroupChat
    from autogen_agentchat import EVENT_LOGGER_NAME
    from autogen_agentchat.messages import (
        ModelClientStreamingChunkEvent,
        TextMessage,
    )
    from autogen_agentchat.base import TaskResult
    from autogen_core import CancellationToken

    from rag_helpers import rag_indexer_runner
    from model_loader import load_model_client
    from agents_creator import create_agents_from_config
    from agents_tools_helpers import selector_func
    from autogen_ext.memory.canvas import TextCanvasMemory

    # 1) Load RAG vector memory (same as the notebook)
    rag_config_path = os.path.join(LIB_PATH, "rag_config.yaml")
    rag_vector_memory = await rag_indexer_runner(rag_config_path)

    # Lightweight event relay to show QUESTIONS in the UI
    # Store last question to display alongside input prompts
    global LAST_QUESTION
    LAST_QUESTION = None

    class ChainlitEventHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                msg = self.format(record)
                if (
                    "ModelClientStreamingChunkEvent (interviewer_agent)" in msg
                    or "ModelClientStreamingChunkEvent (summarizer_agent)" in msg
                ):
                    m = re.search(r"QUESTION:\s.*", msg, re.S)
                    if m:
                        q = m.group(0).strip()
                        # Save for input bridge; also show it in UI
                        def _post():
                            asyncio.create_task(cl.Message(content=q).send())
                        # update global
                        global LAST_QUESTION
                        LAST_QUESTION = q
                        _post()
            except Exception:
                pass

    ev_logger = logging.getLogger(EVENT_LOGGER_NAME)
    ev_logger.setLevel(logging.DEBUG)
    ev_logger.addHandler(ChainlitEventHandler())

    # 2) Create the canvas memory & expose update_file_tool under module name 'canvas'
    text_canvas_memory = TextCanvasMemory()
    update_file_tool = text_canvas_memory.get_update_file_tool()
    canvas = types.SimpleNamespace()
    canvas.update_file_tool = update_file_tool
    sys.modules["canvas"] = canvas

    # 3) Load the model client (same loader used in the notebook)
    model_client = load_model_client("azure")

    # 4) Create all agents from YAML configuration
    agents_config_path = os.path.join(LIB_PATH, "agents_config.yaml")
    # Preserve the same order as the notebook/team
    agent_order = [
        "planning_agent",
        "interviewer_agent",
        "summarizer_agent",
        "functional_spec_writer_agent",
        "functional_spec_checker_agent",
        "diagram_creator_agent",
        "mermaid_code_reviewer_agent",
        "terminate_agent",
    ]

    # Build list for creation that includes auxiliary agent_tools
    # (these are wrapped as tools by writer; they are not team speakers)
    agent_build_list = agent_order + [
        "use_case_agent",
        "glossary_agent",
        "user",
    ]

    def _to_text(content):
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
                    if "text" in c:
                        parts.append(str(c["text"]))
                    elif "content" in c:
                        parts.append(str(c["content"]))
                else:
                    txt = getattr(c, "text", None) or getattr(c, "content", None)
                    if isinstance(txt, str):
                        parts.append(txt)
            return "\n".join(parts)
        try:
            return str(content)
        except Exception:
            return ""

    def _extract_last_question(team_ref) -> str | None:
        """Try multiple internal paths to fetch the latest QUESTION from interviewer/summarizer."""
        candidates = []
        try:
            if hasattr(team_ref, "_message_buffer"):
                candidates.append(getattr(team_ref._message_buffer, "_messages", None))
                candidates.append(getattr(team_ref._message_buffer, "messages", None))
        except Exception:
            pass
        try:
            mgr = getattr(team_ref, "_manager", None)
            if mgr and hasattr(mgr, "_message_buffer"):
                candidates.append(getattr(mgr._message_buffer, "_messages", None))
                candidates.append(getattr(mgr._message_buffer, "messages", None))
        except Exception:
            pass

        for seq in candidates:
            if not seq:
                continue
            try:
                for m in reversed(list(seq)):
                    src = getattr(m, "source", getattr(m, "sender", None))
                    if src in ("interviewer_agent", "summarizer_agent"):
                        txt = _to_text(getattr(m, "content", "")).strip()
                        if txt:
                            if txt.startswith("QUESTION:"):
                                return txt
                            # In some cases, models prefix with roles; try to detect QUESTION line inside
                            qline = None
                            for line in txt.splitlines():
                                if line.strip().startswith("QUESTION:"):
                                    qline = line.strip()
                                    break
                            if qline:
                                return qline
            except Exception:
                continue
        return None

    async def chainlit_user_input(prompt: str | None = None, cancellation_token=None) -> str:
        """Collect user input via Chainlit UI. Compatible with (prompt, cancellation_token)."""
        # Try to surface the most recent QUESTION from the team buffer
        try:
            ctx = cl.user_session.get("team_ctx") or {}
            team_ref = ctx.get("team")
            if team_ref is not None:
                q = _extract_last_question(team_ref)
                if q:
                    await cl.Message(content=q).send()
        except Exception:
            pass

        # Echo any generic prompt from the agent as a secondary hint
        if prompt and prompt.strip():
            await cl.Message(content=prompt).send()
        # Keep asking until we have a non-empty answer or cancellation is requested
        while True:
            if cancellation_token is not None and getattr(cancellation_token, "is_canceled", False):
                raise asyncio.CancelledError()
            resp = await cl.AskUserMessage(content="Please enter your reply:", timeout=3600).send()
            text = None
            if resp:
                text = resp.get("content") or resp.get("output") or resp.get("text")
            answer = (text or "").strip()
            if answer:
                return answer
            # If empty, inform and retry
            await cl.Message(content="Input cannot be empty. Please reply with some text.").send()

    user, agents = await create_agents_from_config(
        agents_config_path,
        agent_names=agent_build_list,
        model_client=model_client,
        vector_memory=rag_vector_memory,
        canvas_memory=text_canvas_memory,
        input_func=chainlit_user_input,
    )

    member_agents = [agents[name] for name in agent_order if name in agents] + [user]

    # 5) Selector prompt (same text as the notebook)
    selector_prompt = (
        "Select an agent to perform task.\n\n"
        "{roles}\n\n"
        "Current conversation context:\n"
        "{history}\n\n"
        "Read the above conversation, then select an agent from {participants} to perform the next task.\n"
        "Make sure the planner agent has assigned tasks before other agents start working.\n"
        "Only select one agent.\n"
    )

    # 6) Termination condition (mirrors the notebook)
    termination = MaxMessageTermination(100000000) | TextMentionTermination("TERMINATE")

    # 7) Build the team with our custom selector
    team = SelectorGroupChat(
        member_agents,
        model_client=model_client,
        termination_condition=termination,
        selector_prompt=selector_prompt,
        allow_repeated_speaker=False,
        model_client_streaming=False,
        selector_func=selector_func,
    )

    # 8) Start the runtime
    runtime = SingleThreadedAgentRuntime()
    runtime.start()

    # Ask the user for the task (same semantic as the notebook)
    resp = await cl.AskUserMessage(content="Enter the task for the multi-agent workflow:", timeout=600).send()
    # Chainlit returns a dict-like payload; accept common keys
    task_text = None
    if resp:
        task_text = (
            resp.get("content")
            or resp.get("output")
            or resp.get("text")
        )
        if task_text:
            task_text = str(task_text).strip()

    if not task_text:
        await cl.Message(content="No task provided. Please send a message with your task to start.").send()
        # Defer to on_message to pick up the next user message as the task
        cl.user_session.set("team_ctx", {
            "team": team,
            "user": user,
            "initialized": True,
            "started": False,
        })
        return

    initial_task = task_text
    await cl.Message(content=f"Starting multi-agent workflow for: {initial_task}").send()

    # Run the team; this call performs the same orchestration as the notebook
    # Stash context for possible later interactions
    cl.user_session.set("team_ctx", {"team": team, "user": user, "initialized": True, "started": True})
    # Stream the team outputs so user can see questions/messages live
    try:
        streaming_by_agent: dict[str, cl.Message] = {}
        async for evt in team.run_stream(task=initial_task, cancellation_token=CancellationToken()):
            if isinstance(evt, ModelClientStreamingChunkEvent):
                src = evt.source or "agent"
                msg = streaming_by_agent.get(src)
                if msg is None:
                    msg = cl.Message(content="", author=src)
                    streaming_by_agent[src] = msg
                await msg.stream_token(evt.content)
            elif isinstance(evt, TextMessage):
                # finalize any streaming message for this source
                src = evt.source or "agent"
                msg = streaming_by_agent.pop(src, None)
                if msg is not None:
                    await msg.send()
                await cl.Message(content=str(evt.content), author=src).send()
            elif isinstance(evt, TaskResult):
                # finalize all streams
                for m in list(streaming_by_agent.values()):
                    await m.send()
                streaming_by_agent.clear()
                text = "Workflow complete."
                if evt.stop_reason:
                    text = f"Workflow complete. {evt.stop_reason}"
                await cl.Message(content=text).send()
            else:
                # ignore other event types for now
                pass
    except Exception as e:
        await cl.Message(content=f"Error during workflow: {e}").send()

    # Helpful links to generated artifacts
    convo = os.path.join(PROJECT_ROOT, "conversation", "interview.jsonl")
    spec = os.path.join(PROJECT_ROOT, "conversation", "functional_specification.md")
    mmd = os.path.join(PROJECT_ROOT, "conversation", "process_diagram.mmd")

    lines = [
        f"Conversation log: {convo}",
        f"Functional spec:  {spec}",
        f"Mermaid diagram:  {mmd}",
        "If terminate_agent executed, see experience/<SESSION_ID>/ for final deliverables.",
    ]
    await cl.Message(content="\n".join(lines)).send()


@cl.on_message
async def on_message(msg: cl.Message):
    """If no task was captured at start, treat the first user message as the task."""
    ctx = cl.user_session.get("team_ctx")
    if not ctx:
        return
    if ctx.get("started"):
        # Interactive interview replies are not wired yet
        await cl.Message(content="Thanks! I will enable interactive interview replies next.").send()
        return

    team = ctx.get("team")
    user = ctx.get("user")
    if not team or not user:
        return

    task_text = (msg.content or "").strip()
    if not task_text:
        await cl.Message(content="Please type a task to start.").send()
        return

    await cl.Message(content=f"Starting multi-agent workflow for: {task_text}").send()
    ctx["started"] = True
    cl.user_session.set("team_ctx", ctx)

    try:
        streaming_by_agent: dict[str, cl.Message] = {}
        async for evt in team.run_stream(task=task_text, cancellation_token=CancellationToken()):
            if isinstance(evt, ModelClientStreamingChunkEvent):
                src = evt.source or "agent"
                msg = streaming_by_agent.get(src)
                if msg is None:
                    msg = cl.Message(content="", author=src)
                    streaming_by_agent[src] = msg
                await msg.stream_token(evt.content)
            elif isinstance(evt, TextMessage):
                src = evt.source or "agent"
                msg = streaming_by_agent.pop(src, None)
                if msg is not None:
                    await msg.send()
                await cl.Message(content=str(evt.content), author=src).send()
            elif isinstance(evt, TaskResult):
                for m in list(streaming_by_agent.values()):
                    await m.send()
                streaming_by_agent.clear()
                text = "Workflow complete."
                if evt.stop_reason:
                    text = f"Workflow complete. {evt.stop_reason}"
                await cl.Message(content=text).send()
            else:
                pass
    except Exception as e:
        await cl.Message(content=f"Error during workflow: {e}").send()

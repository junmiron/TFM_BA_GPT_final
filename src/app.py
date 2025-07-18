import os
import sys
import yaml
import types
import chainlit as cl
from typing import List, cast
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage
from autogen_agentchat.base import TaskResult
from autogen_core import CancellationToken
from autogen_ext.memory.canvas import TextCanvasMemory

# Project import paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lib')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from agents_creator import create_agents_from_config
from rag_helpers import create_chromadb_memory
from model_loader import load_model_client

# CONFIG
AGENTS_CONFIG = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lib', 'agents_config.yaml'))
CHROMA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'chromadb_storage'))
COLLECTION_NAME = "business_analyst_rag"
MODEL_NAME = "azure"  # or "ollama" or "lmstudio"

selector_prompt = """
You are orchestrating a requirements engineering multi-agent team. Follow this strict workflow:

1. The planning_agent is assigned first to create a plan of action.
2. The interviewer_agent interviews the user to collect requirements, using RAG memory to inform the questions.
3. The summarizer_agent summarizes information gathered and hands off the summary to the user, asking if the user wishes to add more.
4. The doc_writter_agent uses the summary to draft the functional specification document.
5. The funct_spec_checker_agent verifies that nothing is missing from the functional specification document.
6. The diagram_creator_agent uses the functional spec document to generate a process diagram.
7. The mermaid_code_reviewer_agent reviews the diagram's code to ensure completeness.

Current conversation context:
{history}

Agent roles:
{roles}

Available agents: {participants}

Select the agent who should perform the next step in the workflow above, based strictly on the order provided. Only select the agent that is eligible for the current step (never skip steps). If an agent's task is done, select the next one. Only select one agent.

Your answer should be the name of the selected agent, and nothing else.
"""

# 1. Create the canvas memory and tool:
text_canvas_memory = TextCanvasMemory()
update_file_tool = text_canvas_memory.get_update_file_tool()

# 2. Register the tool as 'canvas.update_file_tool' for YAML import:
canvas = types.SimpleNamespace()
canvas.update_file_tool = update_file_tool
sys.modules['canvas'] = canvas  # This enables the tool import by your agent factory!

@cl.on_chat_start
async def start_chat() -> None:
    # Load model, vector memory (RAG), agents
    model_client = load_model_client(MODEL_NAME)
    vector_memory = await create_chromadb_memory(CHROMA_DIR, COLLECTION_NAME)
    with open(AGENTS_CONFIG, "r") as f:
        config_yaml = yaml.safe_load(f)
    agent_names = list(config_yaml.keys())

    # Create user_proxy and agents, pass canvas_memory!
    user_proxy, agents = await create_agents_from_config(
        yaml_path=AGENTS_CONFIG,
        agent_names=agent_names,
        model_client=model_client,
        vector_memory=vector_memory,
        canvas_memory=text_canvas_memory,
        input_func=lambda prompt: cl.AskUserMessage(content=prompt)
    )

    # Order agents (workflow order), user_proxy last
    agent_order = [
        "planning_agent",
        "interviewer_agent",
        "summarizer_agent",
        "doc_writter_agent",
        "funct_spec_checker_agent",
        "diagram_creator_agent",
        "mermaid_code_reviewer_agent"
    ]
    member_agents = [agents[name] for name in agent_order if name in agents] + [user_proxy]

    termination = MaxMessageTermination(100000000) | TextMentionTermination("TERMINATE")

    # --- Use SelectorGroupChat ---
    team = SelectorGroupChat(
        member_agents,
        model_client=model_client,
        termination_condition=termination,
        selector_prompt=selector_prompt,
        allow_repeated_speaker=True
    )

    cl.user_session.set("team", team)
    cl.user_session.set("user_proxy", user_proxy)
    cl.user_session.set("agents", agents)
    cl.user_session.set("prompt_history", "")

    await cl.Message(
        content="**BusinessAnalistGPT multi-agent system is ready!**\n\nPlease describe your project or requirements to begin the requirements interview process."
    ).send()

@cl.set_starters
async def set_starts() -> List[cl.Starter]:
    return [
        cl.Starter(label="Business process", message="I need an app to manage employee onboarding."),
        cl.Starter(label="Integration", message="We want to integrate our CRM with a new ticketing system."),
        cl.Starter(label="Automation", message="Automate monthly financial reporting from several sources.")
    ]

@cl.on_message
async def chat(message: cl.Message) -> None:
    team = cast(SelectorGroupChat, cl.user_session.get("team"))  # type: ignore

    streaming_response: cl.Message | None = None
    async for msg in team.run_stream(
        task=[TextMessage(content=message.content, source="user")],
        cancellation_token=CancellationToken(),
    ):
        if isinstance(msg, ModelClientStreamingChunkEvent):
            if streaming_response is None:
                streaming_response = cl.Message(content="", author=msg.source)
            await streaming_response.stream_token(msg.content)
        elif streaming_response is not None:
            await streaming_response.send()
            streaming_response = None
        elif isinstance(msg, TaskResult):
            final_message = "Task terminated."
            if msg.stop_reason:
                final_message += " " + msg.stop_reason
            await cl.Message(content=final_message).send()
        else:
            pass


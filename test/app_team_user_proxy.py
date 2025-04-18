from typing import List, cast
import os
import sys
import chainlit as cl
import yaml
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core import CancellationToken
from autogen_core.models import ChatCompletionClient

# Custom import
sys.path.append("C:/Master IA/TFM_BA_GPT/lib")
from agent_creator_helper import create_agent_interviewer
from rag_helper import create_chromadb_memory
from model_helper import get_model_client
from indexing_helpers import load_and_index_documents

async def user_input_func(prompt: str, cancellation_token: CancellationToken | None = None) -> str:
    """Get user input from the UI for the user proxy agent."""
    try:
        response = await cl.AskUserMessage(content=prompt).send()
    except TimeoutError:
        return "User did not provide any input within the time limit."
    if response:
        return response["output"]  # type: ignore
    else:
        return "User did not provide any input."


async def user_action_func(prompt: str, cancellation_token: CancellationToken | None = None) -> str:
    """Get user action from the UI for the user proxy agent."""
    try:
        response = await cl.AskActionMessage(
            content="Pick an action",
            actions=[
                cl.Action(name="approve", label="Approve", payload={"value": "approve"}),
                cl.Action(name="reject", label="Reject", payload={"value": "reject"}),
            ],
        ).send()
    except TimeoutError:
        return "User did not provide any input within the time limit."
    if response and response.get("payload"):  # type: ignore
        if response.get("payload").get("value") == "approve":  # type: ignore
            return "APPROVE."  # This is the termination condition.
        else:
            return "REJECT."
    else:
        return "User did not provide any input."


@cl.on_chat_start  # type: ignore
async def start_chat() -> None:

    # Create RAG
    # Config RAG path and names
    RAGDB_DIR = "C:/Master IA/TFM_BA_GPT/chromadb_storage"
    DOCS_DIR = "C:/Master IA/TFM_BA_GPT/data"
    COLLECTION_NAME = "rag_collection"

    # Create the vector memory for RAG.
    vector_memory = await create_chromadb_memory(RAGDB_DIR, COLLECTION_NAME)

    # Load and index documents
    if not os.path.exists(RAGDB_DIR):
        vector_memory.clear()
        print("Indexing documents... please wait.")
        load_and_index_documents(DOCS_DIR, vector_memory)

    # Load model configuration and create the model client.
    with open("C:/Master IA/TFM_BA_GPT/test/model_config_ollama.yml", "r") as f:
        model_config = yaml.safe_load(f)
    model_client = ChatCompletionClient.load_component(model_config)

    # Create the assistant agent and user proxy agent.
    user, assistant = await create_agent_interviewer(
        model_client,
        vector_memory,
        input_func=user_input_func
    )

    # Termination condition.
    termination = TextMentionTermination("exit", sources=["user"])

    # Chain the assistant, critic and user agents using RoundRobinGroupChat.
    group_chat = RoundRobinGroupChat(
        [assistant, user],
        termination_condition=termination
    )

    # Set the assistant agent in the user session.
    cl.user_session.set("prompt_history", "")  # type: ignore
    cl.user_session.set("team", group_chat)  # type: ignore


@cl.set_starters  # type: ignore
async def set_starts() -> List[cl.Starter]:
    return [
        cl.Starter(
            label="Clean code",
            message="What can you tell me about clean code.",
        ),
        cl.Starter(
            label="Bibliography",
            message="What is the best bibliography that anyone that wanst to make Clean Code should have.",
        ),
        cl.Starter(
            label="Write Code",
            message="Write a function that merge two list of numbers into single sorted list.",
        ),
    ]


@cl.on_message  # type: ignore
async def chat(message: cl.Message) -> None:
    # Get the team from the user session.
    team = cast(RoundRobinGroupChat, cl.user_session.get("team"))  # type: ignore
    # Streaming response message.
    streaming_response: cl.Message | None = None
    # Stream the messages from the team.
    async for msg in team.run_stream(
        task=[TextMessage(content=message.content, source="user")],
        cancellation_token=CancellationToken(),
    ):
        if isinstance(msg, ModelClientStreamingChunkEvent):
            # Stream the model client response to the user.
            if streaming_response is None:
                # Start a new streaming response.
                streaming_response = cl.Message(content="", author=msg.source)
            await streaming_response.stream_token(msg.content)
        elif streaming_response is not None:
            # Done streaming the model client response.
            # We can skip the current message as it is just the complete message
            # of the streaming response.
            await streaming_response.send()
            # Reset the streaming response so we won't enter this block again
            # until the next streaming response is complete.
            streaming_response = None
        elif isinstance(msg, TaskResult):
            # Send the task termination message.
            final_message = "Task terminated. "
            if msg.stop_reason:
                final_message += msg.stop_reason
            await cl.Message(content=final_message).send()
        else:
            # Skip all other message types.
            pass

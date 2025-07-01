import os
import sys
import asyncio
import chainlit as cl

# --- Path setup for lib and src modules ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lib')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from rag_helpers import (
    create_chromadb_memory,
    load_and_index_documents,
    load_and_index_web_page,
    load_index_state,
    save_index_state,
)
from agents_creator import create_agents_from_config
from model_loader import load_model_client
from autogen.agentchat.groupchat import SelectorGroupChat, GroupChatManager

from pathlib import Path

# --- CONFIG ---
CHROMA_DIR = "../chromadb_storage"
DOCS_DIR = "../data"
COLLECTION_NAME = "rag_collection"
STATE_FILE = "../index_state.json"
AGENT_CONFIG_PATH = "../lib/agents_config.yaml"
AGENT_NAMES = [
    "user_proxy",
    "interviewer",
    "spec_verifier_and_doc_writter",
    "diagram_creator",
    # Add other agents if present in config
]
SITES = [
    "https://www.morebusiness.com/business-analyst-interview-questions/",
    "https://www.requiment.com/the-most-asked-questions-about-requirements-gathering/",
    "https://practicalanalyst.com/requirements-elicitation-most-valuable-questions/",
    "https://www.modernanalyst.com/Resources/Articles/tabid/115/ID/179/8-Questions-Every-Business-Analyst-Should-Ask.aspx",
    "https://www.requiment.com/business-analyst-requirements-gathering-interview-questions-answers/",
]

# --- GLOBAL shared vector_memory
vector_memory = None

async def ensure_rag_index():
    """
    Index new documents/URLs only if not previously indexed.
    """
    state = load_index_state(STATE_FILE)
    already_indexed_files = set(state.get("indexed_files", []))
    already_indexed_urls = set(state.get("indexed_urls", []))

    global vector_memory
    vector_memory = await create_chromadb_memory(CHROMA_DIR, COLLECTION_NAME)

    all_files = {
        str(f.relative_to(DOCS_DIR)) for f in Path(DOCS_DIR).rglob("*")
        if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".txt"}
    }
    new_files = all_files - already_indexed_files
    new_urls = set(SITES) - already_indexed_urls

    if new_files or new_urls:
        print("🔄 Indexing new content...")
        if new_files:
            await load_and_index_documents(DOCS_DIR, vector_memory)
            state["indexed_files"] = sorted(list(all_files))
            print(f"✅ Indexed documents in {DOCS_DIR}.")
        if new_urls:
            await load_and_index_web_page(list(new_urls), vector_memory)
            state["indexed_urls"] = sorted(list(already_indexed_urls.union(new_urls)))
            print("✅ Indexed web pages.")
        save_index_state(state, STATE_FILE)
    else:
        print("✅ All documents and URLs are already indexed.")

@cl.on_chat_start
async def start():
    # Interactive model backend selection
    backends = [
        {"label": "Azure OpenAI", "value": "azure"},
        {"label": "Ollama", "value": "ollama"},
        {"label": "LMStudio", "value": "lmstudio"},
    ]
    answer = await cl.AskUserMessage(
        content="👋 Welcome! Which model backend would you like to use for your session?",
        options=[b["label"] for b in backends],
        type="select"
    ).send()
    selected_backend = next(b["value"] for b in backends if b["label"] == answer)
    cl.user_session.set("selected_backend", selected_backend)

    await ensure_rag_index()
    model_client = load_model_client(selected_backend)

    user_proxy, agents = await create_agents_from_config(
        yaml_path=AGENT_CONFIG_PATH,
        agent_names=AGENT_NAMES,
        model_client=model_client,
        vector_memory=vector_memory,
    )
    cl.user_session.set("user_proxy", user_proxy)
    cl.user_session.set("agents", agents)

    selector = SelectorGroupChat(
        agents=[agents[a] for a in AGENT_NAMES if a != "user_proxy"],
        max_round=20,
        messages=[],
    )
    manager = GroupChatManager(groupchat=selector, user_proxy=user_proxy)
    cl.user_session.set("group_manager", manager)

    await cl.Message(
        f"Business Analyst RAG Bot is ready! (Model backend: {selected_backend.title()})"
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    user_proxy = cl.user_session.get("user_proxy")
    manager = cl.user_session.get("group_manager")
    user_proxy.input_func = lambda: message.content
    await manager.run()

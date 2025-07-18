"""
This module provides helper functions for dynamically creating and managing agents
using configuration from a YAML file.

The primary function, `create_agents_from_config`, loads agent definitions from
a YAML configuration file and instantiates both assistant agents and a user proxy agent.
It supports memory attachment, model streaming, and automatic tool loading via dotted paths.

This factory pattern allows flexible orchestration of multi-agent workflows using
AutoGen 0.6 agents and supports extensions like RAG, PDF summarization, diagram generation,
and document validation.

Usage Example:
--------------
agents_config.yaml:

summarizer:
  type: assistant
  description: An agent that summarizes information from PDFs.
  system_message: |
    You summarize documents.
  tools:
    - agents_tools_helpers.read_pdf_file
  stream: true
  use_memory: true

Python:

from agents_creator import create_agents_from_config

agent_names = ["user_proxy", "summarizer"]

user_proxy, agents = await create_agents_from_config(
    yaml_path="agents_config.yaml",
    agent_names=agent_names,
    model_client=model_client,
    vector_memory=vector_memory
)

summarizer_agent = agents["summarizer"]
"""

import yaml
import importlib
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

def import_from_string(dotted_path: str):
    try:
        module_path, attr = dotted_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"Could not import '{dotted_path}': {e}")

def load_agent_config(yaml_path: str) -> dict:
    with open(yaml_path, "r") as f:
        return yaml.safe_load(f)

def inject_team_members(system_message: str, agent_names: list, planning_agent_name: str = "planning_agent"):
    team_members = [name for name in agent_names if name != planning_agent_name and name != "user_proxy"]
    formatted_list = "\n".join(f"  - {member}" for member in team_members)
    return system_message.replace("Your team members are:", f"Your team members are:\n{formatted_list}")

def resolve_memory(cfg, vector_memory, canvas_memory):
    mem_type = str(cfg.get("use_memory", "false")).lower()
    if mem_type == "vector_memory":
        return [vector_memory]
    elif mem_type == "canvas_memory":
        return [canvas_memory]
    else:
        return None

async def create_agents_from_config(
    yaml_path: str,
    agent_names: list,
    model_client=None,
    vector_memory=None,
    canvas_memory=None,
    input_func=input
):
    config = load_agent_config(yaml_path)

    user_proxy = None
    agents = {}

    for name in agent_names:
        if name not in config:
            raise ValueError(f"Agent '{name}' is not defined in the config file.")

        cfg = config[name]
        agent_type = cfg.get("type", "assistant")

        if agent_type == "user_proxy":
            user_proxy = UserProxyAgent(
                name=name,
                description=cfg.get("description", ""),
                input_func=input_func
            )
        elif agent_type == "assistant":
            tool_paths = cfg.get("tools", [])
            tools = [import_from_string(path) for path in tool_paths]

            # Inject team members into planning_agent's system_message
            system_message = cfg.get("system_message", "")
            if name == "planning_agent":
                system_message = inject_team_members(system_message, agent_names)

            agent_memory = resolve_memory(cfg, vector_memory, canvas_memory)

            agents[name] = AssistantAgent(
                name=name,
                description=cfg.get("description", ""),
                model_client=model_client,
                memory=agent_memory,
                tools=tools if tools else None,
                system_message=system_message,
                model_client_stream=cfg.get("stream", False)
            )
        else:
            raise ValueError(f"Unsupported agent type: {agent_type}")

    return user_proxy, agents


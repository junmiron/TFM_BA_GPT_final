import yaml
import importlib
from typing import Any, Iterable, List, Dict, Tuple
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.tools import AgentTool  # <-- NEW
from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools
from inspect import isawaitable

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
    team_members = [name for name in agent_names if name != planning_agent_name and name != "user"]
    if "Your team members are:" in system_message:
        formatted_list = "\n".join(f"  - {member}" for member in team_members)
        return system_message.replace("Your team members are:", f"Your team members are:\n{formatted_list}")
    return system_message

def resolve_memory(cfg, vector_memory, canvas_memory):
    mem_type = str(cfg.get("use_memory", "false")).lower()
    if mem_type == "vector_memory" and vector_memory:
        return [vector_memory]
    elif mem_type == "canvas_memory" and canvas_memory:
        return [canvas_memory]
    else:
        return None

# -------------------- NEW helpers --------------------

def _normalize_tool_objects(obj: Any) -> List[Any]:
    """Return a list of tool objects from an imported object/factory."""
    if obj is None:
        return []
    if isinstance(obj, (list, tuple, set)):
        return list(obj)
    return [obj]

def _load_function_tools(paths: Iterable[str]) -> List[Any]:
    """Load 'tools:' exactly as before: dotted paths to callable function tools."""
    return [import_from_string(p) for p in (paths or [])]

async def _aload_mcp_tools(specs):
    """
    Load 'mcp_tools:' entries. Each entry may be:
      - a dotted string to an awaitable factory that returns a tool or list of tools
      - a dotted string to a tool or list of tools
      - a mapping: { import: "pkg.module.factory_or_object", kwargs: {...} }
    """
    tools = []
    for entry in (specs or []):
        if isinstance(entry, str):
            target = import_from_string(entry)
            produced = target() if callable(target) else target
            if isawaitable(produced):
                produced = await produced
            tools.extend(_normalize_tool_objects(produced))
        elif isinstance(entry, dict) and "import" in entry:
            target = import_from_string(entry["import"])
            kwargs = entry.get("kwargs", {}) or {}
            produced = target(**kwargs) if callable(target) else target
            if isawaitable(produced):
                produced = await produced
            tools.extend(_normalize_tool_objects(produced))
        else:
            raise ValueError(f"Invalid mcp_tools entry: {entry!r}")
    return tools

def _rebuild_agent_with_tools(old: AssistantAgent, extra_tools: List[Any]) -> AssistantAgent:
    """Re-create an AssistantAgent with old properties + new tools (preserves everything else)."""
    existing = getattr(old, "_tools", []) or []
    combined_tools = list(existing) + list(extra_tools)

    # Extract the raw system message text if present
    system_message_text = ""
    if hasattr(old, "_system_messages") and old._system_messages:
        try:
            system_message_text = old._system_messages[0].content
        except Exception:
            system_message_text = ""

    return AssistantAgent(
        name=old._name,
        description=old._description,
        model_client=old._model_client,
        memory=old._memory,
        tools=combined_tools or None,
        reflect_on_tool_use=old._reflect_on_tool_use,
        system_message=system_message_text,
        model_client_stream=old._model_client_stream,
    )

# -----------------------------------------------------

async def create_agents_from_config(
    yaml_path: str,
    agent_names: list,
    model_client=None,
    vector_memory=None,
    canvas_memory=None,
    input_func=input
):
    """
    Extended factory:
      - tools: dotted function tools (unchanged)
      - agent_tools: list of other agent names to wrap as tools
      - mcp_tools: list of dotted objects/factories or {import, kwargs} entries
    """
    config = load_agent_config(yaml_path)

    user = None
    agents: Dict[str, AssistantAgent] = {}

    # --- Pass 1: build all agents with function + MCP tools only ---
    for name in agent_names:
        if name not in config:
            raise ValueError(f"Agent '{name}' is not defined in the config file.")

        cfg = config[name]
        agent_type = cfg.get("type", "assistant")

        if agent_type == "user_proxy":
            user = UserProxyAgent(
                name=name,
                description=cfg.get("description", ""),
                input_func=input_func
            )
            continue

        if agent_type != "assistant":
            raise ValueError(f"Unsupported agent type: {agent_type}")

        # Build base tool list (function tools + mcp tools)
        fn_tools = _load_function_tools(cfg.get("tools", []))
        mcp_tools = await _aload_mcp_tools(cfg.get("mcp_tools", []))
        base_tools = [*fn_tools, *mcp_tools]

        # Inject team members into planning_agent
        system_message = cfg.get("system_message", "")
        if name == "planning_agent":
            system_message = inject_team_members(system_message, agent_names)

        agent_memory = resolve_memory(cfg, vector_memory, canvas_memory)

        agents[name] = AssistantAgent(
            name=name,
            description=cfg.get("description", ""),
            model_client=model_client,
            memory=agent_memory,
            tools=base_tools or None,
            reflect_on_tool_use=cfg.get("reflect_on_tool_use", False),
            system_message=system_message,
            model_client_stream=cfg.get("stream", False),
        )

    # --- Pass 2: attach agent_tools by wrapping referenced agents ---
    for name in agent_names:
        cfg = config[name]
        if cfg.get("type", "assistant") != "assistant":
            continue

        wanted_agent_tools = cfg.get("agent_tools", []) or []
        if not wanted_agent_tools:
            continue

        missing = [a for a in wanted_agent_tools if a not in agents]
        if missing:
            raise ValueError(
                f"Agent '{name}' declares agent_tools referencing unknown agents: {missing}. "
                f"Make sure they are listed in agent_names and created in pass 1."
            )

        wrappers = [AgentTool(agent=agents[a]) for a in wanted_agent_tools]
        agents[name] = _rebuild_agent_with_tools(agents[name], wrappers)

    return user, agents

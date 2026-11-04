"""Model client loader.

Every profile is configured in src/model_config_<name>.yaml: provider, model,
host and generation limits. No profile YAML carries a secret - the API key is
always read from the environment (or the project .env) by load_model_client().

Pick the lanes in .env:
  MODEL_CLIENT        - profile used by the reasoning agents
  MODEL_CLIENT_TOOLS  - profile used by the tool-calling agents
  HUMAN_MODEL         - profile used by the simulated stakeholder lane
"""

import os
from pathlib import Path

import yaml
from autogen_core.models import ChatCompletionClient

try:  # imported as part of a package (tests) or top-level (app2.py adds src/ to sys.path)
    from .tool_call_recovery import ToolCallRecoveryClient
    from .rate_limit_retry import RateLimitRetryClient
except ImportError:
    from tool_call_recovery import ToolCallRecoveryClient
    from rate_limit_retry import RateLimitRetryClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# profile name -> (yaml file, env var holding its key). A key env var of None
# means the backend is a local server that needs no credential.
PROFILES = {
    "openai": ("model_config_openai.yaml", "OPENAI_API_KEY"),
    "openai_npt": ("model_config_openai_npt.yaml", "OPENAI_API_KEY"),
    "azure": ("model_config_azure.yaml", "AZURE_OPENAI_API_KEY"),
    "groq": ("model_config_groq.yaml", "GROQ_API_KEY"),
    "hugging": ("model_config_hugging.yaml", "HF_TOKEN"),
    "github": ("model_config_github.yaml", "GITHUB_TOKEN"),
    "opencode": ("model_config_opencode.yaml", "OPENCODE_GO_API_KEY"),
    "ollama": ("model_config_ollama.yaml", None),
    "lmstudio": ("model_config_lmstudio.yaml", None),
    "strata": ("model_config_strata.yaml", None),
    "onnx": ("model_config_onnx.yaml", None),
}

# Spellings people naturally type, mapped to the canonical profile name.
PROFILE_ALIASES = {
    "opencode-go": "opencode",
    "opencode_go": "opencode",
    "opencode go": "opencode",
    "open-code": "opencode",
    "lm-studio": "lmstudio",
    "huggingface": "hugging",
    "hf": "hugging",
    "strata-local": "strata",
}

# Kept for callers that only need name -> file.
CONFIG_FILES = {name: filename for name, (filename, _) in PROFILES.items()}

# Local servers can be redirected with <PROFILE>_BASE_URL / <PROFILE>_MODEL
# without editing the YAML (used by the e2e harnesses).
LOCAL_PROFILES = {name for name, (_, key_env) in PROFILES.items() if key_env is None}


def available_profiles() -> list[str]:
    """Every profile the selector accepts."""
    return sorted(PROFILES)


def resolve_profile_name(model_name: str) -> str:
    """Canonicalise a profile name, raising ValueError with the full list."""
    name = str(model_name or "").strip().lower()
    name = PROFILE_ALIASES.get(name, name)
    if name not in PROFILES:
        raise ValueError(
            f"Unknown model profile '{model_name}'. "
            f"Choose one of: {', '.join(available_profiles())}"
        )
    return name


def _load_dotenv() -> None:
    """Load the project .env if python-dotenv is installed and the file exists."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)


# Load .env at import: callers read MODEL_CLIENT / MODEL_CLIENT_TOOLS from the
# environment *before* calling load_model_client(), so a lazy load inside the
# function means the profile in .env is silently ignored.
_load_dotenv()


def resolve_api_key(model_name: str, config: dict) -> dict:
    """Fill `api_key` from the environment, never from a hard-coded YAML value.

    Remote profiles must have their key in the environment. Local profiles get a
    harmless placeholder: the OpenAI-compatible client requires an api_key, but a
    local server never checks it.
    """
    _, key_env = PROFILES[model_name]

    if key_env is None:
        local_key = os.getenv(f"{model_name.upper()}_API_KEY")
        config["api_key"] = local_key or "not-needed"
        return config

    env_key = os.getenv(key_env)
    yaml_key = config.get("api_key")
    if env_key:
        config["api_key"] = env_key
    elif not yaml_key or "REPLACE" in str(yaml_key):
        raise RuntimeError(
            f"No API key for profile '{model_name}'. "
            f"Set {key_env} (environment or .env) "
            "or copy src/model_config_template.yaml."
        )
    return config


def apply_env_endpoint(model_name: str, config: dict) -> dict:
    """Optional override: <PROFILE>_BASE_URL / <PROFILE>_MODEL beat the YAML.

    The YAML is the source of truth; this only exists so a test or a second
    machine can point at another host without editing the profile file.
    """
    upper = model_name.upper()
    host = os.getenv(f"{upper}_BASE_URL") or os.getenv(f"{upper}_HOST")
    if host:
        # Ollama's client takes `host`; every OpenAI-compatible client takes `base_url`.
        config["host" if "host" in config else "base_url"] = host
    model = os.getenv(f"{upper}_MODEL")
    if model:
        config["model"] = model
    return config


def load_model_client(model_name: str | None = None) -> ChatCompletionClient:
    """Return an AutoGen ChatCompletionClient for the given profile.

    model_name defaults to the MODEL_CLIENT env var, then "openai".
    """
    _load_dotenv()

    model_name = resolve_profile_name(model_name or os.getenv("MODEL_CLIENT", "openai"))

    config_path = SRC_DIR / PROFILES[model_name][0]
    if not config_path.exists():
        raise FileNotFoundError(
            f"Model config '{config_path}' is missing. "
            "Copy src/model_config_template.yaml and fill it in."
        )

    with config_path.open("r", encoding="utf-8") as f:
        component = yaml.safe_load(f)

    config = component.get("config", {})

    # Host and model come from the YAML; env vars may override them.
    apply_env_endpoint(model_name, config)

    # Inject the API key from the environment rather than hard-coding it.
    resolve_api_key(model_name, config)

    client = ChatCompletionClient.load_component(component)
    # Local servers (LM Studio / llama.cpp + Qwen3) sometimes return tool calls
    # as plain text; the wrapper recovers them into structured FunctionCalls.
    client = ToolCallRecoveryClient(client)

    # Remote providers are rate-limited (Groq free tier: 8000 tokens/min for
    # every model). A 429 inside a group chat aborts the whole run, so retry
    # with backoff instead of letting it bubble up.
    if PROFILES[model_name][1] is not None:
        client = RateLimitRetryClient(client)
    return client

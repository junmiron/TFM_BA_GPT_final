"""Model client loader.

Model configs live in src/model_config_<name>.yaml and carry no secrets:
the API key is injected from the environment (or a local .env file) by
load_model_client().
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

# Env var that supplies the key for each provider profile.
API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "openai_npt": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "hugging": "HF_TOKEN",
    "github": "GITHUB_TOKEN",
    "opencode": "OPENCODE_GO_API_KEY",
    # ollama / lmstudio / strata / onnx are local servers and need no real key
}

CONFIG_FILES = {
    "azure": "model_config_azure.yaml",
    "ollama": "model_config_ollama.yaml",
    "lmstudio": "model_config_lmstudio.yaml",
    "strata": "model_config_strata.yaml",
    "groq": "model_config_groq.yaml",
    "opencode": "model_config_opencode.yaml",
    "hugging": "model_config_hugging.yaml",
    "github": "model_config_github.yaml",
    "onnx": "model_config_onnx.yaml",
    "openai": "model_config_openai.yaml",
    "openai_npt": "model_config_openai_npt.yaml",
}

# Profiles whose base_url / model can be redirected from the environment,
# so a different host or model can be used without editing the YAML.
LOCAL_ENDPOINT_ENV = {
    "lmstudio": ("LMSTUDIO_BASE_URL", "LMSTUDIO_MODEL"),
    "strata": ("STRATA_BASE_URL", "STRATA_MODEL"),
}


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

    The env var wins over the YAML key. Previously the YAML key was used
    verbatim whenever present, so a stale key in the config silently beat the
    valid key in .env.
    """
    key_env = API_KEY_ENV.get(model_name)
    if not key_env or "api_key" not in config:
        return config

    env_key = os.getenv(key_env)
    yaml_key = config.get("api_key")
    if env_key:
        config["api_key"] = env_key
    elif not yaml_key or "REPLACE" in str(yaml_key):
        raise RuntimeError(
            f"No API key for profile '{model_name}'. "
            f"Set {key_env} (environment or .env) "
            "or use src/model_config_template.yaml."
        )
    return config


def load_model_client(model_name: str | None = None) -> ChatCompletionClient:
    """Return an AutoGen ChatCompletionClient for the given profile.

    model_name defaults to the MODEL_CLIENT env var, then "openai".
    """
    _load_dotenv()

    model_name = (model_name or os.getenv("MODEL_CLIENT", "openai")).strip().lower()
    if model_name not in CONFIG_FILES:
        raise ValueError(
            f"Unknown model_name '{model_name}'. Must be one of {sorted(CONFIG_FILES)}"
        )

    config_path = SRC_DIR / CONFIG_FILES[model_name]
    if not config_path.exists():
        raise FileNotFoundError(
            f"Model config '{config_path}' is missing. "
            "Copy src/model_config_template.yaml and fill it in."
        )

    with config_path.open("r", encoding="utf-8") as f:
        component = yaml.safe_load(f)

    config = component.get("config", {})
    provider = component.get("provider", "")

    # Allow local servers (LM Studio / Strata / llama.cpp) to be redirected via
    # env so tests and alternate hosts can point at a different endpoint without
    # editing the YAML. Example: STRATA_BASE_URL=http://127.0.0.1:47831/v1
    env_names = LOCAL_ENDPOINT_ENV.get(model_name)
    if env_names:
        base_url_env, model_env = env_names
        base_url = os.getenv(base_url_env)
        if base_url:
            config["base_url"] = base_url
        model = os.getenv(model_env)
        if model:
            config["model"] = model

    # Inject the API key from the environment rather than hard-coding it.
    resolve_api_key(model_name, config)

    client = ChatCompletionClient.load_component(component)
    # Local servers (LM Studio / llama.cpp + Qwen3) sometimes return tool calls
    # as plain text; the wrapper recovers them into structured FunctionCalls.
    client = ToolCallRecoveryClient(client)

    # Remote providers are rate-limited (Groq free tier: 8000 tokens/min for
    # every model). A 429 inside a group chat aborts the whole run, so retry
    # with backoff instead of letting it bubble up.
    if model_name in API_KEY_ENV:
        client = RateLimitRetryClient(client)
    return client

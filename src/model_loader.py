"""Model client loader.

Model configs live in src/model_config_<name>.yaml and carry no secrets:
the API key is injected from the environment (or a local .env file) by
load_model_client().
"""

import os
from pathlib import Path

import yaml
from autogen_core.models import ChatCompletionClient

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
    # ollama / lmstudio / onnx are local servers and need no real key
}

CONFIG_FILES = {
    "azure": "model_config_azure.yaml",
    "ollama": "model_config_ollama.yaml",
    "lmstudio": "model_config_lmstudio.yaml",
    "groq": "model_config_groq.yaml",
    "hugging": "model_config_hugging.yaml",
    "github": "model_config_github.yaml",
    "onnx": "model_config_onnx.yaml",
    "openai": "model_config_openai.yaml",
    "openai_npt": "model_config_openai_npt.yaml",
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

    # Inject the API key from the environment rather than hard-coding it.
    key_env = API_KEY_ENV.get(model_name)
    if key_env and "api_key" in provider:
        api_key = config.get("api_key")
        if not api_key or "REPLACE" in str(api_key):
            api_key = os.getenv(key_env)
            if not api_key:
                raise RuntimeError(
                    f"No API key for profile '{model_name}'. "
                    f"Set {key_env} (environment or .env) "
                    "or use src/model_config_template.yaml."
                )
            config["api_key"] = api_key

    return ChatCompletionClient.load_component(component)

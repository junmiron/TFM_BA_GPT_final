import os
import yaml
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.ollama import OllamaChatCompletionClient
from autogen_ext.auth.azure import AzureTokenProvider
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

# Import your actual model client class; replace with correct import as needed
# For example:
# from autogen.oai.client import ChatCompletionClient
from autogen.oai.client import ChatCompletionClient

def get_base_path():
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    except NameError:
        return os.path.abspath(os.path.join(os.getcwd(), ".."))

def load_model_client(model_name: str = "azure"):
    """
    Load the model client based on the model name.
    Args:
        model_name: "azure", "ollama", or "lmstudio"
    Returns:
        model_client instance
    """
    base_path = get_base_path()
    configs = {
        "azure": os.path.join(base_path, "src", "model_config_azure.yaml"),
        "ollama": os.path.join(base_path, "src", "model_config_ollama.yaml"),
        "lmstudio": os.path.join(base_path, "src", "model_config_lmstudio.yaml"),
    }
    model_name = model_name.lower()
    if model_name not in configs:
        raise ValueError(f"Unknown model_name '{model_name}'. Must be one of {list(configs.keys())}")
    config_path = configs[model_name]

    with open(config_path, "r") as f:
        model_config = yaml.safe_load(f)
    return ChatCompletionClient.load_component(model_config)

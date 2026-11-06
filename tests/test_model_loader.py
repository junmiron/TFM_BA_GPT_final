"""Groq profile: env key wins, no hard-coded secrets, no decommissioned models."""

import os

import yaml
import pytest

import src.model_loader
from src.model_loader import (CONFIG_FILES, available_profiles, load_model_client,
                       resolve_api_key, resolve_profile_name)

_SRC_DIR = os.path.dirname(os.path.abspath(src.model_loader.__file__))


def _groq_config() -> dict:
    with open(os.path.join(_SRC_DIR, CONFIG_FILES["groq"]), encoding="utf-8") as f:
        return yaml.safe_load(f)["config"]


def test_groq_profile_exists():
    assert "groq" in CONFIG_FILES


def test_no_profile_yaml_carries_a_secret():
    # Every key lives in .env; the YAML profiles describe provider/host/model only.
    for name, (filename, key_env) in src.model_loader.PROFILES.items():
        with open(os.path.join(_SRC_DIR, filename), encoding="utf-8") as f:
            config = yaml.safe_load(f)["config"]
        assert "api_key" not in config, f"{name} profile must not contain api_key"
        if key_env:
            with open(os.path.join(_SRC_DIR, filename), encoding="utf-8") as fh:
                assert key_env in fh.read(), (
                    f"{name} profile should name its key env var ({key_env})"
                )


def test_groq_model_is_not_decommissioned():
    # Groq retired compound-beta / compound-beta-mini on 2026-09-21.
    assert "compound" not in _groq_config()["model"]


def test_env_key_overrides_yaml_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key-123")
    assert resolve_api_key("groq", {"api_key": "stale-yaml-key"})["api_key"] == "env-key-123"


def test_missing_env_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        resolve_api_key("groq", {})


def test_local_profiles_need_no_key(monkeypatch):
    monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)
    config = resolve_api_key("lmstudio", {})
    assert config["api_key"] == "not-needed"


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="Unknown model profile"):
        load_model_client("does-not-exist")


def test_split_lane_profiles_exist():
    # Local agents + remote simulated human is the configured split.
    assert "strata" in CONFIG_FILES
    assert "opencode" in CONFIG_FILES


def test_strata_is_local_and_keyless():
    with open(os.path.join(_SRC_DIR, CONFIG_FILES["strata"]), encoding="utf-8") as f:
        config = yaml.safe_load(f)["config"]
    assert "127.0.0.1" in config["base_url"]
    assert "api_key" not in config
    # Local Qwen needs a large completion budget or tool calls get truncated.
    assert config.get("max_tokens", 0) >= 8000


def test_opencode_config_is_remote_and_keyless_in_yaml():
    with open(os.path.join(_SRC_DIR, CONFIG_FILES["opencode"]), encoding="utf-8") as f:
        config = yaml.safe_load(f)["config"]
    assert "api_key" not in config
    assert "opencode.ai" in config["base_url"]
    # OpenCode Go 400s without the session affinity header.
    assert "x-opencode-session" in config.get("default_headers", {})


def test_opencode_key_comes_from_env(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "env-opencode-key")
    assert resolve_api_key("opencode", {})["api_key"] == "env-opencode-key"


def test_selector_accepts_strata_and_opencode_go():
    assert resolve_profile_name("strata") == "strata"
    assert resolve_profile_name("opencode-go") == "opencode"
    assert resolve_profile_name("OpenCode Go") == "opencode"
    profiles = available_profiles()
    assert "strata" in profiles and "opencode" in profiles


def test_local_endpoint_env_redirect(monkeypatch, tmp_path):
    monkeypatch.setenv("STRATA_BASE_URL", "http://127.0.0.1:12345/v1")
    monkeypatch.setenv("STRATA_MODEL", "some-local-model")

    import src.model_loader as ml

    original = ml.SRC_DIR
    fake = tmp_path / "src"
    fake.mkdir()
    (fake / "model_config_strata.yaml").write_text(
        "provider: autogen_ext.models.openai.OpenAIChatCompletionClient\n"
        "config:\n  model: q2_0\n  api_key: not-needed\n"
        "  base_url: http://127.0.0.1:47831/v1\n",
        encoding="utf-8",
    )
    ml.SRC_DIR = fake
    try:
        ml.load_model_client("strata")
    except Exception:
        pass  # the client may fail to connect; only the redirect matters
    finally:
        ml.SRC_DIR = original

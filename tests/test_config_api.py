"""Configuration API tests (Feature 8): masking, whitelist, validation, .env round-trip."""

import json
import os

import pytest
from fastapi.testclient import TestClient

import server.api as api


def test_config_get_never_echoes_key_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-do-not-return")
    body = TestClient(api.app).get("/api/config").json()
    assert "super-secret-do-not-return" not in json.dumps(body)
    entry = next(k for k in body["keys"] if k["env"] == "OPENAI_API_KEY")
    assert entry["present"] is True
    assert set(entry) == {"env", "present"}


def test_config_put_updates_env_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "MODEL_CLIENT=openai\n# a comment line\nUNTOUCHED=yes\n",
        encoding="utf-8",
    )
    c = TestClient(api.app)
    r = c.put(
        "/api/config",
        json={"MODEL_CLIENT": "groq", "UI_SHOW_ARTIFACTS": False, "MAX_MESSAGES": 40},
    )
    assert r.status_code == 200
    assert os.environ["MODEL_CLIENT"] == "groq"
    assert os.environ["UI_SHOW_ARTIFACTS"] == "false"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "MODEL_CLIENT=groq" in env_text
    assert "UI_SHOW_ARTIFACTS=false" in env_text
    assert "UNTOUCHED=yes" in env_text  # non-whitelisted lines survive
    assert "# a comment line" in env_text
    # restore what the test changed so other tests are unaffected
    monkeypatch.delenv("MODEL_CLIENT", raising=False)
    monkeypatch.delenv("UI_SHOW_ARTIFACTS", raising=False)
    monkeypatch.delenv("MAX_MESSAGES", raising=False)


def test_config_put_rejects_outside_whitelist():
    c = TestClient(api.app)
    assert c.put("/api/config", json={"PATH": "/tmp"}).status_code == 400
    assert c.put("/api/config", json={"MODEL_CLIENT": "not-a-profile"}).status_code == 400
    assert c.put("/api/config", json={"MAX_MESSAGES": 99999}).status_code == 400
    assert c.put("/api/config", json={"SIMULATE_HUMAN": "maybe"}).status_code == 400
    assert c.put("/api/config", json={"OPENAI_API_KEY": ""}).status_code == 400
    assert c.put("/api/config", json={"NOTEXISTING_X_MODEL": "x"}).status_code == 400


def test_config_put_accepts_aliases_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)  # never touch the real .env
    c = TestClient(api.app)
    r = c.put("/api/config", json={"MODEL_CLIENT_TOOLS": "opencode-go", "STRATA_MODEL": "q2_0"})
    assert r.status_code == 200
    assert os.environ["MODEL_CLIENT_TOOLS"] == "opencode"
    assert os.environ["STRATA_MODEL"] == "q2_0"
    # Clearing the override persists an empty value, so model_loader falls back to YAML.
    cleared = c.put("/api/config", json={"STRATA_MODEL": ""})
    assert cleared.status_code == 200
    assert os.environ["STRATA_MODEL"] == ""
    monkeypatch.delenv("MODEL_CLIENT_TOOLS", raising=False)
    monkeypatch.delenv("STRATA_MODEL", raising=False)

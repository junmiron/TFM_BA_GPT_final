"""Release smoke tests for the BA-GPT pipeline.

Run with:  python -m pytest -q
"""

import asyncio
import json
import sys
from pathlib import Path

from autogen_agentchat.messages import TextMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agents_tools_helpers import (  # noqa: E402
    save_conversation_to_jsonl,
    write_md_file_tool,
    read_md_file_tool,
    write_mermaid_to_file_tool,
    move_file_tool,
    ensure_dir_tool,
    selector_func,
    PLANNING,
    INTERVIEWER,
    WRITER,
    TERMINATE,
)


def _msg(source: str, content: str) -> TextMessage:
    return TextMessage(content=content, source=source)


def test_jsonl_pair_is_written_atomically(tmp_path, monkeypatch):
    import agents_tools_helpers as helpers

    target = tmp_path / "interview.jsonl"
    monkeypatch.setattr(helpers, "_PROJECT_ROOT", tmp_path)

    result = save_conversation_to_jsonl(
        [
            {"speaker": "interviewer", "message": "QUESTION: What is the scope?", "subject": "Scope", "q_index": 1},
            {"speaker": "user", "message": "All of it", "subject": "Scope", "q_index": 1},
        ],
        file_path="interview.jsonl",
        session_id="sess-test",
    )
    assert "Saved 2 record" in result

    lines = [json.loads(l) for l in target.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["_meta"]["session_id"] == "sess-test"
    assert lines[1]["speaker"] == "interviewer"
    assert lines[2]["speaker"] == "user"
    assert "timestamp" in lines[1]


def test_markdown_round_trip(tmp_path, monkeypatch):
    import agents_tools_helpers as helpers

    monkeypatch.setattr(helpers, "_PROJECT_ROOT", tmp_path)
    write_result = write_md_file_tool("# Spec\n\n## Scope\nIn scope: everything.", file_path="conversation/functional_specification.md")
    assert "successfully written" in write_result

    content = read_md_file_tool(file_path="conversation/functional_specification.md")
    assert "In scope: everything." in content

    # Missing file must not raise; it must return an error string the agent can read.
    missing = read_md_file_tool(file_path="conversation/does_not_exist.md")
    assert missing.startswith("Error")


def test_mermaid_write_and_move(tmp_path, monkeypatch):
    import agents_tools_helpers as helpers

    monkeypatch.setattr(helpers, "_PROJECT_ROOT", tmp_path)
    written = write_mermaid_to_file_tool("flowchart TD\n  A-->B", file_path="conversation/process_diagram.mmd")
    assert "successfully written" in written

    ensure_dir_tool("experience/sess-test")
    moved = move_file_tool(
        "conversation/process_diagram.mmd",
        "experience/sess-test/process_diagram.mmd",
    )
    assert "Moved" in moved
    assert (tmp_path / "experience" / "sess-test" / "process_diagram.mmd").exists()

    bad = move_file_tool("conversation/missing.mmd", "experience/sess-test/x.mmd")
    assert bad.startswith("Error")


def test_selector_routing_after_question_and_ready():
    # Planner assigns the interviewer -> interviewer asks -> user answers.
    history = [
        _msg(PLANNING, '1 interviewer_agent : Start\n[ASSIGNMENT] agent=interviewer_agent task="start" awaiting_user_reply=true'),
        _msg(INTERVIEWER, "QUESTION: What are the KPIs?"),
    ]
    assert asyncio.run(selector_func(history)) == PLANNING

    history.append(_msg("user", "Revenue and churn"))
    assert asyncio.run(selector_func(history)) == PLANNING

    # Checker flags missing use cases -> writer must regenerate them, not the interviewer.
    history = [_msg("functional_spec_checker_agent", "Not complete. NEEDS_INFO: missing Use Cases")]
    assert asyncio.run(selector_func(history)) == WRITER

    # Checker flags a real gap -> planner runs the interview loop.
    history = [_msg("functional_spec_checker_agent", "Not complete. NEEDS_INFO: missing non-functional requirements")]
    assert asyncio.run(selector_func(history)) == PLANNING

    # terminate_agent keeps the floor until it says TERMINATE.
    assert asyncio.run(selector_func([_msg(TERMINATE, "Exported deliverable.pdf")])) == TERMINATE
    assert asyncio.run(selector_func([_msg(TERMINATE, "Done. TERMINATE")])) == PLANNING


def test_agents_config_is_well_formed():
    import yaml

    config = yaml.safe_load((PROJECT_ROOT / "lib" / "agents_config.yaml").read_text(encoding="utf-8"))
    required = {
        "user",
        "planning_agent",
        "interviewer_agent",
        "summarizer_agent",
        "functional_spec_writer_agent",
        "functional_spec_checker_agent",
        "diagram_creator_agent",
        "mermaid_code_reviewer_agent",
        "terminate_agent",
        "use_case_agent",
        "glossary_agent",
    }
    missing = required - set(config)
    assert not missing, f"agents_config.yaml is missing agents: {missing}"

    # Every agent_tools reference must resolve to an agent defined in the config.
    for name, cfg in config.items():
        for referenced in cfg.get("agent_tools", []) or []:
            assert referenced in config, f"{name} references unknown agent {referenced}"

    # No hard-coded machine paths may remain.
    raw = (PROJECT_ROOT / "lib" / "agents_config.yaml").read_text(encoding="utf-8")
    assert "/run/media/" not in raw
    assert "C:\\" not in raw


def test_model_configs_have_no_secrets():
    """Only the configs that ship in the repo are checked: the provider-specific
    ones (azure/groq/hugging/github) are gitignored local files."""
    shipped = {
        "model_config_openai.yaml",
        "model_config_openai_npt.yaml",
        "model_config_ollama.yaml",
        "model_config_lmstudio.yaml",
        "model_config_onnx.yaml",
        "model_config_template.yaml",
    }
    for path in (PROJECT_ROOT / "src").glob("model_config*.yaml"):
        if path.name not in shipped:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "api_key" in line and not line.strip().startswith("#"):
                value = line.split(":", 1)[1].strip()
                assert value in {"REPLACE_WITH_YOUR_API_KEY", "LMStudio_key", "onnx_key"}, (
                    f"{path.name} looks like it contains a real API key"
                )


def test_rag_paths_resolve_to_project_root():
    import yaml
    from rag_helpers import _project_relative

    config = yaml.safe_load((PROJECT_ROOT / "lib" / "rag_config.yaml").read_text(encoding="utf-8"))
    for key in ("CHROMA_DIR", "DOCS_DIR", "STATE_FILE"):
        resolved = _project_relative(config[key])
        assert Path(resolved).parent == PROJECT_ROOT, f"{key} should resolve under the project root"


def test_terminate_token_only_ends_run_from_terminate_agent():
    """Regression: the first real conversation died on turn one because
    TextMentionTermination('TERMINATE') scanned EVERY message and the planner's
    own task-state wording ('terminate_agent: not started', 'Do NOT output
    TERMINATE') tripped it. Only terminate_agent may end the run."""
    import asyncio
    from autogen_agentchat.conditions import TextMentionTermination
    from autogen_agentchat.messages import TextMessage

    # The planner's actual first-turn output (real run, task="hello").
    planner_msg = (
        "Task state:\ninterviewer_agent: pending\n"
        "terminate_agent: not started\n"
        "I will not output TERMINATE until every task is done.\n"
        "[ASSIGNMENT] agent=interviewer_agent task=\"Greet user\" awaiting_user_reply=true"
    )

    termination = TextMentionTermination("TERMINATE", sources=["terminate_agent"])
    result = asyncio.run(
        termination([TextMessage(content=planner_msg, source="planning_agent")])
    )
    assert result is None, "planner chatter mentioning TERMINATE must not end the run"

    result = asyncio.run(
        termination(
            [
                TextMessage(content=planner_msg, source="planning_agent"),
                TextMessage(content="Pipeline complete. TERMINATE", source="terminate_agent"),
            ]
        )
    )
    assert result is not None, "terminate_agent's TERMINATE must end the run"


def test_apps_restrict_terminate_to_terminate_agent():
    """Every front-end must build the termination condition with
    sources=['terminate_agent'], otherwise any agent echoing the word kills
    the whole conversation (see test_terminate_token_only_ends_run_from_terminate_agent)."""
    # The team (and its termination condition) now lives in lib/pipeline.py;
    # app.py is the legacy front-end that still builds its own team.
    for app_file in ("lib/pipeline.py", "app.py"):
        text = (PROJECT_ROOT / app_file).read_text(encoding="utf-8")
        assert 'TextMentionTermination("TERMINATE", sources=["terminate_agent"])' in text, (
            f"{app_file} must restrict TextMentionTermination to sources=['terminate_agent']"
        )

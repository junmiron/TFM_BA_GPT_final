#!/usr/bin/env python3
"""Release readiness check for BA-GPT.

Run:  python scripts/smoke_check.py

Reports what the machine has and what is still missing before the app can run.
"""

import importlib
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "lib"))
from quiet_deprecations import suppress_third_party_deprecations

suppress_third_party_deprecations()

REQUIRED_MODULES = {
    "chainlit": "chainlit",
    "autogen_agentchat": "autogen-agentchat",
    "autogen_ext": "autogen-ext",
    "chromadb": "chromadb",
    "sentence_transformers": "sentence-transformers",
    "yaml": "PyYAML",
    "fastmcp": "fastmcp",
    "lxml": "lxml",
    "readability": "readability-lxml",
    "pymupdf": "PyMuPDF",
    "PIL": "pillow",
}

OPTIONAL_TOOLS = {
    "mmdc": "mermaid-cli (npm i -g @mermaid-js/mermaid-cli) - required for the PNG diagram",
    "pandoc": "pandoc - optional for functional_specification.pdf; without it the export uses PyMuPDF Story",
    "xelatex": "a LaTeX engine - only used when pandoc is available",
}


def check_python() -> bool:
    if sys.version_info < (3, 10):
        print(f"[FAIL] Python {sys.version_info.major}.{sys.version_info.minor} is too old (need >= 3.10)")
        return False
    print(f"[OK]   Python {sys.version}")
    return True


def check_modules() -> int:
    missing = 0
    for module, package in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module)
            print(f"[OK]   {package}")
        except ImportError:
            missing += 1
            print(f"[FAIL] {package} is not installed (pip install {package})")
    return missing


def check_tools() -> None:
    for tool, hint in OPTIONAL_TOOLS.items():
        found = shutil.which(tool) or (os.name == "nt" and shutil.which(f"{tool}.cmd"))
        print(f"[{'OK' if found else 'WARN'}] {tool}: {hint}" if not found else f"[OK]   {tool} available")


def check_config() -> None:
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        print("[OK]   .env present (gitignored)")
    else:
        print("[WARN] No .env. Copy .env.example to .env and set your keys.")

    # Validate the lanes actually selected in .env, not a hard-coded profile.
    PROFILES = {}
    resolve_profile_name = None
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from model_loader import PROFILES, resolve_profile_name
    except ImportError:
        pass

    if resolve_profile_name:
        for var in ("MODEL_CLIENT", "MODEL_CLIENT_TOOLS", "HUMAN_MODEL"):
            raw = os.getenv(var, "")
            try:
                profile = resolve_profile_name(raw)
                key_env = PROFILES[profile][1]
                if key_env and not os.getenv(key_env):
                    print(f"[WARN] {var}={profile} needs {key_env} in .env")
                else:
                    print(f"[OK]   {var}={profile}")
            except ValueError as exc:
                print(f"[FAIL] {var}={raw!r}: {exc}")
    else:
        if not os.getenv("OPENAI_API_KEY"):
            print("[WARN] OPENAI_API_KEY is not set in the environment or .env")

    for name in ("lib/agents_config.yaml", "lib/rag_config.yaml", "src/model_config_template.yaml"):
        path = PROJECT_ROOT / name
        print(f"[{'OK' if path.exists() else 'FAIL'}] {name}")

    data_dir = PROJECT_ROOT / "data"
    if data_dir.exists() and any(data_dir.iterdir()):
        print(f"[OK]   data/ has {len(list(data_dir.iterdir()))} documents for RAG indexing")
    else:
        print("[WARN] data/ is empty or missing - RAG will only index the SITES list")


def main() -> int:
    print(f"Project root: {PROJECT_ROOT}\n")
    ok = check_python()
    missing = check_modules()
    check_tools()
    check_config()
    print(f"\nResult: {'READY' if ok and missing == 0 else 'NOT READY'} "
          f"({missing} missing package(s))")
    return 0 if ok and missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

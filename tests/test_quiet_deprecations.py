"""The app stack (chainlit -> literalai -> traceloop, and fastmcp -> authlib) emits
deprecation warnings we cannot fix upstream. These tests prove the suppression is
registered and that importing the app produces no warning output at all.
"""
import subprocess
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import pytest

from quiet_deprecations import suppress_third_party_deprecations


def test_both_known_categories_are_suppressed():
    suppressed = suppress_third_party_deprecations()
    assert "pydantic.PydanticDeprecatedSince20" in suppressed
    assert "authlib.deprecate.AuthlibDeprecationWarning" in suppressed
    registered = {f[2] for f in warnings.filters if f[0] == "ignore"}
    from pydantic import PydanticDeprecatedSince20
    assert PydanticDeprecatedSince20 in registered


def test_unrelated_warnings_are_not_swallowed():
    suppress_third_party_deprecations()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.warn("our own deprecation", DeprecationWarning)
    assert any(str(w.message) == "our own deprecation" for w in caught)


def test_importing_the_app_emits_no_warnings():
    proc = subprocess.run(
        [sys.executable, "-W", "default", "-c", "import app2"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    noise = [line for line in proc.stderr.splitlines() if "Warning" in line]
    assert not noise, f"importing app2 emitted warnings: {noise}"

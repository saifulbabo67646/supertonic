"""Run the Studio's JavaScript unit tests with Node's test runner (skipped without Node)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent


def _node_flags(node: str) -> list[str] | None:
    """Flags to load the Studio's ``.js`` ES modules, or ``None`` when this Node is too old.

    The modules have no ``package.json`` beside them; Node 22.7+ detects ES module syntax by
    itself, 20.10+ needs ``--experimental-detect-module``.
    """
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    try:
        major, minor = (int(part) for part in out.stdout.strip().lstrip("v").split(".")[:2])
    except ValueError:
        return None
    if (major, minor) >= (22, 7):
        return []
    if (major, minor) >= (20, 10):
        return ["--experimental-detect-module"]
    return None


def test_studio_logic() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    flags = _node_flags(node)
    if flags is None:
        pytest.skip("Node.js 20.10 or newer is needed")
    result = subprocess.run(
        [node, *flags, "--test", "studio_logic.test.mjs"],
        cwd=HERE,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _clean_supertonic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep host SUPERTONIC_* variables from leaking into tests."""
    import os

    for name in list(os.environ):
        if name.startswith("SUPERTONIC_"):
            monkeypatch.delenv(name)

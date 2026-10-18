"""Tests for scrubbing local paths out of messages shown to API, UI and MCP users."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from supertonic_server.core.scrub import scrub_paths

WIN_HOME = r"C:\Users\alice"
WIN_TEMP = r"C:\Users\alice\AppData\Local\Temp"
MAC_HOME = "/Users/alice"
MAC_TEMP = "/var/folders/s4/abc123/T"


def _win(text: str) -> str:
    return scrub_paths(text, home=WIN_HOME, temp_dirs=[WIN_TEMP])


def _mac(text: str) -> str:
    return scrub_paths(text, home=MAC_HOME, temp_dirs=[MAC_TEMP, "/private" + MAC_TEMP])


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (
            r"Error opening C:\Users\alice\AppData\Local\Temp\supertonic-ref-x1\ref-0: bad",
            r"Error opening <tmp>\supertonic-ref-x1\ref-0: bad",
        ),
        (
            r"no such file c:\users\ALICE\work\models\x.onnx",
            r"no such file <home>\work\models\x.onnx",
        ),
        ("C:/Users/alice/work/model.onnx missing", "<home>/work/model.onnx missing"),
        (r"cannot open D:\data\jobs\abc\style.json", "cannot open style.json"),
        (r"weights at C:\Users\bob\models", "weights at models"),
        (r"C:\Users\alice", "<home>"),
    ],
)
def test_windows_paths(raw: str, clean: str) -> None:
    assert _win(raw) == clean


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (
            "Error opening input file /var/folders/s4/abc123/T/supertonic-ref-ymg/ref-0.",
            "Error opening input file <tmp>/supertonic-ref-ymg/ref-0.",
        ),
        (
            "open /private/var/folders/s4/abc123/T/x/ref-0 failed",
            "open <tmp>/x/ref-0 failed",
        ),
        (
            "[Errno 2] No such file: '/Users/alice/data/jobs/j1'",
            "[Errno 2] No such file: '<home>/data/jobs/j1'",
        ),
        ("model at /Users/carol/models/m.onnx", "model at m.onnx"),
        ("cache /home/dave/.cache/x.bin gone", "cache x.bin gone"),
        ("wrote /tmp/abc/out.wav", "wrote out.wav"),
        ("lock /var/folders/zz/other/T/f.lock", "lock f.lock"),
        ("see /private/etc/hosts", "see hosts"),
        ("/home/", "home"),
        ("C:\\", "<path>"),
    ],
)
def test_posix_paths(raw: str, clean: str) -> None:
    assert _mac(raw) == clean


@pytest.mark.parametrize(
    "text",
    [
        "RuntimeError: kaboom",
        "CUDA out of memory. Tried to allocate 2 GiB",
        "see https://example.com/home/docs and http://host:8000/tmp/x",
        "ratio 3/4 and a/b paths stay",
        "build exceeded 150 min",
    ],
)
def test_ordinary_text_unchanged(text: str) -> None:
    assert _win(text) == text
    assert _mac(text) == text


def test_defaults_use_this_machine() -> None:
    home, temp = str(Path.home()), tempfile.gettempdir()
    out = scrub_paths(f"a {Path(temp) / 'x' / 'f.wav'} b {Path(home) / 'p' / 'g.wav'}")
    assert temp not in out and home not in out
    assert "<tmp>" in out and "<home>" in out


def test_idempotent() -> None:
    once = _mac("open /var/folders/s4/abc123/T/x/ref-0 and /Users/alice/y")
    assert _mac(once) == once

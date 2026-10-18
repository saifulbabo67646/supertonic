"""Keep local file-system paths out of error messages shown to API, UI and MCP users.

Messages from ffmpeg, the builder worker and the OS often name files under the user's home
or temp folder (``C:\\Users\\<name>\\...``, ``/var/folders/...``). Forwarded builds pass the
builder's messages on unchanged, so the machine that produced a message scrubs it.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

# Absolute paths left after the home/temp prefixes are replaced: Windows drive paths and the
# POSIX roots that hold user or temp files. A path ends at whitespace, a quote or a colon.
_TAIL = r"[^\s\"'<>|:,;()]*"
_ABSOLUTE = re.compile(
    rf"(?<![\w/\\.:<>])(?:[A-Za-z]:[\\/]{_TAIL}"
    rf"|/(?:Users|home|tmp|private|var/folders)(?:/{_TAIL})?)"
)


def _variants(paths: Iterable[str | None]) -> set[str]:
    """Each path plus its resolved form, without trailing separators; roots are dropped."""
    out: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        for p in (raw, os.path.realpath(raw)):
            p = p.rstrip("\\/")
            if p and Path(p).parent != Path(p):
                out.add(p)
    return out


def _prefix_pattern(prefix: str) -> re.Pattern[str]:
    """Match ``prefix`` with either separator, any case, ending at a path boundary."""
    parts = [re.escape(part) for part in re.split(r"[\\/]+", prefix)]
    return re.compile(r"[\\/]+".join(parts) + r"(?![^\s\"'<>|:,;()\\/])", re.IGNORECASE)


def _basename(match: re.Match[str]) -> str:
    name = re.split(r"[\\/]", match.group(0).rstrip("\\/"))[-1]
    return name if name and not name.endswith(":") else "<path>"


def scrub_paths(
    text: str, *, home: str | None = None, temp_dirs: Sequence[str] | None = None
) -> str:
    """Replace local paths in ``text``.

    The temp folder becomes ``<tmp>``, the home folder ``<home>``; any other absolute path
    under a user or temp root (``X:\\...``, ``/Users``, ``/home``, ``/tmp``, ``/private``,
    ``/var/folders``) is cut to its last component.

    Args:
        text: The message.
        home: The home folder (default: this user's).
        temp_dirs: The temp folders (default: this machine's).
    """
    if temp_dirs is None:
        env = (os.environ.get(name) for name in ("TMPDIR", "TEMP", "TMP"))
        temp_dirs = [tempfile.gettempdir(), *(p for p in env if p)]
    homes = [home] if home is not None else [str(Path.home()), os.environ.get("USERPROFILE")]
    labelled = [(p, "<tmp>") for p in _variants(temp_dirs)]
    labelled += [(p, "<home>") for p in _variants(homes)]
    for prefix, label in sorted(labelled, key=lambda pl: len(pl[0]), reverse=True):
        text = _prefix_pattern(prefix).sub(label, text)
    return _ABSOLUTE.sub(_basename, text)

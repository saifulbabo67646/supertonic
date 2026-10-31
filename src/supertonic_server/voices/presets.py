"""Built-in voices: the single source of truth for their display names and descriptions.

Ids (``F1``..``F5``, ``M1``..``M5``) are stable and never renamed; a name works anywhere an
id does (case-insensitive). Descriptions are grounded in ``scripts/describe_presets.py``:
pitch is relative to the other voices of the same gender, pace to all ten, and only the
suggested use is a judgement call (see ``docs/voices.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

Pitch = Literal["lower", "higher"]
Pace = Literal["unhurried", "moderate", "brisk"]


@dataclass(frozen=True)
class Preset:
    """Display metadata of one built-in voice.

    Attributes:
        name: Display name; works anywhere the id does.
        gender: ``"female"`` or ``"male"``.
        pitch: Measured median pitch relative to the other voices of the same gender.
        pace: Measured speaking rate relative to all ten voices.
        suits: Suggested use (a neutral suggestion, not a measurement).
    """

    name: str
    gender: Literal["female", "male"]
    pitch: Pitch
    pace: Pace
    suits: str

    @property
    def description(self) -> str:
        """One line, e.g. ``"Higher-pitched female voice with an unhurried pace; suits ..."``."""
        article = "an" if self.pace[0] in "aeiou" else "a"
        return (
            f"{self.pitch.capitalize()}-pitched {self.gender} voice with {article} {self.pace} "
            f"pace; suits {self.suits}."
        )


PRESETS: MappingProxyType[str, Preset] = MappingProxyType(
    {
        "F1": Preset("Mia", "female", "higher", "unhurried", "narration and explainers"),
        "F2": Preset("Nora", "female", "higher", "moderate", "assistants and product tours"),
        "F3": Preset("Lena", "female", "lower", "unhurried", "audiobooks and calm reading"),
        "F4": Preset("Sofia", "female", "higher", "brisk", "ads, promos and short social clips"),
        "F5": Preset("Yuna", "female", "lower", "moderate", "e-learning and announcements"),
        "M1": Preset("Hugo", "male", "higher", "unhurried", "tutorials and walkthroughs"),
        "M2": Preset("Diego", "male", "lower", "moderate", "documentaries and trailers"),
        "M3": Preset("Ravi", "male", "lower", "brisk", "news reads and quick updates"),
        "M4": Preset("Felix", "male", "higher", "moderate", "voice agents and support calls"),
        "M5": Preset("Omar", "male", "lower", "unhurried", "storytelling and long-form narration"),
    }
)
"""Preset id -> display metadata, in listing order."""

PRESET_IDS = frozenset(PRESETS)

_BY_NAME = {p.name.lower(): vid for vid, p in PRESETS.items()}


def preset_id_for_name(name: str) -> str | None:
    """The preset id whose display name is ``name`` (case-insensitive), else ``None``."""
    return _BY_NAME.get(name.strip().lower())


def is_reserved(name: str) -> bool:
    """True when ``name`` equals a preset id or name (case-insensitive, ignoring spaces)."""
    low = name.strip().lower()
    return low in _BY_NAME or low in {vid.lower() for vid in PRESETS}

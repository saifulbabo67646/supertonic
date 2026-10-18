"""Voice metadata model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class Voice:
    """A voice available for synthesis.

    Attributes:
        id: Unique identifier (preset ``F1``..``M5`` or a slug for custom voices).
        name: Display name.
        kind: ``"preset"`` (read-only) or ``"custom"``.
        description: Free-form description.
        tags: Free-form labels.
        gender: ``"female"``, ``"male"`` or ``None`` when unknown.
        source_note: Where the voice came from.
        created_at: ISO-8601 UTC creation time (empty for presets).
        model: Model the style belongs to.
    """

    id: str
    name: str
    kind: Literal["preset", "custom"]
    description: str = ""
    tags: list[str] = field(default_factory=list)
    gender: str | None = None
    source_note: str = ""
    created_at: str = ""
    model: str = "supertonic-3"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of all fields."""
        return asdict(self)

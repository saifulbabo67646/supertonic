"""Validation of Supertonic 3 voice-style JSON documents."""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any

from supertonic_server.core.errors import ApiError

EXPECTED_DIMS: dict[str, list[int]] = {"style_ttl": [1, 50, 256], "style_dp": [1, 8, 16]}


def _flatten(value: Any) -> Iterator[Any]:
    """Yield the leaves of an arbitrarily nested list."""
    if isinstance(value, list):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


def _invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_style", message, param="style")


def validate_style(data: dict[str, Any]) -> None:
    """Check that ``data`` is a well-formed Supertonic 3 style.

    Raises:
        ApiError: 400 ``invalid_style`` naming the first problem found.
    """
    if not isinstance(data, dict):
        raise _invalid("style must be a JSON object")
    for key, dims in EXPECTED_DIMS.items():
        part = data.get(key)
        if not isinstance(part, dict):
            raise _invalid(f"missing '{key}' object")
        if "dims" not in part or "data" not in part:
            raise _invalid(f"'{key}' needs 'dims' and 'data'")
        if part["dims"] != dims:
            raise _invalid(f"'{key}.dims' must be {dims}, got {part['dims']}")
        values = list(_flatten(part["data"]))
        expected = math.prod(dims)
        if len(values) != expected:
            raise _invalid(f"'{key}.data' has {len(values)} values, expected {expected}")
        for v in values:
            if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
                raise _invalid(f"'{key}.data' contains a non-finite or non-numeric value")

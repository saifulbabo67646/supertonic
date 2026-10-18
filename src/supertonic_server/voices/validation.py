"""Validation of Supertonic 3 voice-style JSON documents."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from supertonic_server.core.errors import ApiError

EXPECTED_DIMS: dict[str, list[int]] = {"style_ttl": [1, 50, 256], "style_dp": [1, 8, 16]}


def _invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_style", message, param="style")


def _as_array(key: str, data: Any, dims: list[int]) -> np.ndarray:
    """Convert ``data`` to a float32 array shaped ``dims`` or raise ``invalid_style``.

    Accepts nesting matching ``dims`` exactly, or a flat list of the right length (the
    ``supertonic`` loader reshapes ``data`` to ``dims``). Ragged or overly deep nesting and
    non-numeric leaves are rejected without recursing in Python.
    """
    try:
        arr = np.asarray(data)
    except (ValueError, RecursionError, TypeError, OverflowError):
        raise _invalid(f"'{key}.data' must be a regular nested list of numbers") from None
    if arr.dtype.kind not in "iuf":
        raise _invalid(f"'{key}.data' contains a non-finite or non-numeric value")
    expected = math.prod(dims)
    if list(arr.shape) != dims and arr.shape != (expected,):
        if arr.size != expected:
            raise _invalid(f"'{key}.data' has {arr.size} values, expected {expected}")
        raise _invalid(f"'{key}.data' has shape {list(arr.shape)}, expected {dims}")
    with np.errstate(over="ignore"):
        out = arr.astype(np.float32)
    if not np.isfinite(out).all():
        raise _invalid(f"'{key}.data' contains a non-finite or non-numeric value")
    return out


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
        _as_array(key, part["data"], dims)

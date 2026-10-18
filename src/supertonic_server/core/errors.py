"""Error types shared across the service."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """An error that maps to an OpenAI-style JSON error response.

    Args:
        status: HTTP status code.
        code: Stable machine-readable error code.
        message: Human-readable description.
        param: Name of the offending request parameter, if any.
        type_: OpenAI error ``type`` string.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        param: str | None = None,
        type_: str = "invalid_request_error",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.param = param
        self.type = type_


def error_body(code: str, message: str, param: str | None, type_: str) -> dict[str, Any]:
    """Build the OpenAI-style error payload."""
    return {"error": {"message": message, "type": type_, "code": code, "param": param}}

"""Error types shared across the service."""

from __future__ import annotations


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

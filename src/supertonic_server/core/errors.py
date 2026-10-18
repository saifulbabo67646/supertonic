"""Error types shared across the service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)
_INVALID = "invalid_request_error"


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


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error uses the ``{"error": {...}}`` body."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        body = error_body(exc.code, exc.message, exc.param, exc.type)
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = [str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path")]
        param = ".".join(loc) or None
        message = str(first.get("msg", "Invalid request"))
        return JSONResponse(
            error_body("invalid_request", message, param, _INVALID), status_code=400
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", exc_info=exc)
        body = error_body("internal_error", "Internal server error", None, "server_error")
        return JSONResponse(body, status_code=500)

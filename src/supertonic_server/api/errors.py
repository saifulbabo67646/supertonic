"""FastAPI exception handlers that render every error as ``{"error": {...}}``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from supertonic_server.core.errors import ApiError, error_body

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)
_INVALID = "invalid_request_error"
_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


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
        loc = [str(p) for p in first.get("loc", ())[1:]]
        param = ".".join(loc) or None
        if param is not None and param.replace(".", "").isdigit():
            param = None
        message = str(first.get("msg", "Invalid request"))
        return JSONResponse(
            error_body("invalid_request", message, param, _INVALID), status_code=400
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
        body = error_body(code, str(exc.detail), None, _INVALID)
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", exc_info=exc)
        body = error_body("internal_error", "Internal server error", None, "server_error")
        return JSONResponse(body, status_code=500)

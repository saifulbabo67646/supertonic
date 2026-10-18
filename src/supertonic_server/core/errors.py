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


# -- voice builder errors (shared by the local JobManager and the RemoteBuilder) -------------


def builder_busy() -> ApiError:
    """503: the build queue is full."""
    return ApiError(
        503, "builder_busy", "Voice builder queue is full; retry later", type_="server_error"
    )


def builder_unavailable(message: str) -> ApiError:
    """503: no builder can take the request (none configured, unreachable, shutting down)."""
    return ApiError(503, "builder_unavailable", message, type_="server_error")


def job_not_found(job_id: str) -> ApiError:
    """404: unknown job id."""
    return ApiError(404, "job_not_found", f"Job '{job_id}' not found", param="job_id")


def job_not_running(job_id: str) -> ApiError:
    """409: the job has not started yet."""
    return ApiError(409, "job_not_running", f"Job '{job_id}' has not started yet")


def finish_failed(reason: str) -> ApiError:
    """500: the stop file could not be written (``reason`` must hold no local paths)."""
    return ApiError(
        500, "internal_error", f"Could not ask the build to finish: {reason}", type_="server_error"
    )


def method_unavailable(method: str, available: tuple[str, ...]) -> ApiError:
    """400: the builder cannot run this build method."""
    names = ", ".join(available) or "none"
    return ApiError(
        400,
        "method_unavailable",
        f"method {method!r} is not available on this builder (available: {names})",
        param="method",
    )

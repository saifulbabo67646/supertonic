"""HTTP calls a :class:`~.remote.RemoteBuilder` makes to its builder (another Supertonic server).

Every call returns the decoded JSON body. A transport failure (refused, timed out, bad JSON)
raises :class:`Unreachable`; an error answer is re-raised as the remote's own
:class:`ApiError` (status, code, message, param), except that a refused API key becomes 503
``builder_unavailable`` (the local caller's key is not the problem).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from supertonic_server.builder.models import BUILD_METHODS, BuildMethod, BuildRequest
from supertonic_server.core import errors
from supertonic_server.core.errors import ApiError

HEALTH_TIMEOUT_S = 5.0
UPLOAD_TIMEOUT_S = 120.0
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class Unreachable(Exception):
    """The builder could not be reached or gave an unreadable answer."""


def host_of(base_url: str) -> str:
    """``host:port`` of ``base_url`` (credentials dropped), for messages and labels."""
    parts = urlsplit(base_url)
    netloc = parts.netloc.rpartition("@")[2]
    return netloc or base_url


def _reason(exc: httpx.HTTPError) -> str:
    """Why a request failed, without the URL (it may carry credentials) or the exception text."""
    if isinstance(exc, httpx.TimeoutException):
        return "the connection timed out"
    if isinstance(exc, httpx.ConnectError):
        return "could not connect (refused, or host not found)"
    return f"the connection failed ({type(exc).__name__})"


class BuilderClient:
    """Thin JSON client for a builder's ``/v1`` API.

    Args:
        base_url: The builder's root URL, e.g. ``http://win-laptop:8787``.
        api_key: Sent as ``Authorization: Bearer <key>`` when set.
        http: The client to send requests with (owned by the caller).
    """

    def __init__(self, base_url: str, api_key: str | None, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http
        self.host = host_of(self._base)

    def unreachable(self, reason: str) -> ApiError:
        """503 ``builder_unavailable``: the builder cannot take builds, and why."""
        return errors.builder_unavailable(
            f"Voice builder at {self.host} is not reachable: {reason}"
        )

    async def ready_methods(self) -> tuple[BuildMethod, ...] | None:
        """Check ``GET /v1/health`` (short timeout) reports a local builder; return its methods.

        ``None`` means the builder did not list its methods.

        Raises:
            ApiError: :meth:`unreachable` when it cannot be reached or has no local builder.
        """
        try:
            health = await self._call("GET", "/v1/health", limit=HEALTH_TIMEOUT_S)
        except Unreachable as exc:
            raise self.unreachable(str(exc)) from exc
        except ApiError as exc:
            raise self.unreachable(exc.message) from exc
        kind = health.get("builder")
        if kind != "local":
            raise self.unreachable(f"it has no local voice builder (builder: {kind!r})")
        detail = health.get("builder_detail")
        methods = detail.get("methods") if isinstance(detail, dict) else None
        if not isinstance(methods, list):
            return None
        return tuple(m for m in BUILD_METHODS if m in methods)

    async def submit(self, req: BuildRequest, files: Sequence[tuple[str, bytes]]) -> dict[str, Any]:
        """``POST /v1/voices/build`` with the request's fields and the raw reference files."""
        data = {
            "name": req.name,
            "description": req.description,
            "tags": ",".join(req.tags),
            "source_note": req.source_note,
            "consent": "true" if req.consent is True else "false",
            "method": req.method,
        }
        upload = [("files", (name, content, "application/octet-stream")) for name, content in files]
        return await self._call(
            "POST", "/v1/voices/build", data=data, files=upload, limit=UPLOAD_TIMEOUT_S
        )

    async def job(self, job_id: str) -> dict[str, Any]:
        """``GET /v1/jobs/{id}``."""
        return await self._call("GET", f"/v1/jobs/{quote(job_id, safe='')}")

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """``DELETE /v1/jobs/{id}``."""
        return await self._call("DELETE", f"/v1/jobs/{quote(job_id, safe='')}")

    async def finish(self, job_id: str) -> dict[str, Any]:
        """``POST /v1/jobs/{id}/finish``."""
        return await self._call("POST", f"/v1/jobs/{quote(job_id, safe='')}/finish")

    async def voice(self, voice_id: str) -> dict[str, Any]:
        """``GET /v1/voices/{id}`` (includes the ``build`` metadata)."""
        return await self._call("GET", f"/v1/voices/{quote(voice_id, safe='')}")

    async def style(self, voice_id: str) -> dict[str, Any]:
        """``GET /v1/voices/{id}/style``: the voice's style JSON."""
        return await self._call("GET", f"/v1/voices/{quote(voice_id, safe='')}/style")

    async def _call(
        self, method: str, path: str, *, limit: float | httpx.Timeout = DEFAULT_TIMEOUT, **kw: Any
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method, self._base + path, headers=self._headers, timeout=limit, **kw
            )
        except httpx.HTTPError as exc:
            raise Unreachable(_reason(exc)) from exc
        if response.status_code >= 400:
            raise self._error(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise Unreachable(f"{method} {path} answered with invalid JSON") from exc
        if not isinstance(body, dict):
            raise Unreachable(f"{method} {path} answered with unexpected JSON")
        return body

    def _error(self, response: httpx.Response) -> ApiError:
        status = response.status_code
        try:
            err = response.json()["error"]
            code, message = str(err["code"]), str(err["message"])
            param = err.get("param")
            type_ = str(err.get("type") or "invalid_request_error")
        except (ValueError, KeyError, TypeError):
            if status >= 500:  # up but broken (a proxy page, a crash): it cannot build
                return self.unreachable(f"it answered HTTP {status}")
            return ApiError(
                502,
                "builder_error",
                f"Voice builder at {self.host} answered HTTP {status}",
                type_="server_error",
            )
        if status in (401, 403):
            return errors.builder_unavailable(
                f"Voice builder at {self.host} refused the request ({code}): check "
                "SUPERTONIC_BUILDER_API_KEY matches the builder's API key"
            )
        return ApiError(status, code, message, str(param) if param is not None else None, type_)

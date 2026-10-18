"""Thin typed async HTTP client over the Supertonic REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class SupertonicApiError(Exception):
    """An error response from the server, built from its ``{"error": {...}}`` body.

    Args:
        code: The server's machine-readable error code (``http_error`` if unknown).
        message: Human-readable description.
        status: HTTP status code.
    """

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(f"{message} (code: {code})")
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Speech:
    """Raw audio returned by ``/v1/audio/speech``."""

    audio: bytes
    voice: str
    sample_rate: int | None


def _raise_for_error(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    code, message = "http_error", f"HTTP {resp.status_code}: {resp.text[:200]}".strip()
    try:
        err = resp.json()["error"]
        code, message = str(err["code"]), str(err["message"])
    except (ValueError, KeyError, TypeError):
        pass
    raise SupertonicApiError(code, message, resp.status_code)


class SupertonicClient:
    """Async client for the endpoints the MCP tools need.

    Args:
        http: An ``httpx.AsyncClient`` whose ``base_url`` is the server root.
        api_key: Optional bearer token sent as ``Authorization: Bearer <key>``.
    """

    def __init__(self, http: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = await self._http.request(method, url, headers=self._headers, **kwargs)
        except httpx.TransportError as exc:
            raise SupertonicApiError(
                "connection_error", f"Cannot reach the Supertonic server: {exc}", 0
            ) from exc
        _raise_for_error(resp)
        return resp

    async def languages(self) -> list[dict[str, Any]]:
        """Return ``GET /v1/languages`` data."""
        data: list[dict[str, Any]] = (await self._request("GET", "/v1/languages")).json()["data"]
        return data

    async def voices(self, kind: str | None = None, tag: str | None = None) -> list[dict[str, Any]]:
        """Return ``GET /v1/voices`` data, optionally filtered."""
        params = {k: v for k, v in (("kind", kind), ("tag", tag)) if v}
        data: list[dict[str, Any]] = (
            await self._request("GET", "/v1/voices", params=params)
        ).json()["data"]
        return data

    async def speech(
        self, text: str, voice: str, language: str, speed: float, response_format: str
    ) -> Speech:
        """Call ``POST /v1/audio/speech`` and return the audio bytes."""
        body = {
            "model": "supertonic-3",
            "input": text,
            "voice": voice,
            "language": language,
            "speed": speed,
            "response_format": response_format,
        }
        resp = await self._request("POST", "/v1/audio/speech", json=body)
        rate = resp.headers.get("X-Sample-Rate", "")
        return Speech(
            resp.content, resp.headers.get("X-Voice-Id", voice), int(rate) if rate else None
        )

    async def timestamps(
        self, text: str, voice: str, language: str, speed: float, response_format: str
    ) -> dict[str, Any]:
        """Call ``POST /v1/tts/timestamps`` and return the JSON body."""
        body = {
            "text": text,
            "voice": voice,
            "language": language,
            "speed": speed,
            "response_format": response_format,
        }
        data: dict[str, Any] = (await self._request("POST", "/v1/tts/timestamps", json=body)).json()
        return data

    async def preview(self, voice: str, language: str) -> bytes:
        """Return the WAV bytes of ``GET /v1/voices/{id}/preview``."""
        resp = await self._request(
            "GET", f"/v1/voices/{voice}/preview", params={"language": language}
        )
        return resp.content

"""Pure-ASGI request guard: API key, forwarded-header check and request-body cap.

The guard runs before routing and body parsing, so unauthenticated or oversized requests
are refused without the server reading (let alone parsing) their bodies.

- **API key.** When ``settings.api_key`` is set, every ``/v1/*`` request except
  ``GET /v1/health``, and the OpenAPI pages (``/docs``, ``/redoc``, ``/openapi.json``), need
  ``Authorization: Bearer <key>``. WebSockets may instead pass ``?api_key=``.
- **Tunnel footgun.** Without an API key, a request carrying a forwarding header
  (``CF-Connecting-IP``, ``X-Forwarded-For``, ``Forwarded``, ``X-Real-IP``) came through a
  proxy or tunnel and is refused with 403 ``forwarded_without_key``.
- **Body cap.** HTTP bodies are limited to :data:`MAX_BODY_BYTES` (voice imports to
  :data:`MAX_IMPORT_BODY_BYTES`); the limit is enforced while the body streams in, so a
  missing or false ``Content-Length`` does not help. Oversized bodies get 413
  ``payload_too_large``.

A refused WebSocket is not closed here: the guard stores the error under
:data:`WS_REJECTION` in the scope and the realtime handler accepts the socket, sends a
``conversation.item.tts.failed`` event explaining why, then closes it with 1008.
"""

from __future__ import annotations

import contextlib
import hmac
from typing import TYPE_CHECKING, Any

from starlette.datastructures import Headers, QueryParams
from starlette.responses import JSONResponse

from supertonic_server.core.errors import ApiError, error_body

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 1024 * 1024
"""Largest accepted HTTP request body (bytes)."""

MAX_IMPORT_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024
"""Largest body of ``POST /v1/voices/import``: a 2 MB style plus multipart framing."""

WS_REJECTION = "supertonic.rejection"
"""Scope key under which the guard leaves an :class:`ApiError` for the WebSocket handler."""

FORWARDED_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "forwarded", "x-real-ip")
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


def bearer_token(headers: Headers) -> str:
    """Return the token of an ``Authorization: Bearer`` header, or ``""``."""
    scheme, _, token = headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _invalid_key() -> ApiError:
    return ApiError(
        401, "invalid_api_key", "Incorrect or missing API key", type_="authentication_error"
    )


def _forwarded() -> ApiError:
    return ApiError(
        403,
        "forwarded_without_key",
        "This request came through a proxy or tunnel (it carries a forwarding header such as "
        "X-Forwarded-For or CF-Connecting-IP), but the server has no API key. Set "
        "SUPERTONIC_API_KEY (and SUPERTONIC_PUBLIC_URL, any value for quick tunnels) before "
        "exposing the server.",
        type_="permission_error",
    )


def _too_large(limit: int) -> ApiError:
    return ApiError(413, "payload_too_large", f"Request body exceeds the limit of {limit} bytes")


class _BodyTooLarge(Exception):
    """Raised from ``receive`` once the streamed body passes the limit."""


class Guard:
    """ASGI middleware enforcing the rules in the module docstring.

    Args:
        app: The wrapped ASGI application.
        api_key: The configured API key (``settings.api_key``), or ``None``.
    """

    def __init__(self, app: ASGIApp, api_key: str | None) -> None:
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the connection, then pass it on (HTTP bodies through the size cap)."""
        if scope["type"] == "websocket":
            rejection = self.check(scope)
            if rejection is not None:
                scope[WS_REJECTION] = rejection
            await self.app(scope, receive, send)
        elif scope["type"] == "http":
            rejection = self.check(scope)
            if rejection is not None:
                await _respond(rejection, scope, receive, send)
            else:
                await self._capped(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    def check(self, scope: Scope) -> ApiError | None:
        """Return why the connection must be refused, or ``None`` to let it through."""
        headers = Headers(scope=scope)
        if not self.api_key:
            return _forwarded() if any(h in headers for h in FORWARDED_HEADERS) else None
        if not _protected(scope):
            return None
        supplied = bearer_token(headers)
        if not supplied and scope["type"] == "websocket":
            supplied = QueryParams(scope.get("query_string", b"")).get("api_key", "")
        if hmac.compare_digest(supplied.encode(), self.api_key.encode()):
            return None
        return _invalid_key()

    async def _capped(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = _body_limit(scope)
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            await _respond(_too_large(limit), scope, receive, send)
            return
        received = 0
        exceeded = started = False

        async def capped_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                return  # drop whatever the app made of the aborted body; we answer 413
            started = started or message["type"] == "http.response.start"
            await send(message)

        with contextlib.suppress(_BodyTooLarge):
            await self.app(scope, capped_receive, guarded_send)
        if exceeded and not started:
            await _respond(_too_large(limit), scope, receive, send)


def _protected(scope: Scope) -> bool:
    path: str = scope["path"]
    if path in DOCS_PATHS:
        return True
    if path != "/v1" and not path.startswith("/v1/"):
        return False
    return not (scope["type"] == "http" and scope["method"] == "GET" and path == "/v1/health")


def _body_limit(scope: Scope) -> int:
    if scope["method"] == "POST" and scope["path"] == "/v1/voices/import":
        return MAX_IMPORT_BODY_BYTES
    return MAX_BODY_BYTES


async def _respond(exc: ApiError, scope: Scope, receive: Receive, send: Send) -> None:
    body: dict[str, Any] = error_body(exc.code, exc.message, exc.param, exc.type)
    await JSONResponse(body, status_code=exc.status)(scope, receive, send)

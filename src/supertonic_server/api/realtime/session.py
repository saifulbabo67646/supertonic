"""Realtime TTS WebSocket: event dispatch, ordered synthesis and barge-in.

Each context (see :mod:`.context`) owns a sentence buffer, an ordered queue of sentences
and one consumer task, so audio of a context is always in order while different
contexts synthesise concurrently. Every outgoing event goes through one writer task, so
frames never interleave and cancelling a context can also discard its unsent audio.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from supertonic_server.api.realtime import protocol as p
from supertonic_server.api.realtime.context import Context, Entry
from supertonic_server.api.realtime.params import ConnectParams, Voicing, check_key, parse_params
from supertonic_server.audio import resample, to_pcm16
from supertonic_server.core.errors import ApiError
from supertonic_server.engine import PRIORITY_REALTIME

if TYPE_CHECKING:
    from supertonic_server.api.deps import AppState

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_CONTEXTS = 32
"""Contexts one socket may open; more is almost certainly a client bug."""

_POLICY_VIOLATION = 1008
_TRY_AGAIN_LATER = 1013
_AUDIO_EVENTS = {"conversation.item.audio_output.delta", "conversation.item.audio_output.done"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Session:
    """One realtime connection: dispatches client events and streams audio back."""

    def __init__(self, ws: WebSocket, state: AppState, params: ConnectParams) -> None:
        self.ws = ws
        self.state = state
        self.id = _new_id("sess")
        self.defaults = params.voicing
        self.sample_rate = params.sample_rate
        self.max_partial = params.max_partial_length
        self.contexts: dict[str, Context] = {}
        self._out: deque[dict[str, Any]] = deque()
        self._wake = asyncio.Event()

    def info(self, voicing: Voicing) -> dict[str, Any]:
        """The ``session`` object describing ``voicing``."""
        v = voicing
        return p.session_info(self.id, v.voice, v.language, self.sample_rate, v.speed)

    def emit(self, event: dict[str, Any]) -> None:
        """Queue ``event`` for the writer; events are sent whole, in emit order."""
        self._out.append(event)
        self._wake.set()

    async def run(self) -> None:
        """Serve the socket until the client disconnects, then stop all work."""
        writer = asyncio.create_task(self._write())
        self.emit(p.session_created(self.info(self.defaults)))
        try:
            while True:
                message = await self.ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                text = message.get("text")
                try:
                    if text is None:
                        raise p.EventError("invalid_event", "Binary frames are not supported")
                    await self._handle(p.parse_event(text))
                except p.EventError as exc:
                    self.emit(p.tts_failed(exc, exc.context_id))
        except WebSocketDisconnect:
            pass
        finally:
            tasks = [c.task for c in self.contexts.values() if c.task is not None]
            for task in (*tasks, writer):
                task.cancel()
            await asyncio.gather(*tasks, writer, return_exceptions=True)

    async def _write(self) -> None:
        while True:
            while not self._out:
                self._wake.clear()
                await self._wake.wait()
            event = self._out.popleft()
            try:
                await self.ws.send_text(json.dumps(event))
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                logger.debug("realtime socket closed while sending: %r", exc)
                return

    async def _handle(self, event: p.ClientEvent) -> None:
        ctx_id = event.context_id
        try:
            if isinstance(event, p.SessionUpdate):
                self._update(event)
            elif isinstance(event, p.Cancel):
                await self._cancel(event.context_id)
            elif isinstance(event, p.Append):
                self._append(self._context(event.context_id), event.text)
            elif isinstance(event, p.Commit):
                self._commit(self._context(event.context_id))
            else:
                self._context(event.context_id).buffer.clear()
        except ApiError as exc:
            self.emit(p.tts_failed(exc, ctx_id))

    def _context(self, context_id: str) -> Context:
        ctx = self.contexts.get(context_id)
        if ctx is None:
            if len(self.contexts) >= MAX_CONTEXTS:
                raise ApiError(
                    400,
                    "too_many_contexts",
                    f"At most {MAX_CONTEXTS} contexts per connection",
                    param="context_id",
                )
            ctx = self.contexts[context_id] = Context(context_id, self.defaults, self.max_partial)
        return ctx

    def _update(self, event: p.SessionUpdate) -> None:
        library = self.state.library
        if event.context_id is None:
            self.defaults = self.defaults.patched(event.session, library)
            for ctx in self.contexts.values():
                self._enqueue(ctx, ctx.set_voicing(ctx.voicing.patched(event.session, library)))
            voicing = self.defaults
        else:
            ctx = self._context(event.context_id)
            self._enqueue(ctx, ctx.set_voicing(ctx.voicing.patched(event.session, library)))
            voicing = ctx.voicing
        self.emit(p.session_updated(self.info(voicing), event.context_id))

    def _append(self, ctx: Context, text: str) -> None:
        if ctx.item_id is None:
            ctx.item_id = _new_id("item")
        self.emit(p.text_received(ctx.id, ctx.item_id, text))
        self._enqueue(ctx, ctx.buffer.append(text))

    def _commit(self, ctx: Context) -> None:
        """Flush the buffer and end the current item; with no item, nothing is sent."""
        self._enqueue(ctx, ctx.buffer.flush())
        if ctx.item_id is not None:
            self._put(ctx, Entry(ctx.item_id, None, ctx.voicing))
            ctx.item_id = None

    async def _cancel(self, context_id: str) -> None:
        ctx = self.contexts.get(context_id)
        if ctx is not None:
            await ctx.reset()
        self._out = deque(
            e
            for e in self._out
            if not (e["type"] in _AUDIO_EVENTS and e.get("context_id") == context_id)
        )
        self.emit(p.context_cancelled(context_id))

    def _enqueue(self, ctx: Context, sentences: list[str]) -> None:
        """Sanitise and queue sentences; ones with nothing speakable are skipped."""
        if not sentences:
            return
        if ctx.item_id is None:
            ctx.item_id = _new_id("item")
        engine = self.state.engine
        for sentence in sentences:
            try:
                pieces = engine.prepare(sentence, ctx.voicing.language)
            except ApiError as exc:
                if exc.code != "empty_input":
                    raise
                continue
            for piece in pieces:
                self._put(ctx, Entry(ctx.item_id, piece, ctx.voicing))

    def _put(self, ctx: Context, entry: Entry) -> None:
        ctx.queue.put_nowait(entry)
        if ctx.task is None:
            ctx.task = asyncio.create_task(self._consume(ctx, ctx.queue))

    async def _consume(self, ctx: Context, queue: asyncio.Queue[Entry]) -> None:
        engine = self.state.engine
        steps = self.state.settings.realtime_steps
        while True:
            entry = await queue.get()
            if entry.item_id == ctx.failed_item:
                continue
            if entry.text is None:
                self.emit(p.audio_done(ctx.id, entry.item_id))
                continue
            v = entry.voicing
            try:
                audio = await engine.synth(
                    entry.text, v.style, v.language, v.speed, steps, PRIORITY_REALTIME
                )
            except ApiError as exc:
                self._fail(ctx, entry.item_id, exc)
                continue
            except Exception:
                logger.exception("realtime synthesis failed")
                err = ApiError(500, "internal_error", "Synthesis failed", type_="server_error")
                self._fail(ctx, entry.item_id, err)
                continue
            pcm = to_pcm16(resample(audio, engine.sample_rate, self.sample_rate))
            delta = base64.b64encode(pcm).decode("ascii")
            self.emit(p.audio_delta(ctx.id, entry.item_id, delta))

    def _fail(self, ctx: Context, item_id: str, exc: ApiError) -> None:
        """Report a failed item; its remaining sentences, buffer and ``done`` are dropped."""
        ctx.failed_item = item_id
        if ctx.item_id == item_id:
            ctx.item_id = None
            ctx.buffer.clear()
        self.emit(p.tts_failed(exc, ctx.id, item_id))


@router.websocket("/v1/audio/speech/websocket")
async def speech_websocket(ws: WebSocket) -> None:
    """Realtime TTS: text streamed in, base64 PCM16 sentences streamed out.

    Authentication happens here (``Authorization: Bearer`` or ``?api_key=``): the socket is
    accepted first so the client gets a ``conversation.item.tts.failed`` event explaining
    the rejection before the 1008 close.
    """
    await ws.accept()
    state: AppState | None = getattr(ws.app.state, "app_state", None)
    if state is None:
        exc = ApiError(503, "not_ready", "Model is still loading", type_="server_error")
        await _reject(ws, exc, _TRY_AGAIN_LATER)
        return
    try:
        check_key(ws, state.settings.api_key)
        params = parse_params(ws.query_params, state)
    except ApiError as exc:
        await _reject(ws, exc, _POLICY_VIOLATION)
        return
    await Session(ws, state, params).run()


async def _reject(ws: WebSocket, exc: ApiError, close_code: int) -> None:
    """Explain a refused connection, then close it (quietly if the client already left)."""
    try:
        await ws.send_json(p.tts_failed(exc, None))
        await ws.close(close_code)
    except (WebSocketDisconnect, RuntimeError, OSError) as err:
        logger.debug("realtime client left during rejection: %r", err)

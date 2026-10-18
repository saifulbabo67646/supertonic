"""Tests for the realtime TTS WebSocket."""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import WS_PATH, recv_json, recv_until
from supertonic_server.api import create_app
from supertonic_server.engine import Engine, Scheduler

if TYPE_CHECKING:
    from starlette.testclient import WebSocketTestSession

    from conftest import WsFactory
    from supertonic_server.core.config import Settings
    from supertonic_server.voices import VoiceLibrary

DELTA = "conversation.item.audio_output.delta"
DONE = "conversation.item.audio_output.done"
FAILED = "conversation.item.tts.failed"


def _deltas(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in msgs if m["type"] == DELTA]


def test_stream_two_sentences_then_done(ws: WebSocketTestSession) -> None:
    created = ws.receive_json()
    assert created["type"] == "session.created" and created["session"]["sample_rate"] == 24000
    ws.send_json({"type": "input_text_buffer.append", "text": "Hello there. How"})
    assert ws.receive_json()["type"] == "conversation.item.input_text.received"
    d1 = ws.receive_json()
    assert d1["type"] == "conversation.item.audio_output.delta"  # before commit
    ws.send_json({"type": "input_text_buffer.append", "text": " are you?"})
    ws.receive_json()
    ws.send_json({"type": "input_text_buffer.commit"})
    msgs = recv_until(ws, "conversation.item.audio_output.done")
    assert (
        sum(m["type"].endswith("delta") for m in msgs) == 1 and msgs[-1]["item_id"] == d1["item_id"]
    )
    assert len(base64.b64decode(d1["delta"])) % 2 == 0


def test_session_created_shape(ws: WebSocketTestSession) -> None:
    session = recv_json(ws)["session"]
    assert session["id"] and session["object"] == "realtime.tts.session"
    assert session["modalities"] == ["audio"] and session["model"] == "supertonic-3"
    assert (session["voice"], session["language"], session["speed"]) == ("F1", "en", 1.05)


def test_contexts_are_independent(ws: WebSocketTestSession) -> None:
    recv_json(ws)
    for ctx, text in (("a", "Alpha one. Alpha two."), ("b", "Beta one.")):
        ws.send_json({"type": "input_text_buffer.append", "text": text, "context_id": ctx})
        ws.send_json({"type": "input_text_buffer.commit", "context_id": ctx})
    msgs: list[dict[str, Any]] = []
    while sum(m["type"] == DONE for m in msgs) < 2:
        msgs.append(recv_json(ws))
    done = {m["context_id"]: m["item_id"] for m in msgs if m["type"] == DONE}
    assert set(done) == {"a", "b"} and done["a"] != done["b"]
    for ctx, n in (("a", 2), ("b", 1)):
        mine = [m for m in _deltas(msgs) if m["context_id"] == ctx]
        assert len(mine) == n and {m["item_id"] for m in mine} == {done[ctx]}
        last_delta = max(i for i, m in enumerate(msgs) if m in mine)
        assert last_delta < msgs.index({"type": DONE, "item_id": done[ctx], "context_id": ctx})


def test_cancel_stops_deltas(ws_slow: WebSocketTestSession) -> None:  # FakeModel(delay=0.1)
    ws_slow.receive_json()
    ws_slow.send_json(
        {"type": "input_text_buffer.append", "text": "A. B. C. D. E.", "context_id": "x"}
    )
    ws_slow.send_json({"type": "context.cancel", "context_id": "x"})
    msgs = recv_until(ws_slow, "context.cancelled")
    assert sum(m["type"].endswith("delta") for m in msgs) <= 1
    assert msgs[-1]["context_id"] == "x"
    ws_slow.send_json(
        {"type": "input_text_buffer.commit", "context_id": "y"}
    )  # socket still usable
    ws_slow.send_json({"type": "input_text_buffer.append", "text": "Hi.", "context_id": "y"})
    after = recv_until(ws_slow, "conversation.item.input_text.received")
    assert [m["type"] for m in after] == ["conversation.item.input_text.received"]
    # Nothing more arrives for the cancelled context, even after its old sentences would be done.
    ws_slow.send_json({"type": "input_text_buffer.commit", "context_id": "y"})
    rest = recv_until(ws_slow, DONE)
    assert all(m.get("context_id") == "y" for m in rest)


def test_append_after_cancel_starts_new_item(ws_slow: WebSocketTestSession) -> None:
    recv_json(ws_slow)
    ws_slow.send_json({"type": "input_text_buffer.append", "text": "One. Two. Three."})
    first = recv_json(ws_slow)
    ws_slow.send_json({"type": "context.cancel"})
    recv_until(ws_slow, "context.cancelled")
    ws_slow.send_json({"type": "input_text_buffer.append", "text": "Four."})
    second = recv_json(ws_slow)
    ws_slow.send_json({"type": "input_text_buffer.commit"})
    msgs = recv_until(ws_slow, DONE)
    assert second["item_id"] != first["item_id"]
    assert [m["item_id"] for m in msgs] == [second["item_id"]] * len(msgs) and len(msgs) == 2


def test_session_update_changes_voice(
    ws: WebSocketTestSession, engine: Engine, lib: VoiceLibrary
) -> None:
    recv_json(ws)
    ws.send_json({"type": "tts_session.updated", "session": {"voice": "m1", "speed": 1.3}})
    updated = recv_json(ws)
    assert updated["type"] == "session.updated"
    assert updated["session"]["voice"] == "M1" and updated["session"]["speed"] == 1.3
    ws.send_json({"type": "input_text_buffer.append", "text": "Hi there."})
    ws.send_json({"type": "input_text_buffer.commit"})
    recv_until(ws, DONE)
    _, style, steps, speed, lang = engine.model.calls[-1]  # type: ignore[attr-defined]
    assert style is lib.style("M1") and style is not lib.style("F1")
    assert (steps, speed, lang) == (3, 1.3, "en")  # realtime_steps


def test_session_update_single_context(
    ws: WebSocketTestSession, engine: Engine, lib: VoiceLibrary
) -> None:
    recv_json(ws)
    ws.send_json({"type": "tts_session.updated", "context_id": "m", "session": {"voice": "M1"}})
    assert recv_json(ws)["context_id"] == "m"
    for ctx in ("m", "f"):
        ws.send_json({"type": "input_text_buffer.append", "text": "Hi.", "context_id": ctx})
        ws.send_json({"type": "input_text_buffer.commit", "context_id": ctx})
        recv_until(ws, DONE)
    styles = [c[1] for c in engine.model.calls]  # type: ignore[attr-defined]
    assert styles == [lib.style("M1"), lib.style("F1")]


def test_session_update_invalid_keeps_socket(ws: WebSocketTestSession) -> None:
    recv_json(ws)
    ws.send_json({"type": "tts_session.updated", "session": {"speed": 5}})
    assert recv_json(ws)["error"]["code"] == "invalid_speed"
    ws.send_json({"type": "tts_session.updated", "session": {"language": "xx"}})
    assert recv_json(ws)["error"]["code"] == "language_not_supported"
    ws.send_json({"type": "tts_session.updated", "session": {}})
    assert recv_json(ws)["session"]["voice"] == "F1"


def test_bad_voice_rejected(client_ws_factory: WsFactory) -> None:
    with client_ws_factory("?voice=nobody") as ws:
        m = ws.receive_json()
        assert (
            m["type"] == "conversation.item.tts.failed" and m["error"]["code"] == "voice_not_found"
        )
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("?language=xx", "language_not_supported"),
        ("?sample_rate=8000", "invalid_sample_rate"),
        ("?sample_rate=abc", "invalid_sample_rate"),
        ("?speed=3", "invalid_speed"),
        ("?max_partial_length=0", "invalid_max_partial_length"),
    ],
)
def test_bad_params_rejected(client_ws_factory: WsFactory, query: str, code: str) -> None:
    with client_ws_factory(query) as ws:
        assert ws.receive_json()["error"]["code"] == code
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_auth_query_param(authed_ws_factory: WsFactory) -> None:
    with authed_ws_factory("?api_key=secret") as ws:
        assert ws.receive_json()["type"] == "session.created"
    with authed_ws_factory("") as ws:
        assert ws.receive_json()["error"]["code"] == "invalid_api_key"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_auth_bearer_header(settings: Settings, engine: Engine, lib: VoiceLibrary) -> None:
    app = create_app(settings.model_copy(update={"api_key": "secret"}), engine, lib)
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app).websocket_connect(WS_PATH, headers=headers) as ws:
        assert ws.receive_json()["type"] == "session.created"


def test_sample_rate_and_options(client_ws_factory: WsFactory) -> None:
    with client_ws_factory("?sample_rate=16000&voice=M1&language=ko&speed=1.2") as ws:
        session = recv_json(ws)["session"]
        assert (session["sample_rate"], session["voice"], session["language"]) == (
            16000,
            "M1",
            "ko",
        )
        ws.send_json({"type": "input_text_buffer.append", "text": "Hi."})
        ws.send_json({"type": "input_text_buffer.commit"})
        (delta,) = _deltas(recv_until(ws, DONE))
    samples = len(base64.b64decode(delta["delta"])) // 2
    assert abs(samples - 0.05 * 3 / 1.2 * 16000) < 10  # FakeModel duration, resampled


def test_unknown_and_invalid_events(ws: WebSocketTestSession) -> None:
    recv_json(ws)
    ws.send_json({"type": "nope", "context_id": "q"})
    m = recv_json(ws)
    assert m["type"] == FAILED and m["error"]["code"] == "unknown_event"
    assert m["context_id"] == "q"
    ws.send_text("not json")
    assert recv_json(ws)["error"]["code"] == "invalid_event"
    ws.send_json({"type": "input_text_buffer.append"})  # missing text
    m = recv_json(ws)
    assert m["error"]["code"] == "invalid_event" and m["error"]["param"] == "text"
    ws.send_bytes(b"\x00")
    assert recv_json(ws)["error"]["code"] == "invalid_event"


def test_commit_without_item_sends_nothing(ws: WebSocketTestSession) -> None:
    recv_json(ws)
    ws.send_json({"type": "input_text_buffer.commit"})
    ws.send_json({"type": "context.cancel"})
    assert recv_json(ws)["type"] == "context.cancelled"  # no done for the empty commit


def test_commit_after_all_sentences_sent_still_done(ws: WebSocketTestSession) -> None:
    recv_json(ws)
    ws.send_json({"type": "input_text_buffer.append", "text": "Done already. "})
    recv_json(ws)
    delta = recv_json(ws)
    ws.send_json({"type": "input_text_buffer.commit"})
    assert recv_json(ws) == {"type": DONE, "item_id": delta["item_id"], "context_id": "default"}


def test_clear_drops_buffered_text(ws: WebSocketTestSession, engine: Engine) -> None:
    recv_json(ws)
    ws.send_json({"type": "input_text_buffer.append", "text": "Kept. Dropped"})
    ws.send_json({"type": "input_text_buffer.clear"})
    ws.send_json({"type": "input_text_buffer.commit"})
    msgs = recv_until(ws, DONE)
    assert len(_deltas(msgs)) == 1
    assert [c[0] for c in engine.model.calls] == [["Kept."]]  # type: ignore[attr-defined]


def test_unspeakable_sentence_skipped(ws: WebSocketTestSession, engine: Engine) -> None:
    recv_json(ws)
    ws.send_json({"type": "input_text_buffer.append", "text": "😀★! Hi 😀there."})
    ws.send_json({"type": "input_text_buffer.commit"})
    msgs = recv_until(ws, DONE)
    assert not any(m["type"] == FAILED for m in msgs)
    assert [c[0] for c in engine.model.calls] == [["!"], ["Hi there."]]  # type: ignore[attr-defined]
    ws.send_json({"type": "input_text_buffer.append", "text": "😀"})
    ws.send_json({"type": "input_text_buffer.commit"})
    msgs = recv_until(ws, DONE)
    assert [m["type"] for m in msgs] == ["conversation.item.input_text.received", DONE]


def test_server_busy_reported(settings: Settings, lib: VoiceLibrary) -> None:
    from fakes import FakeModel

    busy = Engine(FakeModel(), Scheduler(workers=1, max_queue=0))
    with TestClient(create_app(settings, busy, lib)).websocket_connect(WS_PATH) as ws:
        recv_json(ws)
        ws.send_json({"type": "input_text_buffer.append", "text": "Hi. ", "context_id": "c"})
        msgs = recv_until(ws, FAILED)
        assert msgs[-1]["error"]["code"] == "server_busy" and msgs[-1]["context_id"] == "c"
        ws.send_json({"type": "input_text_buffer.commit", "context_id": "c"})
        ws.send_json({"type": "context.cancel", "context_id": "c"})
        assert recv_json(ws)["type"] == "context.cancelled"  # socket still open


def test_disconnect_mid_stream_is_quiet(
    settings: Settings, lib: VoiceLibrary, caplog: pytest.LogCaptureFixture
) -> None:
    from fakes import FakeModel

    caplog.set_level(logging.DEBUG)
    slow = Engine(FakeModel(delay=0.1), Scheduler(workers=1, max_queue=64))
    with TestClient(create_app(settings, slow, lib)).websocket_connect(WS_PATH) as ws:
        recv_json(ws)
        ws.send_json({"type": "input_text_buffer.append", "text": "One. Two. Three. Four. "})
        recv_json(ws)
    # Leaving the block waits for the handler to finish; queued sentences never ran.
    assert len(slow.model.calls) <= 2  # type: ignore[attr-defined]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

"""Tests for the voice library."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from fakes import fake_style, make_style
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import Voice, VoiceLibrary


def test_list_presets(lib: VoiceLibrary) -> None:
    ids = [v.id for v in lib.list()]
    assert ids[:2] == ["F1", "M1"] and lib.get("F1").gender == "female"
    assert lib.get("M1").gender == "male" and lib.get("F1").created_at == ""


def test_import_and_resolve(lib: VoiceLibrary) -> None:
    v = lib.import_style(make_style(), name="My Narrator", tags=["warm"])
    assert v.id == "my-narrator" and v.kind == "custom"
    assert lib.resolve("my-narrator").id == lib.resolve("MY NARRATOR").id == "my-narrator"
    assert lib.resolve("m1").id == "M1"
    assert v.created_at.endswith("+00:00")


def test_import_collision_and_reserved(lib: VoiceLibrary) -> None:
    a = lib.import_style(make_style(), name="Bob")
    b = lib.import_style(make_style(), name="bob")
    assert (a.id, b.id) == ("bob", "bob-2")
    assert lib.import_style(make_style(), name="f1").id == "f1-2"
    assert lib.import_style(make_style(), name="F5").id == "f5-2"


def test_id_match_beats_name_and_ambiguity(lib: VoiceLibrary) -> None:
    lib.import_style(make_style(), name="Twin")
    lib.import_style(make_style(), name="Twin")
    assert lib.resolve("TWIN").id == "twin"
    lib.update("twin", name="Echo")
    lib.update("twin-2", name="Echo")
    with pytest.raises(ApiError) as e:
        lib.resolve("echo")
    assert e.value.code == "ambiguous_voice" and e.value.status == 400


def test_unknown_voice(lib: VoiceLibrary) -> None:
    with pytest.raises(ApiError) as e:
        lib.resolve("nobody")
    assert e.value.status == 404 and "F1" in e.value.message
    with pytest.raises(ApiError) as e2:
        lib.get("nobody")
    assert e2.value.code == "voice_not_found" and e2.value.param == "voice"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["style_ttl"].update(dims=[1, 50, 128]),
        lambda s: s["style_dp"]["data"].pop(),
        lambda s: s["style_ttl"]["data"].__setitem__(0, float("nan")),
        lambda s: s["style_ttl"]["data"][0][0].__setitem__(0, float("inf")),
        lambda s: s["style_dp"]["data"][0][0].pop(),
        lambda s: s.pop("style_dp"),
    ],
)
def test_invalid_style_rejected_and_nothing_written(lib: VoiceLibrary, mutate) -> None:  # type: ignore[no-untyped-def]
    s = make_style()
    mutate(s)
    with pytest.raises(ApiError) as e:
        lib.import_style(s, name="bad")
    assert e.value.code == "invalid_style" and not (lib.custom_dir / "bad").exists()
    assert [v.id for v in lib.list()] == ["F1", "M1"]


def test_failed_write_leaves_nothing(lib: VoiceLibrary, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    calls = {"n": 0}
    real = os.replace

    def flaky(src: str | Path, dst: str | Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(OSError):
        lib.import_style(make_style(), name="Half")
    assert not (lib.custom_dir / "half").exists() and len(lib.list()) == 2


def test_presets_read_only(lib: VoiceLibrary) -> None:
    for op in (lambda: lib.delete("F1"), lambda: lib.update("F1", name="x")):
        with pytest.raises(ApiError) as e:
            op()
        assert e.value.code == "voice_read_only"


def test_style_loads(lib: VoiceLibrary) -> None:
    st = lib.style("F1")
    assert st.ttl.shape == (1, 50, 256) and st.dp.shape == (1, 8, 16)
    assert lib.style("F1") is st
    v = lib.import_style(make_style(1), name="Mine")
    assert lib.style(v.id).ttl.shape == (1, 50, 256)
    assert lib.style_json("mine")["metadata"] == {"seed": 1}


def test_fake_style_helper() -> None:
    assert fake_style(3).dp.shape == (1, 8, 16)


def test_update_delete_and_persistence(lib: VoiceLibrary) -> None:
    v = lib.import_style(make_style(), name="Keep", description="d")
    lib.update(v.id, description="new", tags=["a"])
    again = VoiceLibrary(lib.presets_dir, lib.custom_dir)
    got = again.get("keep")
    assert (got.description, got.tags, got.name) == ("new", ["a"], "Keep")
    assert [x.id for x in again.list()] == ["F1", "M1", "keep"]
    lib.delete("keep")
    assert not (lib.custom_dir / "keep").exists()
    with pytest.raises(ApiError):
        lib.get("keep")


def test_preview_path(lib: VoiceLibrary) -> None:
    v = lib.import_style(make_style(), name="Pv")
    assert lib.preview_path(v.id, "en") == lib.custom_dir / "pv" / "previews" / "en.wav"
    assert (
        lib.preview_path("F1", "ja") == lib.custom_dir / "_presets" / "F1" / "previews" / "ja.wav"
    )
    assert not lib.preview_path("F1", "ja").exists()


def test_voice_defaults_and_to_dict() -> None:
    a, b = Voice("a", "a", "custom"), Voice("b", "b", "custom")
    a.tags.append("x")
    assert b.tags == [] and json.dumps(a.to_dict())


def test_concurrent_imports(lib: VoiceLibrary) -> None:
    ids: list[str] = []

    def work() -> None:
        ids.append(lib.import_style(make_style(), name="Same").id)

    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(ids)) == 8


def _deep(value: object, depth: int) -> object:
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize(
    "data",
    [
        # Right leaf count (8 * 16) but ragged rows.
        [[[0.0] * 17, [0.0] * 15, *([[0.0] * 16] * 6)]],
        _deep(0.0, 5000),
        [[["0.5"] * 16] * 8],
        [[[0.0] * 16] * 7 + [[0.0] * 8 + [[0.0]] * 8]],
    ],
)
def test_ragged_or_deep_style_data_rejected(lib: VoiceLibrary, data: object) -> None:
    from supertonic_server.voices.validation import validate_style

    s = make_style()
    s["style_dp"]["data"] = data
    with pytest.raises(ApiError) as e:
        validate_style(s)
    assert e.value.code == "invalid_style" and e.value.status == 400


def test_flat_style_data_accepted() -> None:
    """The loader reshapes ``data`` to ``dims``, so a flat list of the right length is fine."""
    from supertonic_server.voices.validation import validate_style

    s = make_style()
    s["style_dp"]["data"] = [0.25] * (8 * 16)
    validate_style(s)


def test_orphan_folder_does_not_block_import(lib: VoiceLibrary) -> None:
    """A leftover folder without valid metadata must not make imports fail forever (I9)."""
    (lib.custom_dir / "ghost").mkdir()
    (lib.custom_dir / "ghost" / "style.json").write_text("{}", encoding="utf-8")
    v = lib.import_style(make_style(), name="Ghost")
    assert v.id == "ghost-2" and lib.style(v.id) is not None


def test_save_preview_refuses_deleted_voice(lib: VoiceLibrary) -> None:
    v = lib.import_style(make_style(), name="Gone")
    lib.delete(v.id)
    with pytest.raises(ApiError) as e:
        lib.save_preview(v.id, "en", b"RIFF")
    assert e.value.code == "voice_not_found"
    assert not (lib.custom_dir / v.id).exists()
    assert lib.save_preview("F1", "en", b"RIFF").read_bytes() == b"RIFF"  # presets: _presets


def test_slug_length_and_windows_reserved_names(lib: VoiceLibrary) -> None:
    long = lib.import_style(make_style(), name="x" * 100)
    again = lib.import_style(make_style(), name="x" * 100)
    assert len(long.id) <= 64 and len(again.id) <= 64 and long.id != again.id
    for name in ("CON", "nul", "Aux", "prn", "com1", "LPT9"):
        vid = lib.import_style(make_style(), name=name).id
        assert vid.lower() != name.lower() and vid.startswith(name.lower())
    assert lib.import_style(make_style(), name="com10").id == "com10"


def test_scan_takes_id_from_folder(lib: VoiceLibrary, caplog: pytest.LogCaptureFixture) -> None:
    """voice.json cannot claim another voice's id; mismatches are skipped (M8)."""
    v = lib.import_style(make_style(), name="Real")
    meta = lib.custom_dir / v.id / "voice.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    (lib.custom_dir / "copy").mkdir()
    (lib.custom_dir / "copy" / "style.json").write_text(json.dumps(make_style()), "utf-8")
    (lib.custom_dir / "copy" / "voice.json").write_text(json.dumps(data), "utf-8")  # id "real"
    (lib.custom_dir / "noid").mkdir()
    (lib.custom_dir / "noid" / "style.json").write_text(json.dumps(make_style()), "utf-8")
    del data["id"]
    (lib.custom_dir / "noid" / "voice.json").write_text(json.dumps(data), "utf-8")
    again = VoiceLibrary(lib.presets_dir, lib.custom_dir)
    assert [x.id for x in again.list()] == ["F1", "M1", "noid", "real"]
    assert "copy" in caplog.text

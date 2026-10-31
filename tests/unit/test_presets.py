"""Tests for the named built-in voices."""

from __future__ import annotations

import json

import pytest

from fakes import make_style
from supertonic_server.core.errors import ApiError
from supertonic_server.voices import PRESETS, VoiceLibrary
from supertonic_server.voices.presets import PRESET_IDS, is_reserved, preset_id_for_name

# Names the stock voices of a well-known hosted TTS service use; ours must not clash.
AVOID = {
    "rachel", "adam", "bella", "antoni", "domi", "elli", "josh", "arnold", "sam", "sarah",
    "charlie", "george", "callum", "liam", "charlotte", "alice", "matilda", "will", "jessica",
    "eric", "chris", "brian", "daniel", "lily", "bill", "river", "aria", "laura", "roger",
}  # fmt: skip


def test_every_preset_has_a_distinct_name_and_description() -> None:
    assert set(PRESETS) == {f"{g}{i}" for g in "FM" for i in range(1, 6)} == PRESET_IDS
    names = [p.name.lower() for p in PRESETS.values()]
    assert len(set(names)) == 10 and not set(names) & AVOID
    assert not set(names) & {i.lower() for i in PRESET_IDS}
    for vid, p in PRESETS.items():
        assert p.gender == ("female" if vid[0] == "F" else "male")
        assert p.gender in p.description and p.description.endswith(".")
    assert PRESETS["F1"].description == (
        "Higher-pitched female voice with an unhurried pace; suits narration and explainers."
    )


@pytest.mark.parametrize("ref", ["Mia", "mia", " MIA ", "F1", "f1"])
def test_reserved(ref: str) -> None:
    assert is_reserved(ref)


def test_name_lookup() -> None:
    assert preset_id_for_name("hugo") == "M1" and preset_id_for_name("Narrator") is None


def test_library_lists_names_and_descriptions(lib: VoiceLibrary) -> None:
    f1 = lib.get("F1")
    assert (f1.name, f1.description, f1.gender) == ("Mia", PRESETS["F1"].description, "female")
    assert lib.get("M1").name == "Hugo"


@pytest.mark.parametrize(("ref", "vid"), [("Mia", "F1"), ("mia", "F1"), ("HUGO", "M1")])
def test_resolve_by_preset_name(lib: VoiceLibrary, ref: str, vid: str) -> None:
    assert lib.resolve(ref).id == vid


def test_ids_still_resolve(lib: VoiceLibrary) -> None:
    assert lib.resolve("F1").id == "F1" and lib.resolve("m1").id == "M1"


def test_preset_name_beats_an_older_custom_voice_with_that_name(lib: VoiceLibrary) -> None:
    folder = lib.custom_dir / "old-mia"
    folder.mkdir(parents=True)
    (folder / "style.json").write_text(json.dumps(make_style()), encoding="utf-8")
    meta = {"id": "old-mia", "name": "Mia", "kind": "custom", "created_at": "2026-01-01"}
    (folder / "voice.json").write_text(json.dumps(meta), encoding="utf-8")
    lib = VoiceLibrary(lib.presets_dir, lib.custom_dir)
    assert lib.resolve("mia").id == "F1" and lib.resolve("old-mia").id == "old-mia"
    # editing its description keeps the old name; renaming to another preset name is refused
    assert lib.update("old-mia", name="Mia", description="d").name == "Mia"
    with pytest.raises(ApiError) as e:
        lib.update("old-mia", name="Hugo")
    assert e.value.code == "voice_name_taken"


def _legacy_voice(lib: VoiceLibrary, vid: str, name: str) -> VoiceLibrary:
    folder = lib.custom_dir / vid
    folder.mkdir(parents=True)
    (folder / "style.json").write_text(json.dumps(make_style()), encoding="utf-8")
    meta = {"id": vid, "name": name, "kind": "custom", "created_at": "2026-01-01"}
    (folder / "voice.json").write_text(json.dumps(meta), encoding="utf-8")
    return VoiceLibrary(lib.presets_dir, lib.custom_dir)


def test_built_in_name_beats_a_legacy_folder_named_like_it(lib: VoiceLibrary) -> None:
    lib = _legacy_voice(lib, "mia", "Mia")
    assert lib.resolve("Mia").id == "F1" and lib.resolve("MIA").id == "F1"
    assert lib.resolve("mia").id == "mia"  # the exact id still reaches the old voice
    # and it can still be edited and deleted by that id
    assert lib.update("mia", description="old").description == "old"
    lib.delete("mia")
    assert [v.id for v in lib.list()] == ["F1", "M1"]


def test_id_in_any_capitalisation_still_resolves(lib: VoiceLibrary) -> None:
    lib = _legacy_voice(lib, "old-mia", "Old")
    assert lib.resolve("OLD-MIA").id == "old-mia"


def test_import_never_takes_a_built_in_name_as_id(lib: VoiceLibrary) -> None:
    voice = lib.import_style(make_style(), name="Mia.")
    assert voice.id == "mia-2" and voice.name == "Mia."
    assert lib.resolve("Mia").id == "F1" and lib.resolve("Mia.").id == "mia-2"


@pytest.mark.parametrize("name", ["Mia", "hugo", "F1", " m1 "])
def test_import_with_preset_name_rejected(lib: VoiceLibrary, name: str) -> None:
    with pytest.raises(ApiError) as e:
        lib.import_style(make_style(), name=name)
    assert (e.value.status, e.value.code, e.value.param) == (409, "voice_name_taken", "name")
    assert [v.id for v in lib.list()] == ["F1", "M1"]


def test_rename_to_preset_name_rejected(lib: VoiceLibrary) -> None:
    lib.import_style(make_style(), name="Narrator")
    for name in ("MIA", "f1"):
        with pytest.raises(ApiError) as e:
            lib.update("narrator", name=name)
        assert e.value.code == "voice_name_taken"
    assert lib.get("narrator").name == "Narrator"


def test_preset_by_name_is_read_only(lib: VoiceLibrary) -> None:
    with pytest.raises(ApiError) as e:
        lib.delete("Mia")
    assert e.value.code == "voice_read_only"

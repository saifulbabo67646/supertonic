"""Tests for language metadata and text segmentation."""

import pytest
from supertonic.config import SUPPORTED_LANGUAGES

from supertonic_server.core.errors import ApiError
from supertonic_server.text import (
    LANGUAGES,
    SentenceBuffer,
    get_language,
    sanitize,
    split_sentences,
)


def test_languages_cover_model() -> None:
    assert [lang.code for lang in LANGUAGES] == [*SUPPORTED_LANGUAGES, "na"]
    assert get_language("ja").spaced is False
    with pytest.raises(ApiError) as e:
        get_language("xx")
    assert e.value.code == "language_not_supported"
    assert e.value.status == 400
    assert e.value.param == "language"


def test_language_samples_are_short_and_nonempty() -> None:
    for lang in LANGUAGES:
        assert lang.name
        assert 0 < len(lang.sample) <= 80


def test_split_english() -> None:
    assert split_sentences("Hi there. How are you? Fine!", "en") == [
        "Hi there.",
        "How are you?",
        "Fine!",
    ]


def test_split_japanese() -> None:
    assert split_sentences("こんにちは。元気ですか？はい。", "ja") == [
        "こんにちは。",
        "元気ですか？",
        "はい。",
    ]


def test_split_paragraphs_and_decimals() -> None:
    assert split_sentences("Pi is 3.14 today.\n\nNew paragraph", "en") == [
        "Pi is 3.14 today.",
        "New paragraph",
    ]


def test_split_never_returns_empty() -> None:
    assert split_sentences("  \n\n  ", "en") == []
    assert all(split_sentences("A.  B.\n\n\nC", "en"))


def test_split_long_piece_respects_max_len() -> None:
    text = ("word " * 200).strip()
    parts = split_sentences(text, "en", max_len=100)
    assert all(len(p) <= 100 for p in parts) and " ".join(parts) == text


def test_split_long_unspaced_piece_hard_cuts() -> None:
    parts = split_sentences("あ" * 50, "ja", max_len=20)
    assert all(0 < len(p) <= 20 for p in parts) and "".join(parts) == "あ" * 50


def test_split_korean_default_limit_is_shorter() -> None:
    text = " ".join(["가나다"] * 60)
    assert max(len(p) for p in split_sentences(text, "ko")) <= 120
    assert max(len(p) for p in split_sentences(text, "en")) > 120


def test_sanitize_drops_unsupported() -> None:
    def unsupported(t: str) -> list[str]:
        return [c for c in t if c in "😀★"]

    assert sanitize("Hello 😀 world ★!", unsupported) == "Hello world !"
    assert sanitize("😀 ★", unsupported) == ""


def test_sentence_buffer_streaming() -> None:
    b = SentenceBuffer(max_partial_length=250)
    assert b.append("Hello wor") == []
    assert b.append("ld. How") == ["Hello world."]
    assert b.flush() == ["How"]
    assert b.flush() == []


def test_sentence_buffer_japanese_needs_no_space() -> None:
    b = SentenceBuffer()
    assert b.append("こんにちは。元気") == ["こんにちは。"]
    assert b.flush() == ["元気"]


def test_sentence_buffer_forces_long_partial() -> None:
    b = SentenceBuffer(max_partial_length=20)
    out = b.append("one two three four five six seven")
    assert out and all(len(s) <= 20 for s in out) and not out[0].endswith(" ")


def test_sentence_buffer_clear() -> None:
    b = SentenceBuffer()
    b.append("pending text")
    b.clear()
    assert b.flush() == []


def test_split_hindi_and_arabic() -> None:
    assert split_sentences("नमस्ते।आप कैसे हैं? ठीक हूँ।", "hi") == [
        "नमस्ते।",
        "आप कैसे हैं?",
        "ठीक हूँ।",
    ]
    assert split_sentences("كيف حالك؟ أنا بخير.", "ar") == ["كيف حالك؟", "أنا بخير."]


def test_split_keeps_closing_quote_with_sentence() -> None:
    assert split_sentences('He said "hi." Next one.', "en") == ['He said "hi."', "Next one."]


def test_sentence_buffer_hindi_danda() -> None:
    b = SentenceBuffer()
    assert b.append("नमस्ते। आप") == ["नमस्ते।"]
    assert b.flush() == ["आप"]


def test_sentence_buffer_closing_quote() -> None:
    b = SentenceBuffer()
    assert b.append('He said "hi." Nex') == ['He said "hi."']
    assert b.flush() == ["Nex"]


def test_sentence_buffer_korean_limit() -> None:
    b = SentenceBuffer(lang="ko")
    out = b.append(" ".join(["가나다"] * 60))
    assert out and all(len(s) <= 120 for s in out)
    assert all(len(s) <= 120 for s in b.flush())
    assert SentenceBuffer(max_partial_length=50, lang="ko")._max_partial == 50

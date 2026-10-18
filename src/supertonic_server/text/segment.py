"""Text sanitising and sentence segmentation for synthesis."""

from __future__ import annotations

import re
from collections.abc import Callable

DEFAULT_MAX_LEN = 300
_MAX_LEN_BY_LANG = {"ko": 120}
_SOFT_BREAKS = ",;:、"

_PARAGRAPH = re.compile(r"\n\s*\n")
# Terminators needing no following space (CJK, Devanagari danda, Arabic question mark, ellipsis),
# and optional closing quotes/brackets that stay attached to the sentence.
_TERM = "。！？।॥؟…"
_CLOSE = "\"'”’»」』）)\\]"
_SENTENCE = re.compile(
    rf"(.*?(?:[{_TERM}]+[{_CLOSE}]*|[.!?]+[{_CLOSE}]*(?=\s|\Z))|.+)\s*", re.DOTALL
)
_WHITESPACE = re.compile(r"\s+")
# A buffered sentence is complete after a no-space terminator or .!? plus whitespace.
_COMPLETE = re.compile(rf"[{_TERM}]+[{_CLOSE}]*|[.!?]+[{_CLOSE}]*\s|\n\s*\n")


def sanitize(text: str, unsupported: Callable[[str], list[str]]) -> str:
    """Drop characters the model cannot render, collapse whitespace and strip.

    Args:
        text: Raw input text.
        unsupported: Returns the characters of ``text`` the model cannot handle.
    """
    for bad in set(unsupported(text)):
        if bad:
            text = text.replace(bad, " ")
    return _WHITESPACE.sub(" ", text).strip()


def _cut_point(piece: str, max_len: int) -> int:
    """Index at which to cut ``piece`` so the head is at most ``max_len`` long."""
    best = -1
    for i, ch in enumerate(piece[: max_len + 1]):
        if ch.isspace():
            best = i
        elif ch in _SOFT_BREAKS and i < max_len:
            best = i + 1
    return best if best > 0 else max_len


def _split_long(piece: str, max_len: int) -> list[str]:
    parts: list[str] = []
    while len(piece) > max_len:
        cut = _cut_point(piece, max_len)
        head, piece = piece[:cut].strip(), piece[cut:].strip()
        if head:
            parts.append(head)
    if piece:
        parts.append(piece)
    return parts


def _split(text: str, max_len: int) -> list[str]:
    sentences: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = _WHITESPACE.sub(" ", paragraph).strip()
        for sentence in _SENTENCE.findall(paragraph):
            sentence = sentence.strip()
            if sentence:
                sentences.extend(_split_long(sentence, max_len))
    return sentences


def _default_max_len(lang: str) -> int:
    return _MAX_LEN_BY_LANG.get(lang, DEFAULT_MAX_LEN)


def split_sentences(text: str, lang: str, max_len: int | None = None) -> list[str]:
    """Split ``text`` into sentences ready to synthesise.

    Splits on paragraph breaks and sentence ends, then splits any piece longer
    than ``max_len`` at the last ``, ; : 、`` or space before the limit.

    Args:
        text: Input text.
        lang: Language code; Korean uses a shorter default limit (120).
        max_len: Maximum piece length (default 300, or 120 for ``ko``).

    Returns:
        Non-empty sentences in order.
    """
    limit = max_len if max_len is not None else _default_max_len(lang)
    return _split(text, limit)


class SentenceBuffer:
    """Accumulates streamed text and releases complete sentences.

    Args:
        max_partial_length: When the unfinished remainder grows past this, it is
            emitted up to the last word boundary so synthesis is not stalled.
        lang: Language code; emitted pieces respect the same per-language length
            limit as :func:`split_sentences` (120 for Korean, 300 otherwise).
    """

    def __init__(self, max_partial_length: int = 250, *, lang: str = "en") -> None:
        self._max_len = _default_max_len(lang)
        self._max_partial = min(max_partial_length, self._max_len)
        self._buf = ""

    def append(self, text: str) -> list[str]:
        """Add text; return sentences that are now complete."""
        self._buf += text
        out: list[str] = []
        end = 0
        for match in _COMPLETE.finditer(self._buf):
            end = match.end()
        if end:
            out.extend(_split(self._buf[:end], self._max_len))
            self._buf = self._buf[end:].lstrip()
        while len(self._buf) > self._max_partial:
            cut = _cut_point(self._buf, self._max_partial)
            head, self._buf = self._buf[:cut].strip(), self._buf[cut:].lstrip()
            if head:
                out.append(head)
        return out

    def flush(self) -> list[str]:
        """Return whatever text remains (if any) and reset the buffer."""
        rest, self._buf = self._buf, ""
        return _split(rest, self._max_len)

    def clear(self) -> None:
        """Discard any buffered text."""
        self._buf = ""

"""Dependency-free WAV helpers (no numpy), usable from thin clients such as the MCP server."""

from __future__ import annotations

import struct

UNKNOWN_SIZE = 0xFFFFFFFF


def finalize_wav(data: bytes) -> bytes:
    """Return a complete WAV file with correct RIFF and ``data`` sizes.

    Streamed WAVs (see :func:`wav_header` with ``data_len=None``) carry ``0xFFFFFFFF`` size
    fields, which many players and Python's :mod:`wave` reject once the bytes are saved to a
    file. The ``data`` chunk is located by walking the chunk list, so headers with extra
    chunks (``LIST``, ``fact``, ...) are handled; everything after it is the payload.

    Raises:
        ValueError: ``data`` is not a RIFF/WAVE file or has no ``data`` chunk.
    """
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        if chunk_id == b"data":
            payload = len(data) - offset - 8
            if payload > UNKNOWN_SIZE - 36:
                raise ValueError("WAV payload too large for a 32-bit size field")
            out = bytearray(data)
            struct.pack_into("<I", out, 4, len(data) - 8)
            struct.pack_into("<I", out, offset + 4, payload)
            return bytes(out)
        (size,) = struct.unpack_from("<I", data, offset + 4)
        offset += 8 + size + (size & 1)  # chunks are padded to an even size
    raise ValueError("WAV file has no data chunk")

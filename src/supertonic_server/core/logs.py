"""Logging helpers: keep API keys passed as ``?api_key=`` out of access logs."""

from __future__ import annotations

import logging
import re

_API_KEY = re.compile(r"(\bapi_key=)[^&\s\"']*", re.IGNORECASE)


def redact_api_key(text: str) -> str:
    """Replace the value of every ``api_key=`` query parameter in ``text`` with ``***``."""
    return _API_KEY.sub(r"\1***", text)


class RedactApiKeyFilter(logging.Filter):
    """Logging filter that redacts ``api_key=`` values from a record's message and args.

    Browsers can only authenticate the realtime WebSocket with ``?api_key=``, and uvicorn's
    access log prints the full request path, query string included.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the record in place; never drops it."""
        if isinstance(record.msg, str):
            record.msg = redact_api_key(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_api_key(a) if isinstance(a, str) else a for a in record.args)
        return True

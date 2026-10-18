"""Host and Origin rules for a server without an API key (CSRF and DNS-rebinding defence).

Without a key the server trusts whoever can reach it, which on loopback means programs on
this machine. A web page the user visits can reach it too: it can send "simple" cross-site
requests (a multipart ``POST`` needs no CORS preflight), and through DNS rebinding it can
even read the answers under its own host name. Browsers always name the page's origin in
``Origin`` (on every cross-origin request and WebSocket) and the host they think they talk
to in ``Host``, so both are checked; programs that send neither (curl, SDKs) pass.
"""

from __future__ import annotations

from collections.abc import Iterable

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::"})
_HTTP_SCHEME = {"ws": "http", "wss": "https"}


def hostname(host: str) -> str:
    """The lower-case host name of a ``Host`` value: ``"[::1]:8787"`` -> ``"::1"``."""
    value = host.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:  # name:port (more colons: a bare IPv6 address)
        value = value.partition(":")[0]
    return value.rstrip(".")


def normalise_origin(origin: str) -> str:
    """Compare origins case-insensitively and without a trailing slash."""
    return origin.strip().lower().rstrip("/")


def trusted_hosts(bind_host: str, extra: Iterable[str]) -> frozenset[str]:
    """Loopback names, the bind host (unless it is a wildcard) and ``extra``."""
    names = set(LOCAL_HOSTS)
    if bind_host.strip() not in WILDCARD_BINDS:
        names.add(hostname(bind_host))
    names.update(hostname(h) for h in extra if h.strip())
    return frozenset(names)


def own_origin(scheme: str, host: str) -> str:
    """The origin a page served by this request's ``Host`` would have."""
    return normalise_origin(f"{_HTTP_SCHEME.get(scheme, scheme)}://{host}")

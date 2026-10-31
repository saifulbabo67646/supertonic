"""One-step start for people who are not developers: ``supertonic-server launch``.

The double-click launchers at the repository root only make sure ``uv`` and the
dependencies are installed, then run this. It owns the parts that would otherwise be
written three times in three shells:

* if a Supertonic server already answers on the preferred port, open the Studio and exit;
* otherwise pick a free port (the preferred one, else the next free one up to 12 above it;
  with ``--port`` only that one);
* start the server and, once ``/v1/health`` answers, open the Studio in the browser.

Every message here is read by people who may never have used a terminal: keep it plain.
"""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from collections.abc import Callable
from typing import Any

import httpx

MODEL_ID = "supertonic-3"
HEALTH_PATH = "/v1/health"
PORT_SPAN = 13  # the preferred port and the 12 above it (8787 to 8799 by default)
READY_TIMEOUT_S = 600.0  # the first start downloads the model (~400 MB)
TROUBLESHOOTING = "docs/troubleshooting.md"

WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]"}


class NoFreePortError(Exception):
    """Raised when the preferred port and every port in the span above it are in use."""


def browser_host(host: str) -> str:
    """Return the address a browser on this machine should use for a server bound to ``host``."""
    if host in WILDCARD_HOSTS:
        return "127.0.0.1"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def studio_url(host: str, port: int) -> str:
    """Return the Studio URL (with a trailing slash) for a server bound to ``host:port``."""
    return f"http://{browser_host(host)}:{port}/"


def probe_health(base_url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    """Return the JSON from ``GET /v1/health`` at ``base_url``, or ``None`` if nothing answers."""
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.get(base_url.rstrip("/") + HEALTH_PATH)
        if response.status_code != 200:
            return None
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def is_supertonic(health: dict[str, Any] | None) -> bool:
    """Return whether a health response comes from a Supertonic server."""
    return health is not None and health.get("model") == MODEL_ID


def port_is_free(host: str, port: int) -> bool:
    """Return whether nothing listens on ``host:port`` and it can be bound.

    The connect check matters on Windows, where binding a specific address succeeds even
    while another program listens on the wildcard address for the same port.
    """
    target = browser_host(host).strip("[]")
    family = socket.AF_INET6 if ":" in target else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as conn:
        conn.settimeout(0.5)
        if conn.connect_ex((target, port)) == 0:
            return False
    bind_host = host.strip("[]") if host not in WILDCARD_HOSTS else ""
    bind_family = socket.AF_INET6 if ":" in bind_host or host in {"::", "[::]"} else socket.AF_INET
    with socket.socket(bind_family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
        except OSError:
            return False
    return True


def choose_port(
    host: str,
    preferred: int,
    *,
    span: int = PORT_SPAN,
    is_free: Callable[[str, int], bool] = port_is_free,
) -> int:
    """Return the first free port from ``preferred`` up to ``preferred + span - 1``.

    Raises:
        NoFreePortError: every port in the range is in use.
    """
    for port in range(preferred, min(preferred + span, 65536)):
        if is_free(host, port):
            return port
    last = min(preferred + span - 1, 65535)
    raise NoFreePortError(f"ports {preferred} to {last} are all in use")


def open_in_browser(url: str, opener: Callable[[str], bool] | None = None) -> None:
    """Open ``url`` in the default browser; if that fails, say how to open it by hand."""
    try:
        opened = (opener or webbrowser.open)(url)
    except Exception:  # noqa: BLE001 - any browser failure only means "open it yourself"
        opened = False
    if not opened:
        say(f"Could not open your browser automatically. Open this address yourself: {url}")


def say(message: str = "", *, end: str = "\n") -> None:
    """Print a message for the person at the console, right away."""
    print(message, end=end, flush=True)


class ReadyWatcher(threading.Thread):
    """Wait in the background until the server answers, then announce it and open the Studio.

    Prints a dot every ``dot_every`` seconds while waiting so a long first start (the model
    download) does not look frozen.
    """

    def __init__(
        self,
        url: str,
        *,
        open_browser: bool,
        timeout: float = READY_TIMEOUT_S,
        interval: float = 0.5,
        dot_every: float = 3.0,
        probe: Callable[[str], dict[str, Any] | None] | None = None,
        opener: Callable[[str], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(name="supertonic-ready", daemon=True)
        self.url = url
        self.open_browser = open_browser
        self.timeout = timeout
        self.interval = interval
        self.dot_every = dot_every
        self._probe = probe
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._stop_event = threading.Event()
        self.ready = False

    def stop(self) -> None:
        """Stop waiting (the server is shutting down)."""
        self._stop_event.set()

    def run(self) -> None:
        """Poll the health endpoint; announce readiness or a timeout."""
        start = self._clock()
        next_dot = start + self.dot_every
        while not self._stop_event.is_set():
            if is_supertonic((self._probe or probe_health)(self.url)):
                self.ready = True
                self._announce()
                return
            now = self._clock()
            if now - start >= self.timeout:
                say()
                say(
                    "Supertonic is taking much longer than usual to start. Leave this window "
                    f"open a little longer, or see {TROUBLESHOOTING}."
                )
                return
            if now >= next_dot:
                say(".", end="")
                next_dot = now + self.dot_every
            self._sleep(self.interval)

    def _announce(self) -> None:
        say()
        say(f"Supertonic is ready: {self.url}")
        say("Keep this window open while you use it. To stop Supertonic, close this window")
        say("or press Ctrl+C.")
        if self.open_browser:
            open_in_browser(self.url, self._opener)


def already_running(
    host: str,
    port: int,
    *,
    open_browser: bool,
    span: int = PORT_SPAN,
    probe: Callable[[str], dict[str, Any] | None] | None = None,
    opener: Callable[[str], bool] | None = None,
) -> bool:
    """If Supertonic already answers on ``port`` or one of the ``span - 1`` ports above it
    (where the launcher would have put it), say so, open the Studio and return True."""
    check = probe or probe_health
    for candidate in range(port, min(port + span, 65536)):
        url = studio_url(host, candidate)
        if is_supertonic(check(url)):
            say(f"Supertonic is already running: {url}")
            if open_browser:
                say("Opening it in your browser.")
                open_in_browser(url, opener)
            return True
    return False


def first_start_note() -> None:
    """Explain the wait before the first start finishes."""
    say("Starting Supertonic. The first start downloads the voice model (about 400 MB),")
    say("which can take a few minutes. Later starts take a few seconds.")


def fail(message: str) -> None:
    """Print an error for the person at the console, with where to find help."""
    say()
    say(f"Supertonic could not start: {message}")
    say(f"For help, see {TROUBLESHOOTING} in the Supertonic folder.")

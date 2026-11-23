"""Run the app with uvicorn in a background thread with a clean, safe shutdown."""
from __future__ import annotations

import ipaddress
import logging
import logging.handlers
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from .config import AppConfig, Paths, load_config
from .main import create_app

log = logging.getLogger("readingclub")


def setup_logging(paths: Paths) -> None:
    paths.ensure()
    # A windowed (no console) executable has no stdout/stderr.
    if sys.stdout is None:
        sys.stdout = open(Path(paths.logs_dir) / "stdout.log", "a", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(Path(paths.logs_dir) / "stderr.log", "a", encoding="utf-8")  # noqa: SIM115
    root = logging.getLogger()
    if any(getattr(h, "_rc", False) for h in root.handlers):
        return
    handler = logging.handlers.RotatingFileHandler(
        paths.logs_dir / "server.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler._rc = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def local_addresses() -> list[dict]:
    """IPv4 addresses of this machine, classified as lan / tailscale."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:  # primary outbound interface (no packets are sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    out = []
    tailnet = ipaddress.ip_network("100.64.0.0/10")
    for addr in sorted(found):
        ip = ipaddress.ip_address(addr)
        if ip.is_loopback or ip.is_link_local:
            continue
        kind = "tailscale" if ip in tailnet else ("lan" if ip.is_private else "other")
        out.append({"address": addr, "kind": kind})
    out.sort(key=lambda a: {"lan": 0, "tailscale": 1, "other": 2}[a["kind"]])
    return out


class ServerController:
    def __init__(self, paths: Paths, config: AppConfig | None = None, app_kwargs: dict | None = None):
        self.paths = paths
        self.config = config or load_config(paths)
        self.app_kwargs = app_kwargs or {}
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.error: BaseException | None = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive() and self.server and self.server.started)

    def start(self, timeout: float = 30) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.error = None
        app = create_app(self.paths.data_dir, config=self.config, **self.app_kwargs)
        cfg = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=5,
            proxy_headers=False,
        )
        self.server = uvicorn.Server(cfg)
        self.server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

        def run():
            try:
                self.server.run()
            except BaseException as exc:  # noqa: BLE001
                self.error = exc
                log.exception("Server crashed")

        self.thread = threading.Thread(target=run, name="uvicorn", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                log.info("Server listening on %s:%s", self.config.host, self.config.port)
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        raise RuntimeError(f"Server failed to start: {self.error or 'port may already be in use'}")

    def stop(self, timeout: float = 15) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout)
        self.thread = None
        self.server = None
        log.info("Server stopped")

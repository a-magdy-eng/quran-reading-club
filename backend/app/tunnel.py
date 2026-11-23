"""Built-in online sharing through a Cloudflare Tunnel.

The host laptop opens an *outbound* encrypted connection to Cloudflare; Cloudflare
gives the club a public https:// address and forwards requests through that
connection to the local server. Nothing is opened on the router or firewall and
the laptop's IP address is never exposed.

Two modes:
* Quick tunnel (default, no account): a random https://<words>.trycloudflare.com
  address that changes every time sharing is started.
* Named tunnel (optional): set "cloudflare_tunnel_token" and "public_url" in
  config.json to use your own stable hostname from a free Cloudflare account.

cloudflared is Cloudflare's official, Apache-2.0 licensed connector. It is
downloaded on first use from Cloudflare's GitHub releases and accepted only if
its Windows Authenticode signature is valid and issued to Cloudflare.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from .config import Paths, bundle_dir

log = logging.getLogger("readingclub.tunnel")

DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
QUICK_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CONNECTED_RE = re.compile(r"Registered tunnel connection|Connection [0-9a-f-]+ registered", re.I)
EXE_NAME = "cloudflared.exe" if os.name == "nt" else "cloudflared"


class TunnelError(Exception):
    pass


def local_binary_path(paths: Paths) -> Path:
    return paths.data_dir / "bin" / EXE_NAME


def find_cloudflared(paths: Paths) -> Path | None:
    for candidate in (local_binary_path(paths), bundle_dir() / EXE_NAME):
        if candidate.is_file():
            return candidate
    found = shutil.which("cloudflared")
    return Path(found) if found else None


def verify_signature(path: Path) -> None:
    """Accept the binary only with a valid Authenticode signature from Cloudflare (Windows)."""
    if os.name != "nt":
        return
    ps = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:QRC_FILE; "
        "Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "QRC_FILE": str(path)},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    status = lines[0] if lines else ""
    subject = lines[1] if len(lines) > 1 else ""
    if status != "Valid" or "cloudflare" not in subject.lower():
        raise TunnelError(f"cloudflared signature check failed ({status or 'no signature'}; {subject or 'unknown signer'}).")


def download_cloudflared(paths: Paths, progress: Callable[[str], None] | None = None) -> Path:
    target = local_binary_path(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("Downloading cloudflared from Cloudflare (about 55 MB)…")
    fd, tmp_name = tempfile.mkstemp(suffix=".exe", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "quran-reading-club"})
        with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as fh:
            shutil.copyfileobj(r, fh, length=1 << 20)
        if progress:
            progress("Checking Cloudflare's digital signature…")
        verify_signature(tmp)
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return target


def _kill_with_parent(proc: subprocess.Popen):
    """Windows: put the child in a job object that is closed (killing the child)
    when this process exits, even after a crash. Returns the job handle."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = k32.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # ExtendedLimitInformation
        handle = k32.OpenProcess(0x0101, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        k32.AssignProcessToJobObject(job, handle)
        k32.CloseHandle(handle)
        return job
    except Exception:  # noqa: BLE001 - best effort
        log.debug("Could not create job object", exc_info=True)
        return None


class TunnelController:
    """Runs cloudflared as a child process and reports the public URL."""

    def __init__(
        self,
        port: int,
        paths: Paths,
        token: str | None = None,
        fixed_url: str | None = None,
        command: list[str] | None = None,  # override for tests
    ):
        self.port = port
        self.paths = paths
        self.token = token or None
        self.fixed_url = (fixed_url or "").rstrip("/") or None
        self.command = command
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.status = "stopped"  # stopped | starting | online | error
        self.error: str | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.on_change: Callable[[], None] | None = None

    @property
    def named(self) -> bool:
        return bool(self.token)

    def public_url(self) -> str | None:
        return self.url if self.status == "online" else None

    def _set(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                pass

    def build_command(self, binary: Path) -> list[str]:
        if self.command:
            return self.command
        base = [str(binary), "tunnel", "--no-autoupdate"]
        if self.token:
            return base + ["run", "--token", self.token]
        return base + ["--url", f"http://127.0.0.1:{self.port}"]

    def start(self, timeout: float = 60, progress: Callable[[str], None] | None = None) -> str:
        with self._lock:
            if self.proc and self.proc.poll() is None and self.url:
                return self.url
            self._ready.clear()
            self.url = None
            self._set("starting")
            binary = None
            if not self.command:
                binary = find_cloudflared(self.paths)
                if binary is None:
                    try:
                        binary = download_cloudflared(self.paths, progress)
                    except Exception as exc:  # noqa: BLE001
                        self._set("error", f"Could not get cloudflared: {exc}")
                        raise TunnelError(self.error) from exc
            cmd = self.build_command(binary)  # type: ignore[arg-type]
            self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                self._set("error", f"Could not start cloudflared: {exc}")
                raise TunnelError(self.error) from exc
            self._job = _kill_with_parent(self.proc)
            threading.Thread(target=self._pump, args=(self.proc,), name="cloudflared-log", daemon=True).start()
        if progress:
            progress("Connecting to Cloudflare…")
        if not self._ready.wait(timeout):
            self.stop()
            self._set("error", "Cloudflare did not answer in time. Check the internet connection and try again.")
            raise TunnelError(self.error)
        if self.status != "online" or not self.url:
            raise TunnelError(self.error or "The tunnel stopped unexpectedly.")
        return self.url

    def _pump(self, proc: subprocess.Popen) -> None:
        log_path = self.paths.logs_dir / "tunnel.log"
        with log_path.open("a", encoding="utf-8") as logf:
            assert proc.stdout is not None
            for line in proc.stdout:
                logf.write(line)
                logf.flush()
                if self.url is None:
                    m = QUICK_URL_RE.search(line)
                    if m and not self.named:
                        self.url = m.group(0)
                    elif self.named and CONNECTED_RE.search(line):
                        self.url = self.fixed_url
                    if self.url:
                        log.info("Online sharing at %s", self.url)
                        self._set("online")
                        self._ready.set()
        code = proc.wait()
        if self.proc is proc:
            was_online = self.status == "online"
            self.url = None
            if self.status != "stopped":
                self._set("error", f"cloudflared exited (code {code}); see logs/tunnel.log" if not was_online else "Online sharing stopped unexpectedly; see logs/tunnel.log")
            self._ready.set()

    def stop(self) -> None:
        with self._lock:
            proc, self.proc = self.proc, None
            self.url = None
            self._set("stopped")
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            self._ready.set()


__all__ = ["TunnelController", "TunnelError", "find_cloudflared", "download_cloudflared"]

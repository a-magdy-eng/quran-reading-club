"""Application configuration (data/config.json) and filesystem locations."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765

# Only private address space may reach the server. 100.64.0.0/10 is the
# Tailscale (CGNAT) range. Public internet addresses are always refused.
DEFAULT_ALLOWED_NETWORKS = [
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "100.64.0.0/10",
    "fc00::/7",
    "fe80::/10",
    "fd7a:115c:a1e0::/48",
]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory holding read-only bundled resources."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent  # repository root


def default_data_dir() -> Path:
    env = os.environ.get("READINGCLUB_DATA")
    if env:
        return Path(env).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent / "data"
    return bundle_dir() / "data"


def frontend_dist_dir() -> Path:
    if is_frozen():
        return bundle_dir() / "frontend_dist"
    return bundle_dir() / "frontend" / "dist"


@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    # Creating new groups is only allowed from the host laptop itself unless enabled.
    allow_remote_group_creation: bool = False
    allowed_networks: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_NETWORKS))
    token_ttl_days: int = 30
    auto_backup_hours: int = 24
    backups_to_keep: int = 14
    open_browser_on_start: bool = True
    # Online sharing (Cloudflare Tunnel). Quick tunnels need no account.
    online_sharing_on_start: bool = False
    # Optional named tunnel for a stable address: token from the Cloudflare
    # dashboard plus the public hostname you routed to http://localhost:<port>.
    cloudflare_tunnel_token: str = ""
    public_url: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "AppConfig":
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        cfg = cls(**known)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not (1 <= int(self.port) <= 65535):
            raise ValueError(f"Invalid port {self.port}")
        self.port = int(self.port)
        self.token_ttl_days = max(1, int(self.token_ttl_days))
        self.backups_to_keep = max(1, int(self.backups_to_keep))
        self.auto_backup_hours = max(0, int(self.auto_backup_hours))


@dataclass
class Paths:
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "readingclub.db"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure(self) -> None:
        for p in (self.data_dir, self.backups_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)


def load_config(paths: Paths) -> AppConfig:
    """Load config.json, creating it with defaults (and filling new keys) if needed."""
    paths.ensure()
    raw: dict = {}
    if paths.config_path.exists():
        try:
            raw = json.loads(paths.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"config.json is not valid JSON: {exc}") from exc
    cfg = AppConfig.from_dict(raw)
    merged = {**asdict(cfg), **{k: v for k, v in raw.items() if k not in asdict(cfg)}}
    if merged != raw:
        paths.config_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return cfg

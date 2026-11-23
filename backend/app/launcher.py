"""Desktop launcher: starts the server, shows connection URLs, backups, safe shutdown.

Usage (packaged):   QuranReadingClub.exe            -> window
                    QuranReadingClub.exe --headless -> console only (Ctrl+C to stop)
                    QuranReadingClub.exe --backup   -> write a backup and exit
                    QuranReadingClub.exe --restore FILE.zip   (server must be stopped)
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import APP_ID, APP_NAME, __version__
from .backup import BackupError, create_backup, list_backups, restore_backup
from .config import Paths, default_data_dir, load_config
from .server import ServerController, local_addresses, port_in_use, setup_logging
from .tunnel import TunnelController, TunnelError, find_cloudflared

log = logging.getLogger("readingclub")

FIREWALL_RULE = "Quran Reading Club"


def is_our_server(port: int) -> bool:
    try:
        import urllib.request
        import json

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return json.loads(r.read().decode()).get("app") == APP_ID
    except Exception:
        return False


def firewall_command(port: int) -> str:
    """Two inbound rules: LAN on private networks, and Tailscale's range on any profile."""
    name = FIREWALL_RULE
    return (
        f'netsh advfirewall firewall delete rule name="{name}" >nul 2>&1 & '
        f'netsh advfirewall firewall delete rule name="{name} (Tailscale)" >nul 2>&1 & '
        f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow protocol=TCP '
        f"localport={port} profile=private remoteip=LocalSubnet & "
        f'netsh advfirewall firewall add rule name="{name} (Tailscale)" dir=in action=allow protocol=TCP '
        f"localport={port} profile=any remoteip=100.64.0.0/10"
    )


def add_firewall_rules(port: int) -> bool:
    """Ask Windows (UAC prompt) to add the firewall rules. Returns True if launched."""
    if os.name != "nt":
        return False
    params = f'/c {firewall_command(port)}'
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", params, None, 0)  # type: ignore[attr-defined]
    return rc > 32


def open_folder(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class LauncherWindow:
    BG = "#0f1513"
    CARD = "#161e1b"
    TEXT = "#e9eeeb"
    MUTED = "#8b9a93"
    ACCENT = "#3fb68b"
    GOLD = "#d9b45b"
    DANGER = "#e0686b"

    def __init__(self, ctl: ServerController, tunnel: TunnelController):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ctl = ctl
        self.tunnel = tunnel
        self.tunnel_note = ""
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} — Host")
        self.root.configure(bg=self.BG)
        self.root.minsize(560, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.CARD)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.CARD, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.CARD, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Url.TLabel", background=self.CARD, foreground=self.ACCENT, font=("Consolas", 11, "bold"))
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI Semibold", 16))
        style.configure("Status.TLabel", background=self.BG, foreground=self.ACCENT, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background="#24302c", foreground=self.TEXT, borderwidth=0, padding=(12, 7), font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#2e3c37")])
        style.configure("Primary.TButton", background=self.ACCENT, foreground="#04140d", font=("Segoe UI Semibold", 10))
        style.map("Primary.TButton", background=[("active", "#52cda0")])
        style.configure("Danger.TButton", background="#3a2324", foreground=self.DANGER)
        style.map("Danger.TButton", background=[("active", "#4a2a2b")])
        style.configure("Small.TButton", padding=(8, 3), font=("Segoe UI", 9))

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="۞  " + APP_NAME, style="Title.TLabel").pack(anchor="w")
        self.status = ttk.Label(outer, text="", style="Status.TLabel")
        self.status.pack(anchor="w", pady=(2, 12))

        self.urls_frame = ttk.Frame(outer, style="Card.TFrame", padding=14)
        self.urls_frame.pack(fill="x")

        online = ttk.Frame(outer, style="Card.TFrame", padding=14)
        online.pack(fill="x", pady=(10, 0))
        head = ttk.Frame(online, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Share online (friends anywhere)", style="Card.TLabel", font=("Segoe UI Semibold", 10)).pack(side="left")
        self.share_btn = ttk.Button(head, text="Share online", style="Primary.TButton", command=self.toggle_sharing)
        self.share_btn.pack(side="right")
        row = ttk.Frame(online, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        self.online_url = ttk.Label(row, text="", style="Url.TLabel")
        self.online_url.pack(side="left")
        self.copy_online = ttk.Button(row, text="Copy", style="Small.TButton", command=lambda: self.tunnel.url and self.copy(self.tunnel.url))
        self.online_note = ttk.Label(online, text="", style="Muted.TLabel", justify="left", wraplength=520)
        self.online_note.pack(anchor="w", pady=(6, 0))
        self.auto_share = tk.BooleanVar(value=self.ctl.config.online_sharing_on_start)
        ttk.Checkbutton(online, text="Start sharing automatically when the club starts", variable=self.auto_share, command=self.save_auto_share).pack(anchor="w", pady=(6, 0))
        style.configure("TCheckbutton", background=self.CARD, foreground=self.MUTED, font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", self.CARD)])

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Open in browser", style="Primary.TButton", command=self.open_browser).pack(side="left")
        ttk.Button(actions, text="Back up now", command=self.backup).pack(side="left", padx=6)
        ttk.Button(actions, text="Restore…", command=self.restore).pack(side="left")
        ttk.Button(actions, text="Data folder", command=lambda: open_folder(self.ctl.paths.data_dir)).pack(side="left", padx=6)

        actions2 = ttk.Frame(outer)
        actions2.pack(fill="x", pady=(8, 0))
        ttk.Button(actions2, text="Allow through Windows Firewall", command=self.firewall).pack(side="left")
        ttk.Button(actions2, text="Stop server & exit", style="Danger.TButton", command=self.on_close).pack(side="right")

        info = ttk.Frame(outer, style="Card.TFrame", padding=12)
        info.pack(fill="x", pady=(14, 0))
        self.info_label = ttk.Label(info, text="", style="Muted.TLabel", justify="left", wraplength=520)
        self.info_label.pack(anchor="w")

        self.refresh_urls()
        self.refresh_status()
        self.refresh_tunnel()
        if self.ctl.config.online_sharing_on_start:
            self.root.after(500, lambda: self.start_sharing(confirm=False))

    # -- online sharing ---------------------------------------------------
    def refresh_tunnel(self):
        t = self.tunnel
        if t.status == "online" and t.url:
            self.online_url.configure(text=t.url, foreground=self.ACCENT)
            if not self.copy_online.winfo_ismapped():
                self.copy_online.pack(side="right")
            self.share_btn.configure(text="Stop sharing", style="Danger.TButton", state="normal")
            note = (
                "Anyone with this link can open the sign-in page; only people with an account or your invitation code can "
                "get in. Traffic is HTTPS-encrypted by Cloudflare and your router stays closed."
            )
            if not t.named:
                note += " This free link changes each time you start sharing; share the new one with your group."
            self.online_note.configure(text=note, foreground=self.MUTED)
        else:
            self.copy_online.pack_forget()
            busy = t.status == "starting"
            self.online_url.configure(
                text=(self.tunnel_note or "Connecting…") if busy else ("Not sharing" if t.status != "error" else "Sharing failed"),
                foreground=self.GOLD if busy else (self.DANGER if t.status == "error" else self.MUTED),
            )
            self.share_btn.configure(text="Share online", style="Primary.TButton", state="disabled" if busy else "normal")
            self.online_note.configure(
                text=t.error
                or "Gives your club a secure https:// link that works from anywhere (mobile data, other homes) through a free "
                "Cloudflare Tunnel. No router or firewall changes, and friends don't need to install anything.",
                foreground=self.DANGER if t.error else self.MUTED,
            )
        self.root.after(1000, self.refresh_tunnel)

    def toggle_sharing(self):
        if self.tunnel.status == "online":
            self.tunnel.stop()
        else:
            self.start_sharing(confirm=True)

    def start_sharing(self, confirm: bool):
        from tkinter import messagebox

        if confirm and find_cloudflared(self.ctl.paths) is None:
            if not messagebox.askyesno(
                APP_NAME,
                "Online sharing uses cloudflared, Cloudflare's official free tunnel program (about 55 MB).\n\n"
                "Download it now from Cloudflare's GitHub releases? It is checked for Cloudflare's digital "
                "signature before it is used.",
            ):
                return

        def work():
            try:
                self.tunnel.start(timeout=90, progress=lambda m: setattr(self, "tunnel_note", m))
            except TunnelError as exc:
                log.warning("Online sharing failed: %s", exc)
            finally:
                self.tunnel_note = ""

        self.tunnel.status = "starting"
        self.tunnel.error = None
        threading.Thread(target=work, name="tunnel-start", daemon=True).start()

    def save_auto_share(self):
        import json

        self.ctl.config.online_sharing_on_start = bool(self.auto_share.get())
        try:
            path = self.ctl.paths.config_path
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            data["online_sharing_on_start"] = self.ctl.config.online_sharing_on_start
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            log.warning("Could not save config: %s", exc)

    # -- UI helpers -----------------------------------------------------
    def url_row(self, parent, label: str, url: str | None, note: str = ""):
        from tkinter import ttk

        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, style="Muted.TLabel", width=22).pack(side="left")
        if url:
            ttk.Label(row, text=url, style="Url.TLabel").pack(side="left")
            ttk.Button(row, text="Copy", style="Small.TButton", command=lambda u=url: self.copy(u)).pack(side="right")
        else:
            ttk.Label(row, text=note, style="Muted.TLabel").pack(side="left")

    def refresh_urls(self):
        for w in self.urls_frame.winfo_children():
            w.destroy()
        port = self.ctl.config.port
        self.url_row(self.urls_frame, "This computer", f"http://localhost:{port}")
        addrs = local_addresses()
        lan = [a for a in addrs if a["kind"] == "lan"]
        ts = [a for a in addrs if a["kind"] == "tailscale"]
        if lan:
            for a in lan:
                self.url_row(self.urls_frame, "Friends on your Wi-Fi/LAN", f"http://{a['address']}:{port}")
        else:
            self.url_row(self.urls_frame, "Friends on your Wi-Fi/LAN", None, "No network connection found")
        if ts:
            for a in ts:
                self.url_row(self.urls_frame, "Friends via Tailscale", f"http://{a['address']}:{port}")
        else:
            self.url_row(self.urls_frame, "Friends via Tailscale", None, "Tailscale not detected (optional)")
        self.root.after(30000, self.refresh_urls)

    def refresh_status(self):
        running = self.ctl.running
        self.status.configure(
            text=f"● Server running on port {self.ctl.config.port}" if running else "● Server stopped",
            foreground=self.ACCENT if running else self.DANGER,
        )
        backups = list_backups(self.ctl.paths)
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(backups[0].stat().st_mtime)) if backups else "never"
        self.info_label.configure(
            text=(
                f"Data folder: {self.ctl.paths.data_dir}\n"
                f"Last backup: {last} · automatic backup every {self.ctl.config.auto_backup_hours} h "
                f"(keeps {self.ctl.config.backups_to_keep})\n"
                "Keep this window open while your group is reading. Closing it stops the server safely.\n"
                f"Version {__version__}. Quran text: Tanzil Project (tanzil.net)."
            )
        )
        self.root.after(5000, self.refresh_status)

    def copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.configure(text=f"Copied {text}")

    # -- actions --------------------------------------------------------
    def open_browser(self):
        webbrowser.open(f"http://localhost:{self.ctl.config.port}")

    def backup(self):
        from tkinter import messagebox

        try:
            path = create_backup(self.ctl.paths, keep=self.ctl.config.backups_to_keep)
            messagebox.showinfo(APP_NAME, f"Backup saved:\n{path}")
        except BackupError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def restore(self):
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            title="Choose a backup to restore",
            initialdir=str(self.ctl.paths.backups_dir),
            filetypes=[("Reading Club backup", "*.zip")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Restore this backup?\n\nThe server restarts and everything after the backup is replaced. "
            "Your current data is saved first as a 'pre-restore' backup.",
        ):
            return
        try:
            self.ctl.stop()
            safety = restore_backup(self.ctl.paths, Path(path))
            messagebox.showinfo(APP_NAME, f"Backup restored.\nPrevious data saved as:\n{safety}")
        except BackupError as exc:
            messagebox.showerror(APP_NAME, f"Restore failed: {exc}")
        finally:
            try:
                self.ctl.start()
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Server failed to restart: {exc}")
            self.refresh_status()

    def firewall(self):
        from tkinter import messagebox

        if add_firewall_rules(self.ctl.config.port):
            messagebox.showinfo(
                APP_NAME,
                "Windows will ask for permission. The rules allow your local network (Private networks only) "
                "and Tailscale devices to reach the reading club. Nothing is opened to the internet.",
            )
        else:
            messagebox.showwarning(APP_NAME, "Could not start the firewall helper. See the README for manual steps.")

    def on_close(self):
        from tkinter import messagebox

        if messagebox.askyesno(APP_NAME, "Stop the server and exit?\n\nFriends will be disconnected until you start it again."):
            self.status.configure(text="Stopping…")
            self.root.update()
            self.tunnel.stop()
            self.ctl.stop()
            self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def message(text: str, error: bool = False, gui: bool = True) -> None:
    print(text, file=sys.stderr if error else sys.stdout)
    if gui:
        try:
            import tkinter as tk
            from tkinter import messagebox

            r = tk.Tk()
            r.withdraw()
            (messagebox.showerror if error else messagebox.showinfo)(APP_NAME, text)
            r.destroy()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="QuranReadingClub", description=APP_NAME)
    parser.add_argument("--headless", action="store_true", help="run without a window (Ctrl+C to stop)")
    parser.add_argument("--data", help="data folder (default: 'data' next to the program)")
    parser.add_argument("--port", type=int, help="override the port from config.json")
    parser.add_argument("--backup", action="store_true", help="write a backup and exit")
    parser.add_argument("--restore", metavar="ZIP", help="restore a backup (server must not be running) and exit")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser on start")
    parser.add_argument("--online", action="store_true", help="with --headless: also share online via Cloudflare Tunnel")
    args = parser.parse_args(argv)

    paths = Paths(Path(args.data).resolve() if args.data else default_data_dir())
    setup_logging(paths)
    gui = not (args.headless or args.backup or args.restore)
    try:
        config = load_config(paths)
    except ValueError as exc:
        message(f"Configuration problem: {exc}\nFile: {paths.config_path}", error=True, gui=gui)
        return 2
    if args.port:
        config.port = args.port

    if args.backup:
        print(create_backup(paths, keep=config.backups_to_keep))
        return 0
    if args.restore:
        if port_in_use(config.port):
            message("Stop the running server before restoring a backup.", error=True, gui=False)
            return 1
        safety = restore_backup(paths, Path(args.restore))
        print(f"Restored. Previous data saved as {safety}")
        return 0

    if port_in_use(config.port):
        if is_our_server(config.port):
            webbrowser.open(f"http://localhost:{config.port}")
            message("The reading club is already running. Opening it in your browser.", gui=gui)
            return 0
        message(
            f"Port {config.port} is used by another program.\nChange \"port\" in {paths.config_path} and try again.",
            error=True,
            gui=gui,
        )
        return 1

    tunnel = TunnelController(config.port, paths, token=config.cloudflare_tunnel_token, fixed_url=config.public_url)

    def sharing_info() -> dict:
        return {
            "status": tunnel.status,
            "public_url": tunnel.public_url(),
            "named": tunnel.named,
            "lan_urls": [f"http://{a['address']}:{config.port}" for a in local_addresses()],
        }

    ctl = ServerController(paths, config, app_kwargs={"sharing_provider": sharing_info})
    try:
        ctl.start()
    except Exception as exc:  # noqa: BLE001
        log.exception("Start failed")
        message(f"The server could not start:\n{exc}\n\nSee {paths.logs_dir / 'server.log'}", error=True, gui=gui)
        return 1
    log.info("%s %s started; data in %s", APP_NAME, __version__, paths.data_dir)
    if config.open_browser_on_start and not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{config.port}")).start()

    if not gui:
        print(f"{APP_NAME} running at http://localhost:{config.port}")
        for a in local_addresses():
            print(f"  {a['kind']:>9}: http://{a['address']}:{config.port}")
        if args.online or config.online_sharing_on_start:
            try:
                print(f"  online: {tunnel.start(timeout=120, progress=print)}")
            except TunnelError as exc:
                print(f"  online sharing failed: {exc}")
        print("Press Ctrl+C to stop.")
        try:
            while ctl.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        tunnel.stop()
        ctl.stop()
        return 0

    LauncherWindow(ctl, tunnel).run()
    tunnel.stop()
    if ctl.running:
        ctl.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Quran Reading Club

A private, self-hosted Quran reading club for a small group of friends.
Your Windows laptop is the server. Friends read in their browser on your Wi-Fi, or **from anywhere** through the built-in **Share online** button (a free, HTTPS Cloudflare Tunnel; no router setup) or Tailscale.
There is no cloud database, no paid API and no account required for hosting; all data stays on your laptop.

* **The Quran, built in.** The verified Tanzil Uthmani text (v1.1) is bundled verbatim, with the standard 604-page Madani mushaf pagination, surah headers and basmala.
* **Two reading modes.**
  * **Flow:** reflowable, scalable text like an e-book, with an end-of-page marker after every standard page and juz/hizb (¼ ½ ¾) markers in the side margin.
  * **Mushaf:** one standard page at a time.
  * Both have night/paper themes, text size, fullscreen, page/surah/juz navigation and a remembered bookmark.
* **Daily task.** By default at least **2 pages** and **20 minutes of active reading**. Both are configurable.
* **Honest activity tracking.** Paused when hidden, unfocused or idle. Checked against wall-clock time on the server, one live session per person. Pages count once per khatma after a minimum time on the page.
* **Streaks.**
  * Individual and group streaks (the group streak grows only when *everyone* completes the day), with longest streaks and a history calendar.
  * Days follow the group's timezone and reset time, and are finalised safely after midnight and across server restarts.
* **Administration.**
  * Invitation codes, member management, configurable group size, and assigned reading by page range, surah or juz.
  * Everyone's history, and a confirmed streak reset.
* **Windows launcher.** One `QuranReadingClub.exe`. It starts the server, shows the LAN and Tailscale URLs, sets up the firewall, backs up and restores, and stops safely.
* **Share online.** One click gives a secure `https://` link for friends anywhere.
  Tunnelled visitors are never treated as the host, and passwords and invite codes are throttled.

## Documents

| | |
|---|---|
| [docs/HOST-GUIDE.md](docs/HOST-GUIDE.md) | installation, firewall, Tailscale, configuration, backup and restore, troubleshooting |
| [docs/FRIENDS-GUIDE.md](docs/FRIENDS-GUIDE.md) | how friends connect and read |
| [docs/HOW-TRACKING-WORKS.md](docs/HOW-TRACKING-WORKS.md) | how time, pages and streaks are tracked, and their limits |

## Quick start (host)

1. Unzip `QuranReadingClub-win64.zip` to a writable folder and run `QuranReadingClub.exe`.
2. In the browser that opens, click **Create a new group (host)**.
3. Click **Allow through Windows Firewall** in the host window.
4. For friends outside your home, click **Share online**.
5. Share the address shown in the host window and the invitation code from **Admin** with your friends.

## Architecture

```
QuranReadingClub.exe  (PyInstaller, one folder, no Python/Node needed)
 ├─ Tkinter host window: status, URLs, backup/restore, firewall, safe shutdown
 └─ Uvicorn + FastAPI (one process, one port, default 8765, bound to 0.0.0.0)
     ├─ /api/...   JSON API (bearer tokens, scrypt password hashes)
     ├─ /...       React + TypeScript single-page app (built with Vite)
     ├─ SQLite     data/readingclub.db (WAL, synchronous=FULL, BEGIN IMMEDIATE)
     └─ Quran      app/quran_data (Tanzil text + metadata, loaded and validated at start-up)
```

* **Why one process:** friends only need a browser, and the host runs a single program. The SPA is served by the same server, so there is no CORS and no second port.
* **Why SQLite with immediate transactions:** fully local, a single file that is easy to back up, and safe concurrent heartbeats from several devices.
* **Network guard:** requests from non-private addresses are refused. Only localhost, LAN and the Tailscale range are allowed.

Source layout:

```
backend/app/        FastAPI app: models, tracking, streak engine, API, launcher, backups
backend/tests/      pytest suite (81 tests)
frontend/src/       React app: dashboard, reader (flow + mushaf), admin; tracker with vitest tests
packaging/          PyInstaller spec and icon generator
build.ps1           one-command build -> dist\QuranReadingClub\ and a zip
```

## Building from source

Requirements: Windows, Python 3.11+ and Node.js 20+.

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

This installs dependencies, builds the web app, runs all tests, and produces `dist\QuranReadingClub\QuranReadingClub.exe` and `dist\QuranReadingClub-win64.zip`.

Development:

```powershell
.venv\Scripts\python backend\run_club.py --headless   # API + built UI on :8765
cd frontend; npm run dev                              # hot-reloading UI on :5173 (proxies /api)
cd backend; ..\.venv\Scripts\python -m pytest -q      # backend tests
cd frontend; npx vitest run                           # tracker tests
```

## Licence

The application source code is released under the [MIT License](LICENSE).
Third-party content keeps its own licence; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Quran text licence

The Quran text is the **Tanzil Quran Text (Uthmani, Version 1.1)**, Copyright (C) 2007-2026 Tanzil Project.
It is licensed under Creative Commons Attribution 3.0 and is used verbatim; changing it is not allowed.
The file `backend/app/quran_data/quran-uthmani.txt` keeps the original copyright block. Updates: <https://tanzil.net/updates/>.

The app shows this attribution with a link to tanzil.net on every page.
It only presents the text: the basmala at the start of each surah is displayed as a heading line, as tanzil.net does, and verse numbers are drawn as ornaments.

The Madani page, juz and hizb boundaries come from Tanzil's `quran-data.xml` metadata.
Flow mode does not reproduce the printed line breaks of a physical mushaf. Mushaf mode keeps the standard page boundaries with reflowed lines.

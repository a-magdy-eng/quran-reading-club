# Third-party notices

## Quran text and metadata: Tanzil Project

`backend/app/quran_data/quran-uthmani.txt`
: Tanzil Quran Text (Uthmani, Version 1.1). Copyright (C) 2007-2026 Tanzil Project.
  License: Creative Commons Attribution 3.0.

`backend/app/quran_data/quran-data.xml`
: Tanzil Quran metadata: suras, juz, hizb quarters, pages and sajdas. (C) 2008-2009 Tanzil.info. License: CC BY.

Terms of use, from the copyright block in the text file:

* Verbatim copies may be copied and distributed, but **changing the text is not allowed**.
* The text can be used in any website or application, provided its source (Tanzil Project) is clearly indicated and a link to <https://tanzil.net> is given so users can follow changes.
* The copyright notice must be included in all verbatim copies and reproduced appropriately in derived files.

This application ships both files unmodified and keeps their copyright notice. It shows "Quran text: Tanzil Project" with a link to tanzil.net on every page.
For display, the leading basmala of each surah is shown as a heading line, and verse numbers are drawn as ornaments; the text itself is never altered.
Check for updates at <https://tanzil.net/updates/>.

## Fonts (bundled in the web interface)

| Font | Author | Licence |
|---|---|---|
| Amiri Quran | Khaled Hosny | SIL Open Font License 1.1 |
| Inter | Rasmus Andersson | SIL Open Font License 1.1 |
| Fraunces | Undercase Type | SIL Open Font License 1.1 |

All three are packaged through Fontsource.

## Software used at runtime

| Component | Licence |
|---|---|
| Python | PSF License |
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic | MIT |
| SQLAlchemy | MIT |
| SQLite | Public domain |
| tzdata (IANA time zone database) | Apache-2.0 (data: public domain) |
| React, React DOM | MIT |
| React Router | MIT |
| Tk/Tcl | Tcl/Tk License (BSD-style) |

The Windows executable is built with PyInstaller (GPL-2.0 with the bootloader exception, which permits distributing the resulting program under any licence).

## cloudflared (not distributed with this project)

Online sharing uses **cloudflared** by Cloudflare, Inc. (Apache-2.0).
It is not included in this repository or in release builds. The app downloads it from Cloudflare's official GitHub releases when the host first clicks "Share online", and uses it only if its Authenticode signature is valid and issued to Cloudflare.
Use of Cloudflare Tunnel is subject to Cloudflare's terms of service.

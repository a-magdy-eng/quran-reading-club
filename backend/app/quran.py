"""The Quran text (Tanzil Project, Uthmani v1.1) and mushaf metadata.

The bundled files in quran_data/ are verbatim copies from tanzil.net and must
not be edited (see the copyright block at the end of quran-uthmani.txt). This
module only *reads* them; the leading basmala of each sura's first verse is
presented as a separate heading line, exactly as tanzil.net itself displays it.

Pages follow the standard 604-page Madani mushaf layout from Tanzil metadata.
"""
from __future__ import annotations

import bisect
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "quran_data"
TEXT_FILE = "quran-uthmani.txt"
META_FILE = "quran-data.xml"

TOTAL_PAGES = 604
TOTAL_VERSES = 6236
TOTAL_SURAS = 114

ATTRIBUTION = {
    "source": "Tanzil Project",
    "url": "https://tanzil.net",
    "text": "Tanzil Quran Text (Uthmani, Version 1.1)",
    "license": "Creative Commons Attribution 3.0",
    "notice": "Copyright (C) 2007-2026 Tanzil Project. Verbatim copy; changing the text is not allowed. "
    "Check updates at http://tanzil.net/updates/",
}


@dataclass(frozen=True)
class Verse:
    index: int  # 0-based global index
    sura: int
    aya: int
    text: str


@dataclass(frozen=True)
class Sura:
    index: int
    ayas: int
    start: int  # global index of first verse
    name: str
    tname: str
    ename: str
    type: str
    start_page: int


class QuranData:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.verses: list[Verse] = []
        self._load_text(data_dir / TEXT_FILE)
        self._load_meta(data_dir / META_FILE)
        self.basmala = self.verses[0].text  # 1:1
        self._validate()

    def _load_text(self, path: Path) -> None:
        with path.open(encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                sura, aya, text = line.split("|", 2)
                self.verses.append(Verse(len(self.verses), int(sura), int(aya), text))

    def _load_meta(self, path: Path) -> None:
        root = ET.parse(path).getroot()
        self._verse_idx = {(v.sura, v.aya): v.index for v in self.verses}

        def gidx(el) -> int:
            return self._verse_idx[(int(el.get("sura")), int(el.get("aya")))]

        self.page_starts = [gidx(el) for el in root.find("pages")]
        self.juz_starts = [gidx(el) for el in root.find("juzs")]
        self.quarter_starts = [gidx(el) for el in root.find("hizbs")]
        self.sajdas = {gidx(el): el.get("type") for el in root.find("sajdas")}
        suras = []
        for el in root.find("suras"):
            start = int(el.get("start"))
            suras.append(
                Sura(
                    index=int(el.get("index")),
                    ayas=int(el.get("ayas")),
                    start=start,
                    name=el.get("name"),
                    tname=el.get("tname"),
                    ename=el.get("ename"),
                    type=el.get("type"),
                    start_page=self.page_of_index(start),
                )
            )
        self.suras = suras

    def _validate(self) -> None:
        if len(self.verses) != TOTAL_VERSES:
            raise RuntimeError(f"Quran text has {len(self.verses)} verses, expected {TOTAL_VERSES}")
        if len(self.page_starts) != TOTAL_PAGES or len(self.suras) != TOTAL_SURAS or len(self.juz_starts) != 30:
            raise RuntimeError("Quran metadata is incomplete")
        if self.page_starts != sorted(self.page_starts):
            raise RuntimeError("Quran page metadata is not ordered")

    # --- lookups -----------------------------------------------------------
    def page_of_index(self, idx: int) -> int:
        return bisect.bisect_right(self.page_starts, idx)

    def juz_of_index(self, idx: int) -> int:
        return bisect.bisect_right(self.juz_starts, idx)

    def quarter_of_index(self, idx: int) -> int:
        return bisect.bisect_right(self.quarter_starts, idx)

    def page_range(self, page: int) -> range:
        if not 1 <= page <= TOTAL_PAGES:
            raise ValueError("page out of range")
        start = self.page_starts[page - 1]
        end = self.page_starts[page] if page < TOTAL_PAGES else TOTAL_VERSES
        return range(start, end)

    def juz_start_page(self, juz: int) -> int:
        return self.page_of_index(self.juz_starts[juz - 1])

    def page_summary(self, page: int) -> dict:
        r = self.page_range(page)
        first = self.verses[r.start]
        sura = self.suras[first.sura - 1]
        return {
            "page": page,
            "juz": self.juz_of_index(r.start),
            "sura": sura.index,
            "sura_name": sura.name,
            "sura_tname": sura.tname,
        }

    def page(self, page: int) -> dict:
        r = self.page_range(page)
        quarter_set = set(self.quarter_starts)
        quarter_no = {idx: q + 1 for q, idx in enumerate(self.quarter_starts)}
        juz_no = {idx: j + 1 for j, idx in enumerate(self.juz_starts)}
        verses = []
        for i in r:
            v = self.verses[i]
            text = v.text
            basmala = False
            if v.aya == 1 and v.sura not in (1, 9) and text.startswith(self.basmala + " "):
                text = text[len(self.basmala) + 1 :]
                basmala = True
            verses.append(
                {
                    "sura": v.sura,
                    "aya": v.aya,
                    "text": text,
                    "sura_start": v.aya == 1,
                    "basmala": basmala,
                    "sajda": self.sajdas.get(i),
                    "quarter_start": i in quarter_set and i != 0,
                    # 1..240 when a hizb quarter (rub') starts at this verse; hizb = ceil(q / 4)
                    "quarter": quarter_no.get(i),
                    # 1..30 when a juz starts at this verse
                    "juz_start": juz_no.get(i),
                }
            )
        suras_on_page = sorted({v.sura for v in (self.verses[i] for i in r)})
        return {
            **self.page_summary(page),
            "total_pages": TOTAL_PAGES,
            "juz_end": self.juz_of_index(r.stop - 1),
            "basmala_text": self.basmala,
            "hizb_quarter": self.quarter_of_index(r.start),
            "suras": [
                {
                    "index": s,
                    "name": self.suras[s - 1].name,
                    "tname": self.suras[s - 1].tname,
                    "ename": self.suras[s - 1].ename,
                    "type": self.suras[s - 1].type,
                    "ayas": self.suras[s - 1].ayas,
                }
                for s in suras_on_page
            ],
            "verses": verses,
        }

    def meta(self) -> dict:
        return {
            "total_pages": TOTAL_PAGES,
            "total_verses": TOTAL_VERSES,
            "suras": [
                {
                    "index": s.index,
                    "name": s.name,
                    "tname": s.tname,
                    "ename": s.ename,
                    "type": s.type,
                    "ayas": s.ayas,
                    "start_page": s.start_page,
                }
                for s in self.suras
            ],
            "juzs": [{"index": j, "start_page": self.juz_start_page(j)} for j in range(1, 31)],
            "page_index": [
                {"page": p, "sura": self.verses[self.page_starts[p - 1]].sura, "juz": self.juz_of_index(self.page_starts[p - 1])}
                for p in range(1, TOTAL_PAGES + 1)
            ],
            "attribution": ATTRIBUTION,
        }

    def describe_range(self, start_page: int, end_page: int) -> str:
        a = self.page_summary(start_page)
        b = self.page_summary(end_page)
        if a["sura"] == b["sura"]:
            return f"{a['sura_tname']}"
        return f"{a['sura_tname']} – {b['sura_tname']}"


@lru_cache(maxsize=1)
def get_quran() -> QuranData:
    return QuranData()

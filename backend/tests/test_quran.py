"""The bundled Quran text and mushaf pagination."""
from app.quran import DATA_DIR, TEXT_FILE, TOTAL_PAGES, get_quran


def test_text_file_is_verbatim_tanzil_with_copyright():
    raw = (DATA_DIR / TEXT_FILE).read_text(encoding="utf-8")
    assert "Tanzil Quran Text (Uthmani, Version 1.1)" in raw
    assert "PLEASE DO NOT REMOVE OR CHANGE THIS COPYRIGHT BLOCK" in raw
    q = get_quran()
    assert len(q.verses) == 6236
    assert len(q.suras) == 114


def test_every_verse_is_on_exactly_one_page():
    q = get_quran()
    seen = []
    for p in range(1, TOTAL_PAGES + 1):
        seen.extend(q.page_range(p))
    assert seen == list(range(6236))


def test_known_page_layout():
    q = get_quran()
    p1 = q.page(1)
    assert p1["sura_tname"] == "Al-Faatiha" and len(p1["verses"]) == 7 and p1["juz"] == 1
    p2 = q.page(2)
    assert p2["verses"][0]["sura"] == 2 and p2["verses"][0]["basmala"] is True
    # The basmala is shown as a heading, never duplicated inside the verse.
    assert not p2["verses"][0]["text"].startswith(q.basmala)
    assert q.page(187)["verses"][0]["basmala"] is False  # At-Tawba has no basmala
    assert q.juz_start_page(30) == 582
    last = q.page(604)
    assert [s["index"] for s in last["suras"]] == [112, 113, 114]


def test_hizb_and_juz_markers():
    q = get_quran()
    quarters = [v["quarter"] for p in range(1, TOTAL_PAGES + 1) for v in q.page(p)["verses"] if v["quarter"]]
    assert quarters == list(range(1, 241))  # every rub' marked exactly once, in order
    juzs = [(p, v["juz_start"]) for p in range(1, TOTAL_PAGES + 1) for v in q.page(p)["verses"] if v["juz_start"]]
    assert [j for _, j in juzs] == list(range(1, 31))
    assert dict((j, p) for p, j in juzs)[2] == 22  # juz 2 starts on page 22 (2:142)
    # A juz always starts on a hizb boundary: quarter 4k+1 with k = 2*(juz-1).
    for p in range(1, TOTAL_PAGES + 1):
        for v in q.page(p)["verses"]:
            if v["juz_start"]:
                assert v["quarter"] == 8 * (v["juz_start"] - 1) + 1


def test_quran_api(env):
    admin = env.setup_group()
    meta = admin.ok("get", "/api/quran/meta")
    assert meta["total_pages"] == 604 and len(meta["suras"]) == 114 and len(meta["juzs"]) == 30
    assert meta["attribution"]["url"] == "https://tanzil.net"
    page = admin.ok("get", "/api/quran/page/50")
    assert page["suras"][0]["tname"] == "Aal-i-Imraan"
    assert admin.get("/api/quran/page/0").status_code == 404
    assert admin.get("/api/quran/page/605").status_code == 404

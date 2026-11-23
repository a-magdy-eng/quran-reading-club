// Continuous, reflowable reading view (like an e-book).
//
// A window of mushaf pages is rendered as one text flow and grows in both
// directions as the reader scrolls. The "current page" (used for tracking) is
// the page being read at the reading line, 30% down the viewport: the first
// page whose end marker is still below that line.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Spinner } from "../components";
import { loadPage } from "../quran";
import type { QuranPage } from "../types";
import { QuranText } from "./QuranText";

const TOTAL = 604;
const CHUNK = 3;
const EDGE_PX = 1400;

export interface JumpRequest {
  page: number;
  nonce: number;
}

function pagesBetween(lo: number, hi: number) {
  const out: number[] = [];
  for (let p = Math.max(1, lo); p <= Math.min(TOTAL, hi); p++) out.push(p);
  return out;
}

export function FlowView({ jump, onPage }: { jump: JumpRequest; onPage: (p: number) => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<QuranPage[]>([]);
  const pagesRef = useRef<QuranPage[]>([]);
  pagesRef.current = pages;
  const pendingScroll = useRef<number | null>(null);
  const anchor = useRef<{ page: number; top: number } | null>(null);
  const busy = useRef(false);
  const current = useRef<number>(jump.page);
  const [error, setError] = useState<string | null>(null);

  const startEl = (p: number) => scrollRef.current?.querySelector<HTMLElement>(`[data-start="${p}"]`) ?? null;

  const scrollToPage = useCallback((p: number) => {
    const root = scrollRef.current;
    const el = startEl(p);
    if (!root || !el) return;
    if (p === 1) {
      root.scrollTop = 0;
    } else {
      const delta = el.getBoundingClientRect().top - root.getBoundingClientRect().top;
      root.scrollTop += delta - 24;
    }
    current.current = p;
    onPage(p);
  }, [onPage]);

  // Jump requests (initial page, page input, surah/juz pickers, next/prev).
  useEffect(() => {
    const p = Math.max(1, Math.min(TOTAL, jump.page));
    const have = pagesRef.current;
    if (have.length && have[0].page <= p && have[have.length - 1].page >= p) {
      scrollToPage(p);
      return;
    }
    let cancelled = false;
    busy.current = true;
    Promise.all(pagesBetween(p - 1, p + CHUNK).map(loadPage))
      .then((list) => {
        if (cancelled) return;
        pendingScroll.current = p;
        setPages(list);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => (busy.current = false));
    return () => {
      cancelled = true;
    };
  }, [jump, scrollToPage]);

  // After pages change: either honour a pending jump or keep the text under
  // the reader's eyes still while pages are prepended above.
  useLayoutEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    if (pendingScroll.current != null) {
      const p = pendingScroll.current;
      pendingScroll.current = null;
      scrollToPage(p);
    } else if (anchor.current) {
      const el = startEl(anchor.current.page);
      if (el) root.scrollTop += el.getBoundingClientRect().top - anchor.current.top;
      anchor.current = null;
    }
    check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages]);

  const extend = useCallback(async (dir: "up" | "down") => {
    const have = pagesRef.current;
    if (busy.current || !have.length) return;
    const lo = have[0].page;
    const hi = have[have.length - 1].page;
    if (dir === "up" && lo <= 1) return;
    if (dir === "down" && hi >= TOTAL) return;
    busy.current = true;
    try {
      const nums = dir === "up" ? pagesBetween(lo - CHUNK, lo - 1) : pagesBetween(hi + 1, hi + CHUNK);
      const list = await Promise.all(nums.map(loadPage));
      if (dir === "up") {
        const el = startEl(lo);
        if (el) anchor.current = { page: lo, top: el.getBoundingClientRect().top };
        setPages((cur) => [...list, ...cur]);
      } else {
        setPages((cur) => [...cur, ...list]);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      busy.current = false;
    }
  }, []);

  // Work out the current page and load more text near either edge.
  const check = useCallback(() => {
    const root = scrollRef.current;
    if (!root || !pagesRef.current.length) return;
    const box = root.getBoundingClientRect();
    const line = box.top + root.clientHeight * 0.3;
    const ends = root.querySelectorAll<HTMLElement>("[data-end]");
    let page = pagesRef.current[pagesRef.current.length - 1].page;
    for (const el of ends) {
      if (el.getBoundingClientRect().top > line) {
        page = Number(el.dataset.end);
        break;
      }
    }
    if (root.scrollTop + root.clientHeight >= root.scrollHeight - 4 && pagesRef.current[pagesRef.current.length - 1].page === TOTAL) page = TOTAL;
    if (page !== current.current) {
      current.current = page;
      onPage(page);
    }
    const have = pagesRef.current;
    const nearTop = root.scrollTop < EDGE_PX && have[0].page > 1;
    const nearBottom = root.scrollHeight - root.scrollTop - root.clientHeight < EDGE_PX && have[have.length - 1].page < TOTAL;
    if (nearBottom) extend("down");
    else if (nearTop) extend("up");
  }, [extend, onPage]);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(check);
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(onScroll); // font size / window changes reflow the text
    ro.observe(root);
    return () => {
      root.removeEventListener("scroll", onScroll);
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [check]);

  return (
    <div className="flow-scroll" ref={scrollRef}>
      {error && <p className="form-error">{error}</p>}
      {pages.length ? (
        <article className="flow-text" dir="rtl" lang="ar">
          {pages[0].page > 1 && <div className="flow-edge muted small">…</div>}
          <QuranText pages={pages} />
          {pages[pages.length - 1].page === TOTAL ? (
            <div className="flow-edge small muted" dir="ltr">
              End of the mushaf
            </div>
          ) : (
            <div className="flow-edge muted small">…</div>
          )}
        </article>
      ) : (
        <Spinner />
      )}
    </div>
  );
}

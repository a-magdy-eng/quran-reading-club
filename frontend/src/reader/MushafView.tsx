// Page-at-a-time view: one standard mushaf page per screen, with page number.
import { useEffect, useRef, useState } from "react";
import { ErrorBox, Spinner } from "../components";
import { arabicNumber } from "../format";
import { loadPage, prefetch } from "../quran";
import type { QuranPage } from "../types";
import { QuranText } from "./QuranText";

export function MushafView({ page, onNext, onPrev }: { page: number; onNext: () => void; onPrev: () => void }) {
  const [data, setData] = useState<QuranPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const touch = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    loadPage(page)
      .then((p) => {
        if (cancelled) return;
        setData(p);
        scrollRef.current?.scrollTo({ top: 0 });
      })
      .catch((e) => !cancelled && setError((e as Error).message));
    prefetch(page + 1, page - 1, page + 2);
    return () => {
      cancelled = true;
    };
  }, [page]);

  // Swipe right -> next page (the mushaf opens right-to-left).
  const onTouchStart = (e: React.TouchEvent) => (touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY });
  const onTouchEnd = (e: React.TouchEvent) => {
    if (!touch.current) return;
    const dx = e.changedTouches[0].clientX - touch.current.x;
    const dy = e.changedTouches[0].clientY - touch.current.y;
    touch.current = null;
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.5) (dx > 0 ? onNext : onPrev)();
  };

  return (
    <div className="mushaf-scroll" ref={scrollRef} onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      {error ? (
        <ErrorBox error={error} />
      ) : data && data.page === page ? (
        <article className="mushaf-page" dir="rtl" lang="ar" key={page}>
          <QuranText pages={[data]} endMarkers={false} />
          <div className="mushaf-foot">
            <span className="page-num">{arabicNumber(page)}</span>
          </div>
        </article>
      ) : (
        <Spinner />
      )}
    </div>
  );
}

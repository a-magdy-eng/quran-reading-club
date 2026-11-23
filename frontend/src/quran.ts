import { api } from "./api";
import type { QuranMeta, QuranPage } from "./types";

let metaPromise: Promise<QuranMeta> | null = null;
const pageCache = new Map<number, Promise<QuranPage>>();

export function loadMeta(): Promise<QuranMeta> {
  if (!metaPromise) {
    metaPromise = api<QuranMeta>("/api/quran/meta").catch((e) => {
      metaPromise = null;
      throw e;
    });
  }
  return metaPromise;
}

export function loadPage(page: number): Promise<QuranPage> {
  let p = pageCache.get(page);
  if (!p) {
    p = api<QuranPage>(`/api/quran/page/${page}`).catch((e) => {
      pageCache.delete(page);
      throw e;
    });
    pageCache.set(page, p);
    if (pageCache.size > 40) {
      const first = pageCache.keys().next().value;
      if (first !== undefined && first !== page) pageCache.delete(first);
    }
  }
  return p;
}

export function prefetch(...pages: number[]) {
  for (const p of pages) if (p >= 1 && p <= 604) loadPage(p).catch(() => undefined);
}

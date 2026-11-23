// Connects the ActivityTracker to the browser and to the server's session API.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, getToken } from "../api";
import type { DayProgress, ReadingState } from "../types";
import { ActivityTracker, type PauseReason } from "./ActivityTracker";

const CLIENT_KEY = "qrc.client";

function clientId(): string {
  // One id per browser tab (sessionStorage), so a reload keeps the same id.
  try {
    let id = sessionStorage.getItem(CLIENT_KEY);
    if (!id) {
      id = (crypto.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36)).replace(/-/g, "");
      sessionStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
}

export type SessionStatus = "starting" | "active" | "superseded" | "error" | "ended";

export interface LiveReading {
  status: SessionStatus;
  pauseReason: PauseReason;
  today: DayProgress | null;
  /** today's active seconds including not-yet-sent local time */
  liveSeconds: number;
  /** active seconds on the current page (server + local) */
  pageSeconds: number;
  pageCounted: boolean;
  countedPages: Set<number>;
  khatma: number;
  minPageSeconds: number;
  inactivitySeconds: number;
  error: string | null;
  lastCounted: number[];
  idleInMs: number;
}

export function useReadingSession(initialState: ReadingState | null, page: number) {
  const trackerRef = useRef<ActivityTracker | null>(null);
  const sessionRef = useRef<number | null>(null);
  const seqRef = useRef(0);
  const inflight = useRef(false);
  const pageRef = useRef(page);
  const serverPageDwell = useRef<Record<number, number>>({});
  const [live, setLive] = useState<LiveReading>(() => ({
    status: "starting",
    pauseReason: null,
    today: initialState?.today ?? null,
    liveSeconds: initialState?.today.active_seconds ?? 0,
    pageSeconds: 0,
    pageCounted: false,
    countedPages: new Set(initialState?.counted_pages ?? []),
    khatma: initialState?.khatma ?? 1,
    minPageSeconds: initialState?.tracking.min_page_seconds ?? 20,
    inactivitySeconds: initialState?.tracking.inactivity_timeout_seconds ?? 60,
    error: null,
    lastCounted: [],
    idleInMs: 60_000,
  }));
  const liveRef = useRef(live);
  liveRef.current = live;

  const heartbeatSeconds = initialState?.tracking.heartbeat_seconds ?? 15;

  const start = useCallback(async () => {
    if (!initialState) return;
    setLive((l) => ({ ...l, status: "starting", error: null }));
    try {
      const res = await api("/api/reading/sessions", { body: { client_id: clientId(), page: pageRef.current } });
      sessionRef.current = res.session.id;
      seqRef.current = 0;
      trackerRef.current?.drain(); // anything before the session started is discarded
      trackerRef.current?.resume();
      const st: ReadingState = res.state;
      serverPageDwell.current[st.current_page] = st.current_page_dwell;
      setLive((l) => ({
        ...l,
        status: "active",
        today: st.today,
        countedPages: new Set(st.counted_pages),
        khatma: st.khatma,
        minPageSeconds: st.tracking.min_page_seconds,
        inactivitySeconds: st.tracking.inactivity_timeout_seconds,
      }));
      trackerRef.current?.setInactivityMs(st.tracking.inactivity_timeout_seconds * 1000);
    } catch (e) {
      setLive((l) => ({ ...l, status: "error", error: (e as Error).message }));
    }
  }, [initialState]);

  const send = useCallback(
    async (opts: { final?: boolean } = {}) => {
      const tracker = trackerRef.current;
      const sid = sessionRef.current;
      if (!tracker || sid == null) return;
      if (inflight.current && !opts.final) return;
      const drained = tracker.drain();
      const body = { seq: ++seqRef.current, page: tracker.currentPage, active_ms: drained.activeMs, page_ms: drained.pageMs };
      if (opts.final) {
        sessionRef.current = null;
        // keepalive lets the request finish while the page unloads.
        fetch(`/api/reading/sessions/${sid}/end`, {
          method: "POST",
          keepalive: true,
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken() ?? ""}` },
          body: JSON.stringify(body),
        }).catch(() => undefined);
        return;
      }
      inflight.current = true;
      try {
        const res = await api(`/api/reading/sessions/${sid}/heartbeat`, { body });
        serverPageDwell.current[res.session.end_page] = res.current_page_dwell;
        setLive((l) => {
          const counted = new Set(l.countedPages);
          for (const p of res.newly_counted as number[]) counted.add(p);
          if (res.current_page_counted) counted.add(res.session.end_page);
          return {
            ...l,
            status: "active",
            today: res.today,
            countedPages: counted,
            lastCounted: res.newly_counted.length ? res.newly_counted : l.lastCounted,
            error: null,
          };
        });
      } catch (e) {
        const err = e as ApiError;
        if (err.status === 409 && err.code === "session_superseded") {
          sessionRef.current = null;
          tracker.pause();
          setLive((l) => ({ ...l, status: "superseded" }));
        } else if (err.status === 409 || err.status === 404) {
          // Timed out / restarted: quietly open a fresh session.
          sessionRef.current = null;
          await start();
        } else if (err.status === 0) {
          tracker.restore(drained);
          seqRef.current -= 1;
          setLive((l) => ({ ...l, error: err.message }));
        } else {
          setLive((l) => ({ ...l, error: err.message }));
        }
      } finally {
        inflight.current = false;
      }
    },
    [start],
  );

  // Create the tracker, start the session and wire DOM events (once).
  useEffect(() => {
    if (!initialState) return;
    const tracker = new ActivityTracker(pageRef.current, initialState.tracking.inactivity_timeout_seconds * 1000);
    trackerRef.current = tracker;
    tracker.setVisible(document.visibilityState === "visible");
    tracker.setFocused(document.hasFocus());
    serverPageDwell.current[initialState.current_page] = initialState.current_page_dwell;
    start();

    let lastMove = 0;
    const onInteract = () => tracker.interaction();
    const onMove = () => {
      const t = Date.now();
      if (t - lastMove > 1000) {
        lastMove = t;
        tracker.interaction();
      }
    };
    const onVisibility = () => {
      const visible = document.visibilityState === "visible";
      tracker.setVisible(visible);
      if (!visible) send(); // flush immediately so hidden time is never attributed
      else if (sessionRef.current == null && liveRef.current.status !== "superseded") start();
      else send();
    };
    const onBlur = () => {
      tracker.setFocused(false);
      send();
    };
    const onFocus = () => tracker.setFocused(true);
    const onPageHide = () => send({ final: true });

    window.addEventListener("keydown", onInteract);
    window.addEventListener("pointerdown", onInteract);
    window.addEventListener("wheel", onInteract, { passive: true });
    window.addEventListener("touchstart", onInteract, { passive: true });
    window.addEventListener("scroll", onInteract, { passive: true, capture: true });
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibility);

    const ui = window.setInterval(() => {
      tracker.tick();
      const l = liveRef.current;
      const p = tracker.currentPage;
      const pageSeconds = (serverPageDwell.current[p] ?? 0) + tracker.pendingForPage(p) / 1000;
      setLive({
        ...l,
        pauseReason: l.status === "active" ? tracker.pauseReason : l.pauseReason,
        liveSeconds: (l.today?.active_seconds ?? 0) + tracker.pendingMs / 1000,
        pageSeconds,
        pageCounted: l.countedPages.has(p),
        idleInMs: tracker.msUntilIdle,
      });
    }, 1000);
    const hb = window.setInterval(() => send(), heartbeatSeconds * 1000);

    return () => {
      window.clearInterval(ui);
      window.clearInterval(hb);
      window.removeEventListener("keydown", onInteract);
      window.removeEventListener("pointerdown", onInteract);
      window.removeEventListener("wheel", onInteract);
      window.removeEventListener("touchstart", onInteract);
      window.removeEventListener("scroll", onInteract, { capture: true } as EventListenerOptions);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibility);
      send({ final: true });
      trackerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialState]);

  // Page turns.
  useEffect(() => {
    pageRef.current = page;
    const tracker = trackerRef.current;
    if (tracker && tracker.currentPage !== page) tracker.setPage(page);
  }, [page]);

  const resumeHere = useCallback(() => start(), [start]);
  const pause = useCallback(() => {
    trackerRef.current?.pause();
    send();
  }, [send]);
  const resume = useCallback(() => trackerRef.current?.resume(), []);
  const nudge = useCallback(() => trackerRef.current?.interaction(), []);

  return { live, resumeHere, pause, resume, nudge };
}

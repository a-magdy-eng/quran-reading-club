import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { get } from "../api";
import { Bar, ErrorBox, Icon, Spinner, useToast } from "../components";
import { clock, plural } from "../format";
import { loadMeta, loadPage } from "../quran";
import { FlowView, type JumpRequest } from "../reader/FlowView";
import { MushafView } from "../reader/MushafView";
import { useReadingSession } from "../tracker/useReadingSession";
import type { QuranMeta, ReadingState } from "../types";

const TOTAL = 604;
const FONT_KEY = "qrc.fontSize";
const THEME_KEY = "qrc.readerTheme";
const MODE_KEY = "qrc.readerMode";

type Mode = "flow" | "mushaf";

function readPref<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function writePref(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

const PAUSE_TEXT: Record<string, string> = {
  hidden: "Paused: reader not visible",
  blurred: "Paused: window not focused",
  idle: "Paused: no activity",
  manual: "Paused",
};

function ReaderInner({ state, meta, startPage }: { state: ReadingState; meta: QuranMeta; startPage: number }) {
  const nav = useNavigate();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>(() => readPref<Mode>(MODE_KEY, "flow"));
  const [pageNo, setPageNo] = useState(startPage);
  const [jump, setJump] = useState<JumpRequest>({ page: startPage, nonce: 0 });
  const [fontSize, setFontSize] = useState<number>(() => readPref(FONT_KEY, window.innerWidth < 640 ? 24 : 30));
  const [theme, setTheme] = useState<"night" | "paper">(() => readPref(THEME_KEY, "night"));
  const [fullscreen, setFullscreen] = useState(false);
  const [jumpText, setJumpText] = useState(String(startPage));
  const [suraName, setSuraName] = useState<{ name: string; tname: string; juz: number } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const { live, resumeHere, pause, resume, nudge } = useReadingSession(state, pageNo);
  const wasComplete = useRef(state.today.completed);

  useEffect(() => writePref(FONT_KEY, fontSize), [fontSize]);
  useEffect(() => writePref(THEME_KEY, theme), [theme]);
  useEffect(() => writePref(MODE_KEY, mode), [mode]);

  // Reflect the current page in the URL and the header.
  useEffect(() => {
    setJumpText(String(pageNo));
    nav(`/read/${pageNo}`, { replace: true });
    let cancelled = false;
    loadPage(pageNo)
      .then((p) => !cancelled && setSuraName({ name: p.suras[0].name, tname: p.suras[0].tname, juz: p.juz }))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pageNo, nav]);

  useEffect(() => {
    if (live.today?.completed && !wasComplete.current) toast("Today's reading is complete. May Allah accept it. 🌙", "ok");
    wasComplete.current = !!live.today?.completed;
  }, [live.today?.completed, toast]);
  useEffect(() => {
    if (live.lastCounted.length) toast(`Page ${live.lastCounted.join(", ")} counted ✓`, "info");
  }, [live.lastCounted, toast]);

  const go = useCallback((p: number) => {
    const target = Math.max(1, Math.min(TOTAL, p));
    setPageNo(target);
    setJump((j) => ({ page: target, nonce: j.nonce + 1 }));
  }, []);
  const next = useCallback(() => go(pageNo + 1), [go, pageNo]);
  const prev = useCallback(() => go(pageNo - 1), [go, pageNo]);
  const onFlowPage = useCallback((p: number) => setPageNo(p), []);

  function switchMode(m: Mode) {
    setMode(m);
    setJump((j) => ({ page: pageNo, nonce: j.nonce + 1 }));
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else rootRef.current?.requestFullscreen?.().catch(() => undefined);
  }
  useEffect(() => {
    const on = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  // Keyboard: the mushaf reads right-to-left, so ← is the next page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowLeft") next();
      else if (e.key === "ArrowRight") prev();
      else if (e.key === "f") toggleFullscreen();
      else if (e.key === "+" || e.key === "=") setFontSize((s) => Math.min(56, s + 2));
      else if (e.key === "-") setFontSize((s) => Math.max(16, s - 2));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const today = live.today ?? state.today;
  const reqSecs = today.required_seconds;
  const secs = Math.max(live.liveSeconds, today.active_seconds);
  const pagesDone = today.pages_read;
  const paused = live.status === "active" ? live.pauseReason : null;
  const statusText =
    live.status === "starting"
      ? "Connecting…"
      : live.status === "error"
        ? live.error ?? "Not connected"
        : live.status === "superseded"
          ? "Continued on another device"
          : paused
            ? PAUSE_TEXT[paused]
            : "Reading · timer running";
  const pageNeed = Math.max(0, live.minPageSeconds - live.pageSeconds);

  return (
    <div className={`reader theme-${theme} mode-${mode} ${fullscreen ? "is-fullscreen" : ""}`} ref={rootRef} style={{ ["--reader-size" as string]: `${fontSize}px` }}>
      <div className="reader-top">
        <Link to="/" className="btn btn-icon btn-ghost" title="Back to dashboard">
          <Icon name="home" />
        </Link>
        <div className="reader-title">
          <span className="reader-sura" lang="ar">
            {suraName ? `سورة ${suraName.name}` : "…"}
          </span>
          <span className="muted small">
            {suraName?.tname} · Juz {suraName?.juz ?? "…"} · Page {pageNo} / {TOTAL}
          </span>
        </div>
        <div className="reader-tools">
          <div className="seg" role="group" aria-label="Layout">
            <button className={mode === "flow" ? "on" : ""} onClick={() => switchMode("flow")} title="Flowing text (like an e-book)">
              Flow
            </button>
            <button className={mode === "mushaf" ? "on" : ""} onClick={() => switchMode("mushaf")} title="One mushaf page at a time">
              Mushaf
            </button>
          </div>
          <button className="btn btn-icon btn-ghost" onClick={() => setFontSize((s) => Math.max(16, s - 2))} title="Smaller text (-)">
            <Icon name="minus" />
          </button>
          <button className="btn btn-icon btn-ghost" onClick={() => setFontSize((s) => Math.min(56, s + 2))} title="Larger text (+)">
            <Icon name="plus" />
          </button>
          <button className="btn btn-icon btn-ghost" onClick={() => setTheme((t) => (t === "night" ? "paper" : "night"))} title="Reading theme">
            <Icon name={theme === "night" ? "sun" : "moon"} />
          </button>
          <button className="btn btn-icon btn-ghost hide-sm" onClick={toggleFullscreen} title="Fullscreen (F)">
            <Icon name={fullscreen ? "shrink" : "expand"} />
          </button>
        </div>
      </div>

      <div className="reader-status">
        <div className={`status-chip ${paused || live.status !== "active" ? "is-paused" : "is-live"}`}>
          <span className="status-dot" />
          {statusText}
        </div>
        <div className="status-metric">
          <div className="metric-row small">
            <span className="muted">
              <Icon name="clock" size={13} /> Today
            </span>
            <span className="tabular">
              <strong>{clock(secs)}</strong> / {clock(reqSecs)}
            </span>
          </div>
          <Bar value={secs / reqSecs} tone={secs >= reqSecs ? "accent" : "gold"} />
          <span className="muted tiny">{secs >= reqSecs ? "Time goal met" : `${clock(reqSecs - secs)} remaining`}</span>
        </div>
        <div className="status-metric">
          <div className="metric-row small">
            <span className="muted">
              <Icon name="pages" size={13} /> Pages
            </span>
            <span className="tabular">
              <strong>{pagesDone}</strong> / {today.required_pages}
            </span>
          </div>
          <Bar value={pagesDone / today.required_pages} tone={pagesDone >= today.required_pages ? "accent" : "gold"} />
          <span className="muted tiny">
            {today.completed
              ? "Today's task complete ✓"
              : pagesDone >= today.required_pages
                ? "Page goal met"
                : `${plural(today.required_pages - pagesDone, "page")} remaining`}
          </span>
        </div>
        <div className="status-page small">
          {live.pageCounted ? (
            <span className="ok">
              <Icon name="check" size={14} /> Page {pageNo} counted
            </span>
          ) : (
            <span className="muted">
              Page {pageNo} counts after <strong className="tabular">{Math.ceil(pageNeed)}s</strong>
            </span>
          )}
          {live.status === "active" &&
            (paused === "manual" ? (
              <button className="btn btn-sm btn-ghost" onClick={resume}>
                <Icon name="play" size={14} /> Resume
              </button>
            ) : (
              <button className="btn btn-sm btn-ghost" onClick={pause}>
                <Icon name="pause" size={14} /> Pause
              </button>
            ))}
        </div>
      </div>

      {mode === "flow" ? <FlowView jump={jump} onPage={onFlowPage} /> : <MushafView page={pageNo} onNext={next} onPrev={prev} />}

      <div className="reader-nav">
        <button className="btn btn-nav" onClick={next} disabled={pageNo >= TOTAL} title="Next page (←)">
          <Icon name="left" /> <span className="hide-sm">Next</span>
        </button>
        <div className="reader-jump">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const n = Number(jumpText);
              if (Number.isFinite(n)) go(Math.round(n));
            }}
          >
            <input className="page-input tabular" inputMode="numeric" value={jumpText} onChange={(e) => setJumpText(e.target.value)} aria-label="Page number" />
            <span className="muted small"> / {TOTAL}</span>
          </form>
          <select aria-label="Go to surah" value="" onChange={(e) => e.target.value && go(Number(e.target.value))}>
            <option value="">Surah…</option>
            {meta.suras.map((s) => (
              <option key={s.index} value={s.start_page}>
                {s.index}. {s.tname} ({s.name})
              </option>
            ))}
          </select>
          <select aria-label="Go to juz" value="" onChange={(e) => e.target.value && go(Number(e.target.value))}>
            <option value="">Juz…</option>
            {meta.juzs.map((j) => (
              <option key={j.index} value={j.start_page}>
                Juz {j.index} · p. {j.start_page}
              </option>
            ))}
          </select>
        </div>
        <button className="btn btn-nav" onClick={prev} disabled={pageNo <= 1} title="Previous page (→)">
          <span className="hide-sm">Previous</span> <Icon name="right" />
        </button>
      </div>
      <div className="khatma-strip" title={`Khatma #${live.khatma}: ${live.countedPages.size} of ${TOTAL} pages read`}>
        <div className="khatma-pos" style={{ width: `${(pageNo / TOTAL) * 100}%` }} />
        <span className="tiny muted">
          Position {((pageNo / TOTAL) * 100).toFixed(1)}% · Khatma #{live.khatma}: {live.countedPages.size}/{TOTAL} pages read
        </span>
      </div>

      {live.status === "active" && paused === "idle" && (
        <div className="overlay" onClick={nudge}>
          <div className="overlay-card fade-in">
            <Icon name="pause" size={28} />
            <h3>Still reading?</h3>
            <p className="muted">
              The timer paused after {live.inactivitySeconds} seconds without any activity. Paused time is never counted.
            </p>
            <button className="btn btn-primary" onClick={nudge}>
              Continue reading
            </button>
          </div>
        </div>
      )}
      {live.status === "superseded" && (
        <div className="overlay">
          <div className="overlay-card fade-in">
            <Icon name="book" size={28} />
            <h3>Reading continued elsewhere</h3>
            <p className="muted">You opened the reader on another device or tab. Only one reading session can run at a time.</p>
            <button className="btn btn-primary" onClick={resumeHere}>
              Read here instead
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ReaderPage() {
  const params = useParams();
  const [state, setState] = useState<ReadingState | null>(null);
  const [meta, setMeta] = useState<QuranMeta | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    Promise.all([get<ReadingState>("/api/reading/state"), loadMeta()])
      .then(([s, m]) => {
        setState(s);
        setMeta(m);
      })
      .catch((e) => setError((e as Error).message));
  }, []);
  useEffect(load, [load]);

  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!state || !meta) return <Spinner />;
  const p = Number(params.page);
  const start = Number.isInteger(p) && p >= 1 && p <= TOTAL ? p : state.current_page;
  return <ReaderInner state={state} meta={meta} startPage={start} />;
}

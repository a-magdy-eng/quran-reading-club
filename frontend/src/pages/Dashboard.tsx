import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { Avatar, Bar, ErrorBox, Icon, Pill, Ring, Spinner, StreakFlame } from "../components";
import { clock, countdown, plural, timeIn } from "../format";
import { StreakCalendar } from "../StreakCalendar";
import type { CalendarDay, Dashboard as DashboardData, MemberRow } from "../types";

export function usePolling<T>(path: string, intervalMs = 20000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await get<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [path]);
  useEffect(() => {
    load();
    const id = window.setInterval(() => document.visibilityState === "visible" && load(), intervalMs);
    const onVis = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [load, intervalMs]);
  return { data, error, reload: load };
}

function statusPill(m: MemberRow) {
  if (m.status === "done") return <Pill tone="done"><Icon name="check" size={13} /> Done</Pill>;
  if (m.status === "new" || m.excused_today) return <Pill tone="new">Joined today</Pill>;
  if (m.status === "in_progress") return <Pill tone="progress">In progress</Pill>;
  return <Pill tone="idle">Not started</Pill>;
}

function MemberCard({ m }: { m: MemberRow }) {
  const t = m.today;
  return (
    <div className={`card member-card ${m.status === "done" ? "is-done" : ""} ${m.is_you ? "is-you" : ""}`}>
      <div className="member-head">
        <Avatar name={m.display_name} live={m.reading_now} />
        <div className="member-name">
          <strong>
            {m.display_name}
            {m.is_you && <span className="muted small"> (you)</span>}
          </strong>
          <span className="muted small">
            {m.reading_now ? <span className="live-text">Reading now</span> : `${m.position.sura_tname} · p. ${m.position.page}`}
          </span>
        </div>
        {statusPill(m)}
      </div>
      <div className="member-metrics">
        <div>
          <div className="metric-row">
            <span className="muted small">Pages</span>
            <span className="small">
              <strong>{t.pages_read}</strong> / {t.required_pages}
            </span>
          </div>
          <Bar value={t.pages_read / t.required_pages} tone={t.pages_read >= t.required_pages ? "accent" : "gold"} />
        </div>
        <div>
          <div className="metric-row">
            <span className="muted small">Active time</span>
            <span className="small">
              <strong>{Math.floor(t.active_seconds / 60)}</strong> / {Math.round(t.required_seconds / 60)} min
            </span>
          </div>
          <Bar value={t.active_seconds / t.required_seconds} tone={t.active_seconds >= t.required_seconds ? "accent" : "gold"} />
        </div>
      </div>
      <div className="member-foot small muted">
        <span title="Current streak">
          <Icon name="flame" size={14} className="gold" /> {plural(m.streak.current, "day")}
        </span>
        <span title="Longest streak">best {m.streak.longest}</span>
        <span title="Khatma">khatma #{m.position.khatma}</span>
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { data, error, reload } = usePolling<DashboardData>("/api/dashboard");
  const cal = usePolling<{ days: CalendarDay[]; today: string }>("/api/calendar?days=120", 60000);
  const [, force] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => force((n) => n + 1), 30000);
    return () => window.clearInterval(id);
  }, []);

  if (error && !data) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const me = data.members.find((m) => m.is_you);
  const s = data.streak;
  const allDone = data.completion.all_done;
  const remaining = data.members.filter((m) => !m.today.completed && !m.excused_today);

  return (
    <div className="page fade-in">
      <section className={`hero card ${allDone ? "hero-done" : ""}`}>
        <div className="hero-streak">
          <StreakFlame days={s.current} lit={s.current > 0 || allDone} />
          <div>
            <div className="eyebrow">Group streak</div>
            <div className="hero-number">
              {plural(s.current, "day")}
            </div>
            <div className="muted small">Longest: {plural(s.longest, "day")}</div>
          </div>
        </div>
        <div className="hero-mid">
          <h1 className="group-title">{data.group.name}</h1>
          <p className="hero-msg">
            {allDone
              ? "Everyone has completed today's reading. The streak grows tonight. ✨"
              : remaining.length === 1
                ? `Waiting on ${remaining[0].display_name} to keep the streak alive.`
                : `${data.completion.completed} of ${data.completion.required} members done today.`}
          </p>
          <div className="hero-meta small muted">
            <span>
              <Icon name="clock" size={14} /> Day resets in <strong>{countdown(data.deadline)}</strong> (
              {timeIn(data.deadline, data.settings.timezone)} {data.settings.timezone})
            </span>
            <span>
              <Icon name="pages" size={14} /> {data.settings.min_pages} pages + {data.settings.min_minutes} min each
            </span>
          </div>
        </div>
        <Ring value={data.completion.percent / 100} size={128} color={allDone ? "var(--accent)" : "var(--gold)"}>
          <div className="ring-value">{data.completion.percent}%</div>
          <div className="ring-label">today</div>
        </Ring>
      </section>

      <div className="dash-grid">
        {me && (
          <section className="card you-card">
            <div className="eyebrow">Your reading today</div>
            <div className="you-row">
              <Ring value={me.today.pages_read / me.today.required_pages} size={86} stroke={8}>
                <div className="ring-value sm">{me.today.pages_read}</div>
                <div className="ring-label">/{me.today.required_pages} pages</div>
              </Ring>
              <Ring value={me.today.active_seconds / me.today.required_seconds} size={86} stroke={8} color="var(--gold)">
                <div className="ring-value sm">{Math.floor(me.today.active_seconds / 60)}</div>
                <div className="ring-label">/{Math.round(me.today.required_seconds / 60)} min</div>
              </Ring>
              <div className="you-text">
                {me.today.completed ? (
                  <p>
                    <strong className="ok">Today's task is complete.</strong> Anything more is a bonus.
                  </p>
                ) : (
                  <p>
                    {me.today.remaining_pages > 0 && <>{plural(me.today.remaining_pages, "page")} </>}
                    {me.today.remaining_pages > 0 && me.today.remaining_seconds > 0 && "and "}
                    {me.today.remaining_seconds > 0 && <>{clock(me.today.remaining_seconds)} of reading </>}
                    left.
                  </p>
                )}
                <Link to="/read" className="btn btn-primary">
                  <Icon name="book" /> Continue · {me.position.sura_tname} p. {me.position.page}
                </Link>
              </div>
            </div>
          </section>
        )}
        <section className="card assignment-card">
          <div className="eyebrow">Assigned reading</div>
          {data.assignment ? (
            <>
              <h3 className="assignment-title">{data.assignment.label}</h3>
              <p className="muted small">
                Pages {data.assignment.start_page}–{data.assignment.end_page} · Juz {data.assignment.start.juz}
                {data.assignment.end.juz !== data.assignment.start.juz && `–${data.assignment.end.juz}`}
              </p>
              {data.assignment.note && <p className="assignment-note">{data.assignment.note}</p>}
              <Link to={`/read/${data.assignment.start_page}`} className="btn btn-ghost">
                Open page {data.assignment.start_page}
              </Link>
            </>
          ) : (
            <p className="muted">No assignment. Everyone continues from their own bookmark.</p>
          )}
          <div className="stat-inline small muted">
            <Icon name="pages" size={14} /> {plural(data.pages_today, "page")} read by the group today
          </div>
        </section>
      </div>

      <h2 className="section-title">Members</h2>
      <div className="members-grid">
        {data.members.map((m) => (
          <MemberCard key={m.user_id} m={m} />
        ))}
      </div>

      <h2 className="section-title">Streak history</h2>
      <section className="card">
        {cal.data ? <StreakCalendar days={cal.data.days} today={cal.data.today} /> : <Spinner />}
      </section>
      {error && <p className="muted small">Live update failed: {error}</p>}
      <p className="muted small center">Refreshes automatically every 20 seconds.</p>
    </div>
  );
}

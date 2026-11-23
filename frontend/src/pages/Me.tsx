import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { patch, post } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Icon, Modal, Ring, Spinner, StreakFlame, useToast } from "../components";
import { clock, dateTime, duration, plural, shortDay } from "../format";
import { StreakCalendar } from "../StreakCalendar";
import type { CalendarDay, MemberStats } from "../types";
import { usePolling } from "./Dashboard";

export function KhatmaMap({ counted, current }: { counted: number[]; current: number }) {
  const set = new Set(counted);
  return (
    <div className="khatma-map" aria-label="Pages read in this khatma">
      {Array.from({ length: 604 }, (_, i) => i + 1).map((p) => (
        <Link
          to={`/read/${p}`}
          key={p}
          className={`km-cell ${set.has(p) ? "read" : ""} ${p === current ? "current" : ""}`}
          title={`Page ${p}${set.has(p) ? " · read" : ""}`}
        />
      ))}
    </div>
  );
}

export function HistoryTable({ rows }: { rows: MemberStats["history"] }) {
  if (!rows.length) return <p className="muted">No reading recorded yet.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Day</th>
            <th>Pages</th>
            <th>Active time</th>
            <th>Requirement</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.day}>
              <td>{shortDay(r.day)}</td>
              <td className="tabular">{r.pages_read}</td>
              <td className="tabular">{clock(r.active_seconds)}</td>
              <td className="muted small">
                {r.required_pages} p · {Math.round(r.required_seconds / 60)} min
              </td>
              <td>
                <span className={`outcome out-${r.outcome}`}>{r.outcome === "excused" ? "joined" : r.outcome}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SessionsTable({ rows, showName }: { rows: MemberStats["sessions"]; showName?: boolean }) {
  if (!rows.length) return <p className="muted">No sessions yet.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showName && <th>Member</th>}
            <th>Started</th>
            <th>Ended</th>
            <th>Pages</th>
            <th>New pages</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              {showName && <td>{s.name}</td>}
              <td>{dateTime(s.started_at)}</td>
              <td className="muted">{s.status === "active" ? <span className="live-text">live</span> : dateTime(s.ended_at)}</td>
              <td className="small">
                {s.start_page === s.end_page ? `p. ${s.start_page}` : `p. ${s.start_page} → ${s.end_page}`}
                <span className="muted"> · {s.start_sura}</span>
              </td>
              <td className="tabular">{s.pages_read}</td>
              <td className="tabular">{clock(s.active_seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatsView({ data, calendar, personal }: { data: MemberStats; calendar?: { days: CalendarDay[]; today: string } | null; personal?: boolean }) {
  const t = data.today;
  return (
    <>
      <div className="stat-grid">
        <div className="card stat">
          <StreakFlame days={data.streak.current} size="sm" />
          <div>
            <div className="stat-value">{plural(data.streak.current, "day")}</div>
            <div className="stat-label">Current streak</div>
          </div>
        </div>
        <div className="card stat">
          <Icon name="star" size={26} className="gold" />
          <div>
            <div className="stat-value">{plural(data.streak.longest, "day")}</div>
            <div className="stat-label">Longest streak</div>
          </div>
        </div>
        <div className="card stat">
          <Icon name="pages" size={26} className="accent" />
          <div>
            <div className="stat-value">{data.totals.pages}</div>
            <div className="stat-label">Pages read (all time)</div>
          </div>
        </div>
        <div className="card stat">
          <Icon name="clock" size={26} className="accent" />
          <div>
            <div className="stat-value">{duration(data.totals.active_seconds)}</div>
            <div className="stat-label">Total reading time</div>
          </div>
        </div>
        <div className="card stat">
          <Icon name="check" size={26} className="accent" />
          <div>
            <div className="stat-value">{data.totals.days_completed}</div>
            <div className="stat-label">Days completed</div>
          </div>
        </div>
        <div className="card stat">
          <Icon name="bookmark" size={26} className="gold" />
          <div>
            <div className="stat-value">{data.totals.khatmas_completed}</div>
            <div className="stat-label">Khatmas completed</div>
          </div>
        </div>
      </div>

      <div className="dash-grid">
        <section className="card">
          <div className="eyebrow">Today</div>
          <div className="you-row">
            <Ring value={t.pages_read / t.required_pages} size={92} stroke={8}>
              <div className="ring-value sm">{t.pages_read}</div>
              <div className="ring-label">/{t.required_pages} pages</div>
            </Ring>
            <Ring value={t.active_seconds / t.required_seconds} size={92} stroke={8} color="var(--gold)">
              <div className="ring-value sm">{Math.floor(t.active_seconds / 60)}</div>
              <div className="ring-label">/{Math.round(t.required_seconds / 60)} min</div>
            </Ring>
            <div className="you-text">
              <p>{t.completed ? <strong className="ok">Complete ✓</strong> : "Not complete yet."}</p>
              {personal && (
                <Link to="/read" className="btn btn-primary">
                  <Icon name="book" /> Read
                </Link>
              )}
            </div>
          </div>
        </section>
        <section className="card">
          <div className="eyebrow">Current position</div>
          <h3 className="assignment-title">
            {data.position.sura_tname} <span className="ar-inline">{data.position.sura_name}</span>
          </h3>
          <p className="muted small">
            Page {data.position.page} of 604 · Juz {data.position.juz} · Khatma #{data.khatma.number}
          </p>
          <div className="metric-row small">
            <span className="muted">Khatma progress</span>
            <span>
              {data.khatma.counted} / 604 pages
            </span>
          </div>
          <div className="bar bar-accent">
            <div className="bar-fill" style={{ width: `${(data.khatma.counted / 604) * 100}%` }} />
          </div>
        </section>
      </div>

      <h2 className="section-title">Khatma map</h2>
      <section className="card">
        <p className="muted small">Each square is one mushaf page; filled squares have been read in this khatma.</p>
        <KhatmaMap counted={data.khatma.counted_pages} current={data.position.page} />
      </section>

      {calendar && (
        <>
          <h2 className="section-title">Streak calendar</h2>
          <section className="card">
            <StreakCalendar days={calendar.days} today={calendar.today} personalUserId={data.user.id} />
          </section>
        </>
      )}

      <h2 className="section-title">Reading history</h2>
      <section className="card">
        <HistoryTable rows={data.history} />
      </section>
      <h2 className="section-title">Sessions</h2>
      <section className="card">
        <SessionsTable rows={data.sessions} />
      </section>
    </>
  );
}

export function MePage() {
  const { me, refresh, signOut } = useAuth();
  const toast = useToast();
  const { data, error, reload } = usePolling<MemberStats>("/api/stats/me", 30000);
  const cal = usePolling<{ days: CalendarDay[]; today: string }>(`/api/calendar?days=180&user_id=${me?.user.id ?? 0}`, 60000);
  const [name, setName] = useState(me?.user.display_name ?? "");
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [khatmaOpen, setKhatmaOpen] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);

  if (error && !data) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  async function saveName(e: FormEvent) {
    e.preventDefault();
    try {
      await patch("/api/auth/profile", { display_name: name });
      await refresh();
      toast("Name updated");
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }
  async function savePw(e: FormEvent) {
    e.preventDefault();
    if (pw.new_password !== pw.confirm) return toast("Passwords do not match", "error");
    try {
      await post("/api/auth/password", { current_password: pw.current_password, new_password: pw.new_password });
      setPw({ current_password: "", new_password: "", confirm: "" });
      toast("Password changed. Other devices were signed out.");
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }

  return (
    <div className="page fade-in">
      <div className="page-head">
        <div>
          <div className="eyebrow">Personal dashboard</div>
          <h1>{data.user.display_name}</h1>
          <p className="muted small">
            @{data.user.username} · {data.user.role === "admin" ? "Administrator" : "Member"}
          </p>
        </div>
      </div>
      <StatsView data={data} calendar={cal.data} personal />

      {data.khatma.can_start_new && (
        <section className="card khatma-new">
          <h3>Masha'Allah: you have read {data.khatma.counted} pages in this khatma.</h3>
          <p className="muted">Start khatma #{data.khatma.number + 1} to begin counting pages from the start again.</p>
          <button className="btn btn-primary" onClick={() => setKhatmaOpen(true)}>
            Start a new khatma
          </button>
        </section>
      )}

      <h2 className="section-title">Account</h2>
      <div className="dash-grid">
        <form className="card stack" onSubmit={saveName}>
          <label className="field">
            <span>Display name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
          </label>
          <button className="btn btn-ghost">Save name</button>
        </form>
        <form className="card stack" onSubmit={savePw}>
          <label className="field">
            <span>Current password</span>
            <input type="password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} autoComplete="current-password" required />
          </label>
          <div className="grid-2">
            <label className="field">
              <span>New password</span>
              <input type="password" minLength={8} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} autoComplete="new-password" required />
            </label>
            <label className="field">
              <span>Confirm</span>
              <input type="password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} autoComplete="new-password" required />
            </label>
          </div>
          <button className="btn btn-ghost">Change password</button>
        </form>
      </div>
      <div className="row-end">
        <button className="btn btn-ghost" onClick={() => signOut()}>
          <Icon name="logout" /> Sign out
        </button>
        <button className="btn btn-danger-ghost" onClick={() => setLeaveOpen(true)}>
          Leave group
        </button>
      </div>

      <Modal
        open={khatmaOpen}
        title="Start a new khatma?"
        onClose={() => setKhatmaOpen(false)}
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => setKhatmaOpen(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={async () => {
                try {
                  await post("/api/reading/khatma/new");
                  setKhatmaOpen(false);
                  reload();
                  toast("New khatma started. Bismillah!");
                } catch (err) {
                  toast((err as Error).message, "error");
                }
              }}
            >
              Start khatma #{data.khatma.number + 1}
            </button>
          </>
        }
      >
        <p>Your bookmark moves to page 1 and all pages can be counted again. Your history and streaks are kept.</p>
      </Modal>
      <Modal
        open={leaveOpen}
        title="Leave this group?"
        onClose={() => setLeaveOpen(false)}
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => setLeaveOpen(false)}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              onClick={async () => {
                try {
                  await post("/api/group/leave");
                  await refresh();
                } catch (err) {
                  toast((err as Error).message, "error");
                  setLeaveOpen(false);
                }
              }}
            >
              Leave group
            </button>
          </>
        }
      >
        <p>You will stop counting toward the group streak. Your reading history is kept. You can rejoin with an invitation code.</p>
      </Modal>
    </div>
  );
}

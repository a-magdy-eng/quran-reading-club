import { useMemo, useState } from "react";
import type { CalendarDay } from "./types";
import { duration, shortDay } from "./format";

const STATUS_LABEL: Record<string, string> = {
  success: "Everyone completed",
  failed: "Streak broken",
  neutral: "No requirement",
  pending: "In progress",
  none: "No data",
};

function addDays(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + n));
  return dt.toISOString().slice(0, 10);
}

function weekday(day: string): number {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday
}

/** GitHub-style heat-map of reading days. `personal` colours by one member's outcome. */
export function StreakCalendar({ days, today, weeks = 16, personalUserId }: { days: CalendarDay[]; today: string; weeks?: number; personalUserId?: number }) {
  const [hover, setHover] = useState<CalendarDay | null>(null);
  const byDay = useMemo(() => new Map(days.map((d) => [d.day, d])), [days]);

  const grid = useMemo(() => {
    const end = addDays(today, 6 - weekday(today)); // end of this week (Saturday)
    const start = addDays(end, -(weeks * 7 - 1));
    const cols: string[][] = [];
    for (let w = 0; w < weeks; w++) {
      const col: string[] = [];
      for (let i = 0; i < 7; i++) col.push(addDays(start, w * 7 + i));
      cols.push(col);
    }
    return cols;
  }, [today, weeks]);

  const statusOf = (d: CalendarDay | undefined): string => {
    if (!d) return "none";
    if (personalUserId == null) return d.status;
    const m = d.members.find((x) => x.user_id === personalUserId);
    if (!m) return "none";
    return { completed: "success", failed: "failed", excused: "neutral", pending: "pending" }[m.outcome] ?? "none";
  };

  return (
    <div className="calendar">
      <div className="calendar-grid" onMouseLeave={() => setHover(null)}>
        {grid.map((col, i) => (
          <div className="calendar-col" key={i}>
            {col.map((day) => {
              const d = byDay.get(day);
              const st = day > today ? "future" : statusOf(d);
              return (
                <button
                  type="button"
                  key={day}
                  className={`cal-cell cal-${st} ${day === today ? "cal-today" : ""}`}
                  title={`${shortDay(day)} — ${STATUS_LABEL[st] ?? ""}`}
                  onMouseEnter={() => d && setHover(d)}
                  onFocus={() => d && setHover(d)}
                  onClick={() => d && setHover(d)}
                  disabled={day > today}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="calendar-legend small muted">
        <span><i className="cal-cell cal-success" /> complete</span>
        <span><i className="cal-cell cal-failed" /> missed</span>
        <span><i className="cal-cell cal-pending" /> today</span>
        <span><i className="cal-cell cal-neutral" /> no requirement</span>
      </div>
      <div className="calendar-detail">
        {hover ? (
          <>
            <strong>{shortDay(hover.day)}</strong>{" "}
            <span className="muted">
              · {STATUS_LABEL[statusOf(hover)]}
              {hover.provisional && hover.status !== "pending" ? " (not final yet)" : ""}
            </span>
            <ul className="cal-members">
              {hover.members.map((m) => (
                <li key={m.user_id} className={`out-${m.outcome}`}>
                  <span className="dot" /> {m.name}
                  <span className="muted small">
                    {" "}
                    {m.outcome === "excused" ? "joined that day" : m.outcome} · {m.pages_read} p · {duration(m.active_seconds)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <span className="muted small">Hover or tap a day for details.</span>
        )}
      </div>
    </div>
  );
}

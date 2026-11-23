import { useCallback, useEffect, useState, type FormEvent } from "react";
import { del, get, patch, post } from "../api";
import { useAuth } from "../auth";
import { CopyButton, ErrorBox, Icon, Modal, Spinner, useToast } from "../components";
import { shortDay } from "../format";
import { loadMeta } from "../quran";
import type { Assignment, MemberStats, QuranMeta, SessionRow, Settings } from "../types";
import { HistoryTable, SessionsTable } from "./Me";
import { TimezoneSelect } from "./AuthPages";

interface AdminData {
  group: { id: number; name: string; invite_code: string; invite_enabled: boolean; max_members: number; created_at: string };
  settings: Settings;
  members: { user_id: number; username: string; display_name: string; role: string; joined_at: string }[];
  former_members: { user_id: number; display_name: string; left_at: string }[];
  assignment: Assignment | null;
  today: string;
}

function SettingsForm({ settings, onSaved }: { settings: Settings; onSaved: () => void }) {
  const toast = useToast();
  const [zones, setZones] = useState<string[]>([]);
  const [form, setForm] = useState({
    min_pages: settings.min_pages,
    min_minutes: settings.min_minutes,
    timezone: settings.timezone,
    reset_time: settings.reset_time,
    inactivity_timeout_seconds: settings.inactivity_timeout_seconds,
    min_page_seconds: settings.min_page_seconds,
  });
  useEffect(() => {
    get("/api/info").then((i) => setZones(i.timezones)).catch(() => undefined);
  }, []);
  const num = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: Number(e.target.value) });
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await patch("/api/admin/settings", form);
      toast("Settings saved. Days already completed stay completed.");
      onSaved();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }
  return (
    <form className="card stack" onSubmit={submit}>
      <h3>Daily requirements</h3>
      <div className="grid-2">
        <label className="field">
          <span>Minimum pages per day</span>
          <input type="number" min={1} max={604} value={form.min_pages} onChange={num("min_pages")} />
        </label>
        <label className="field">
          <span>Minimum active minutes per day</span>
          <input type="number" min={1} max={600} step={1} value={form.min_minutes} onChange={num("min_minutes")} />
        </label>
      </div>
      <div className="grid-2">
        <TimezoneSelect value={form.timezone} onChange={(v) => setForm({ ...form, timezone: v })} zones={zones} />
        <label className="field">
          <span>Daily reset time (deadline)</span>
          <input type="time" value={form.reset_time} onChange={(e) => setForm({ ...form, reset_time: e.target.value })} />
          <small className="muted">A new reading day starts at this local time.</small>
        </label>
      </div>
      <div className="grid-2">
        <label className="field">
          <span>Inactivity timeout (seconds)</span>
          <input type="number" min={15} max={900} value={form.inactivity_timeout_seconds} onChange={num("inactivity_timeout_seconds")} />
          <small className="muted">The timer pauses after this long without any interaction.</small>
        </label>
        <label className="field">
          <span>Seconds on a page before it counts</span>
          <input type="number" min={3} max={600} value={form.min_page_seconds} onChange={num("min_page_seconds")} />
          <small className="muted">Stops quick page-flipping from counting as reading.</small>
        </label>
      </div>
      <p className="muted small">
        Changes apply to today if today is not yet complete, and to all future days. Completed days are never changed.
      </p>
      <button className="btn btn-primary">Save requirements</button>
    </form>
  );
}

function AssignmentForm({ assignment, meta, onSaved }: { assignment: Assignment | null; meta: QuranMeta | null; onSaved: () => void }) {
  const toast = useToast();
  const [start, setStart] = useState(assignment?.start_page ?? 1);
  const [end, setEnd] = useState(assignment?.end_page ?? 2);
  const [note, setNote] = useState(assignment?.note ?? "");
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await post("/api/admin/assignment", { start_page: start, end_page: end, note });
      toast("Assignment saved");
      onSaved();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }
  function pickSura(i: number) {
    if (!meta) return;
    const s = meta.suras[i - 1];
    let last = 604;
    if (i < 114) {
      const nextStart = meta.suras[i].start_page;
      // If the next surah begins at the top of its page, this surah ended on the page before.
      const topOfPage = meta.page_index[nextStart - 1]?.sura === i + 1;
      last = topOfPage ? nextStart - 1 : nextStart;
    }
    setStart(s.start_page);
    setEnd(Math.max(s.start_page, last));
  }
  function pickJuz(j: number) {
    if (!meta) return;
    setStart(meta.juzs[j - 1].start_page);
    setEnd(j < 30 ? meta.juzs[j].start_page - 1 : 604);
  }
  return (
    <form className="card stack" onSubmit={save}>
      <h3>Assigned reading</h3>
      {assignment ? (
        <p className="muted small">
          Current: <strong>{assignment.label}</strong>, pages {assignment.start_page}–{assignment.end_page}
        </p>
      ) : (
        <p className="muted small">No assignment: members read from their own bookmark.</p>
      )}
      <div className="grid-2">
        <label className="field">
          <span>Quick pick: surah</span>
          <select value="" onChange={(e) => e.target.value && pickSura(Number(e.target.value))}>
            <option value="">Choose…</option>
            {meta?.suras.map((s) => (
              <option key={s.index} value={s.index}>
                {s.index}. {s.tname}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Quick pick: juz</span>
          <select value="" onChange={(e) => e.target.value && pickJuz(Number(e.target.value))}>
            <option value="">Choose…</option>
            {Array.from({ length: 30 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                Juz {i + 1}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid-3">
        <label className="field">
          <span>From page</span>
          <input type="number" min={1} max={604} value={start} onChange={(e) => setStart(Number(e.target.value))} />
        </label>
        <label className="field">
          <span>To page</span>
          <input type="number" min={1} max={604} value={end} onChange={(e) => setEnd(Number(e.target.value))} />
        </label>
        <label className="field">
          <span>Note (optional)</span>
          <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="e.g. This week's portion" />
        </label>
      </div>
      <div className="row">
        <button className="btn btn-primary">Assign to group</button>
        {assignment && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={async () => {
              await del("/api/admin/assignment");
              toast("Assignment cleared");
              onSaved();
            }}
          >
            Clear assignment
          </button>
        )}
      </div>
    </form>
  );
}

export function AdminPage() {
  const toast = useToast();
  const { me, refresh } = useAuth();
  const [data, setData] = useState<AdminData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<QuranMeta | null>(null);
  const [newMember, setNewMember] = useState({ username: "", display_name: "" });
  const [credential, setCredential] = useState<{ username: string; password: string } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<{ user_id: number; display_name: string } | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetName, setResetName] = useState("");
  const [groupForm, setGroupForm] = useState({ name: "", max_members: 10 });
  const [historyUser, setHistoryUser] = useState<number | "">("");
  const [history, setHistory] = useState<MemberStats | null>(null);
  const [allSessions, setAllSessions] = useState<SessionRow[]>([]);
  const [sharing, setSharing] = useState<{ status: string; public_url: string | null; named: boolean; lan_urls: string[] } | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await get<AdminData>("/api/admin/group");
      setData(d);
      setGroupForm({ name: d.group.name, max_members: d.group.max_members });
      setError(null);
      setAllSessions((await get("/api/admin/sessions?limit=50")).sessions);
      setSharing(await get("/api/admin/sharing"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
    loadMeta().then(setMeta).catch(() => undefined);
  }, [load]);
  useEffect(() => {
    if (historyUser === "") return setHistory(null);
    get<MemberStats>(`/api/stats/members/${historyUser}`)
      .then(setHistory)
      .catch((e) => toast((e as Error).message, "error"));
  }, [historyUser, toast]);

  if (error && !data) return <ErrorBox error={error} onRetry={load} />;
  if (!data) return <Spinner />;

  const local = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  const base = sharing?.public_url ?? (local && sharing?.lan_urls[0] ? sharing.lan_urls[0] : window.location.origin);
  const inviteLink = `${base}/join?code=${data.group.invite_code}`;

  async function addMember(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await post("/api/admin/members", newMember);
      setCredential({ username: res.username, password: res.password });
      setNewMember({ username: "", display_name: "" });
      load();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      toast(ok);
      load();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }

  return (
    <div className="page fade-in">
      <div className="page-head">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>{data.group.name}</h1>
          <p className="muted small">
            {data.members.length} / {data.group.max_members} members · reading day {shortDay(data.today)}
          </p>
        </div>
      </div>

      <div className="dash-grid">
        <section className="card stack">
          <h3>Invite friends</h3>
          <p className="muted small">Share the code, or the invite link which fills it in for them.</p>
          <div className="invite-code mono">{data.group.invite_code}</div>
          {sharing?.public_url ? (
            <div className="online-box">
              <span className="pill pill-done">● Online</span>
              <span className="mono small">{sharing.public_url}</span>
              <CopyButton text={sharing.public_url} label="Copy" />
              {!sharing.named && <small className="muted">This free address changes whenever sharing restarts.</small>}
            </div>
          ) : (
            <p className="muted small">
              Friends outside your Wi-Fi: click <strong>Share online</strong> in the host window on the laptop to get a
              secure link that works from anywhere.
            </p>
          )}
          <div className="row wrap">
            <CopyButton text={data.group.invite_code} label="Copy code" />
            <CopyButton text={inviteLink} label="Copy invite link" />
            <button className="btn btn-ghost btn-sm" onClick={() => act(() => post("/api/admin/invite/regenerate"), "New code generated; the old one no longer works")}>
              <Icon name="refresh" size={15} /> New code
            </button>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={data.group.invite_enabled}
              onChange={(e) => act(() => patch("/api/admin/group", { invite_enabled: e.target.checked }), e.target.checked ? "Invitations enabled" : "Invitations disabled")}
            />
            <span>Allow joining with the code</span>
          </label>
        </section>
        <form
          className="card stack"
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await patch("/api/admin/group", groupForm);
              await refresh();
            }, "Group updated");
          }}
        >
          <h3>Group</h3>
          <label className="field">
            <span>Group name</span>
            <input value={groupForm.name} onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })} />
          </label>
          <label className="field">
            <span>Maximum members</span>
            <input type="number" min={2} max={50} value={groupForm.max_members} onChange={(e) => setGroupForm({ ...groupForm, max_members: Number(e.target.value) })} />
          </label>
          <button className="btn btn-ghost">Save group</button>
        </form>
      </div>

      <SettingsForm key={JSON.stringify(data.settings)} settings={data.settings} onSaved={() => { load(); refresh(); }} />

      <h2 className="section-title">Members</h2>
      <section className="card">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Joined</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.members.map((m) => (
                <tr key={m.user_id}>
                  <td>
                    <strong>{m.display_name}</strong> <span className="muted small">@{m.username}</span>
                  </td>
                  <td>{m.role === "admin" ? <span className="pill pill-live">admin</span> : <span className="muted">member</span>}</td>
                  <td className="muted small">{new Date(m.joined_at).toLocaleDateString()}</td>
                  <td className="row-end">
                    {m.user_id !== me?.user.id && (
                      <>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() =>
                            act(async () => {
                              const r = await post(`/api/admin/members/${m.user_id}/reset-password`);
                              setCredential({ username: r.username, password: r.password });
                            }, "Password reset")
                          }
                        >
                          Reset password
                        </button>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => act(() => post(`/api/admin/members/${m.user_id}/role`, { role: m.role === "admin" ? "member" : "admin" }), "Role updated")}
                        >
                          {m.role === "admin" ? "Make member" : "Make admin"}
                        </button>
                        <button className="btn btn-sm btn-danger-ghost" onClick={() => setConfirmRemove(m)}>
                          Remove
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form className="add-member" onSubmit={addMember}>
          <h4>Add a member directly</h4>
          <div className="grid-3">
            <input placeholder="Username" value={newMember.username} onChange={(e) => setNewMember({ ...newMember, username: e.target.value })} required />
            <input placeholder="Display name" value={newMember.display_name} onChange={(e) => setNewMember({ ...newMember, display_name: e.target.value })} />
            <button className="btn btn-ghost">
              <Icon name="plus" size={15} /> Create account
            </button>
          </div>
          <small className="muted">A temporary password is generated; give it to your friend so they can sign in and change it.</small>
        </form>
        {data.former_members.length > 0 && (
          <p className="muted small">Former members: {data.former_members.map((f) => f.display_name).join(", ")}</p>
        )}
      </section>

      <h2 className="section-title">Reading material</h2>
      <AssignmentForm key={data.assignment?.id ?? "none"} assignment={data.assignment} meta={meta} onSaved={load} />

      <h2 className="section-title">Reading history</h2>
      <section className="card stack">
        <label className="field">
          <span>Member</span>
          <select value={historyUser} onChange={(e) => setHistoryUser(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Recent sessions (everyone)</option>
            {data.members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name}
              </option>
            ))}
            {data.former_members.map((m) => (
              <option key={`f${m.user_id}`} value={m.user_id}>
                {m.display_name} (former)
              </option>
            ))}
          </select>
        </label>
        {historyUser === "" ? (
          <SessionsTable rows={allSessions} showName />
        ) : history ? (
          <>
            <p className="muted small">
              Streak {history.streak.current} (best {history.streak.longest}) · {history.totals.pages} pages ·{" "}
              {Math.round(history.totals.active_seconds / 60)} min total · position p. {history.position.page}
            </p>
            <HistoryTable rows={history.history} />
            <h4>Sessions</h4>
            <SessionsTable rows={history.sessions} />
          </>
        ) : (
          <Spinner />
        )}
      </section>

      <h2 className="section-title danger">Danger zone</h2>
      <section className="card danger-card">
        <div>
          <h3>Reset the group streak</h3>
          <p className="muted small">The current group streak goes back to zero. Longest streak and all history are kept.</p>
        </div>
        <button className="btn btn-danger" onClick={() => setResetOpen(true)}>
          Reset streak…
        </button>
      </section>

      <Modal
        open={!!credential}
        title="Sign-in details"
        onClose={() => setCredential(null)}
        actions={
          <button className="btn btn-primary" onClick={() => setCredential(null)}>
            Done
          </button>
        }
      >
        {credential && (
          <div className="stack">
            <p>Give these to your friend. The password is shown only once.</p>
            <div className="cred">
              <span className="muted">Username</span> <strong className="mono">{credential.username}</strong>
            </div>
            <div className="cred">
              <span className="muted">Password</span> <strong className="mono">{credential.password}</strong>
            </div>
            <CopyButton text={`Username: ${credential.username}\nPassword: ${credential.password}\n${window.location.origin}`} label="Copy all" />
          </div>
        )}
      </Modal>
      <Modal
        open={!!confirmRemove}
        title={`Remove ${confirmRemove?.display_name}?`}
        onClose={() => setConfirmRemove(null)}
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => setConfirmRemove(null)}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              onClick={() => {
                const m = confirmRemove!;
                setConfirmRemove(null);
                act(() => del(`/api/admin/members/${m.user_id}`), `${m.display_name} removed`);
              }}
            >
              Remove member
            </button>
          </>
        }
      >
        <p>They will no longer count toward the group streak from now on. Their history is kept; they can rejoin with a code.</p>
      </Modal>
      <Modal
        open={resetOpen}
        title="Reset the group streak?"
        onClose={() => setResetOpen(false)}
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => setResetOpen(false)}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              disabled={resetName !== data.group.name}
              onClick={() => {
                setResetOpen(false);
                setResetName("");
                act(() => post("/api/admin/streak/reset", { confirm_group_name: resetName }), "Group streak reset");
              }}
            >
              Reset streak
            </button>
          </>
        }
      >
        <p>
          Type the group name <strong>{data.group.name}</strong> to confirm. Counting starts again tomorrow.
        </p>
        <input value={resetName} onChange={(e) => setResetName(e.target.value)} placeholder={data.group.name} />
      </Modal>
    </div>
  );
}

import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, post } from "../api";
import { useAuth } from "../auth";
import { Icon } from "../components";
import { browserTimezone } from "../format";

interface Info {
  can_create_group: boolean;
  is_host: boolean;
  timezones: string[];
  attribution: { source: string; url: string };
}

function useInfo() {
  const [info, setInfo] = useState<Info | null>(null);
  useEffect(() => {
    api<Info>("/api/info").then(setInfo).catch(() => undefined);
  }, []);
  return info;
}

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="auth-shell">
      <div className="auth-card fade-in">
        <div className="brand-mark">
          <span className="brand-ar" lang="ar" dir="rtl">
            حلقة القرآن
          </span>
          <span className="brand-en">Quran Reading Club</span>
        </div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
        {children}
      </div>
      <p className="auth-foot muted small">
        Quran text: <a href="https://tanzil.net" target="_blank" rel="noreferrer">Tanzil Project</a> · Private
        reading club hosted on your own computer
      </p>
    </div>
  );
}

function Field({
  label,
  hint,
  ...props
}: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export function LoginPage() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const info = useInfo();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await post("/api/auth/login", { username, password });
      signIn(res.token, res.me);
      nav("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Welcome back" subtitle="Sign in to continue your daily reading.">
      <form onSubmit={submit} className="stack">
        <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus />
        <Field label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        {error && <p className="form-error">{error}</p>}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <div className="auth-links">
        <Link to="/join">I have an invitation code</Link>
        {info?.can_create_group && <Link to="/setup">Create a new group (host)</Link>}
      </div>
    </Shell>
  );
}

export function JoinPage() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ invite_code: params.get("code") ?? "", username: "", display_name: "", password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (form.password !== form.confirm) return setError("Passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      const res = await post("/api/auth/register", {
        invite_code: form.invite_code,
        username: form.username,
        display_name: form.display_name || form.username,
        password: form.password,
      });
      signIn(res.token, res.me);
      nav("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Join your reading club" subtitle="Your host gave you an invitation code.">
      <form onSubmit={submit} className="stack">
        <Field label="Invitation code" value={form.invite_code} onChange={set("invite_code")} required className="mono upper" placeholder="ABCD2345" />
        <div className="grid-2">
          <Field label="Username" value={form.username} onChange={set("username")} autoComplete="username" required hint="Letters, digits, . _ -" />
          <Field label="Display name" value={form.display_name} onChange={set("display_name")} placeholder="Shown to the group" />
        </div>
        <div className="grid-2">
          <Field label="Password" type="password" value={form.password} onChange={set("password")} autoComplete="new-password" required minLength={8} hint="At least 8 characters" />
          <Field label="Confirm password" type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" required />
        </div>
        {error && <p className="form-error">{error}</p>}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "Joining…" : "Create account & join"}
        </button>
      </form>
      <div className="auth-links">
        <Link to="/login">I already have an account</Link>
      </div>
    </Shell>
  );
}

export function TimezoneSelect({ value, onChange, zones }: { value: string; onChange: (v: string) => void; zones: string[] }) {
  const list = useMemo(() => (zones.includes(value) ? zones : [value, ...zones]), [zones, value]);
  return (
    <label className="field">
      <span>Group timezone</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {list.map((z) => (
          <option key={z} value={z}>
            {z}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SetupPage() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const info = useInfo();
  const [form, setForm] = useState({
    group_name: "",
    timezone: browserTimezone(),
    max_members: 10,
    min_pages: 2,
    min_minutes: 20,
    username: "",
    display_name: "",
    password: "",
    confirm: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

  if (info && !info.can_create_group) {
    return (
      <Shell title="Host only" subtitle="New groups can only be created on the host computer.">
        <p className="muted">Ask your host for an invitation code instead.</p>
        <Link className="btn btn-primary btn-block" to="/join">
          Join with a code
        </Link>
      </Shell>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (form.password !== form.confirm) return setError("Passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      const { confirm: _c, ...body } = form;
      const res = await post("/api/auth/setup", { ...body, display_name: form.display_name || form.username });
      signIn(res.token, res.me);
      nav("/admin");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Create your reading club" subtitle="You will be the group administrator.">
      <form onSubmit={submit} className="stack">
        <h4 className="section-label">The group</h4>
        <Field label="Group name" value={form.group_name} onChange={set("group_name")} required placeholder="e.g. Fajr Circle" />
        <TimezoneSelect value={form.timezone} onChange={(v) => setForm({ ...form, timezone: v })} zones={info?.timezones ?? []} />
        <div className="grid-3">
          <Field label="Pages / day" type="number" min={1} max={604} value={form.min_pages} onChange={set("min_pages")} />
          <Field label="Minutes / day" type="number" min={1} max={600} value={form.min_minutes} onChange={set("min_minutes")} />
          <Field label="Max members" type="number" min={2} max={50} value={form.max_members} onChange={set("max_members")} />
        </div>
        <h4 className="section-label">Your account</h4>
        <div className="grid-2">
          <Field label="Username" value={form.username} onChange={set("username")} required autoComplete="username" />
          <Field label="Display name" value={form.display_name} onChange={set("display_name")} />
        </div>
        <div className="grid-2">
          <Field label="Password" type="password" value={form.password} onChange={set("password")} required minLength={8} autoComplete="new-password" />
          <Field label="Confirm password" type="password" value={form.confirm} onChange={set("confirm")} required autoComplete="new-password" />
        </div>
        {error && <p className="form-error">{error}</p>}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "Creating…" : "Create group"}
        </button>
      </form>
      <div className="auth-links">
        <Link to="/login">Back to sign in</Link>
      </div>
    </Shell>
  );
}

export function NoGroupPage() {
  const { me, refresh, signOut } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();

  async function join(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await post("/api/groups/join", { invite_code: code });
      await refresh();
      nav("/");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Shell title={`Salaam, ${me?.user.display_name ?? ""}`} subtitle="You are not in a reading group right now.">
      <form onSubmit={join} className="stack">
        <Field label="Invitation code" value={code} onChange={(e) => setCode(e.target.value)} required className="mono upper" />
        {error && <p className="form-error">{error}</p>}
        <button className="btn btn-primary btn-block">Join group</button>
      </form>
      <div className="auth-links">
        {me?.can_create_group && <Link to="/create-group">Create a new group instead</Link>}
        <button className="link" onClick={() => signOut()}>
          <Icon name="logout" size={14} /> Sign out
        </button>
      </div>
    </Shell>
  );
}

export function CreateGroupPage() {
  const { refresh } = useAuth();
  const info = useInfo();
  const nav = useNavigate();
  const [form, setForm] = useState({ group_name: "", timezone: browserTimezone(), max_members: 10, min_pages: 2, min_minutes: 20 });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await post("/api/groups", form);
      await refresh();
      nav("/admin");
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <Shell title="New group" subtitle="You will be its administrator.">
      <form onSubmit={submit} className="stack">
        <Field label="Group name" value={form.group_name} onChange={(e) => setForm({ ...form, group_name: e.target.value })} required />
        <TimezoneSelect value={form.timezone} onChange={(v) => setForm({ ...form, timezone: v })} zones={info?.timezones ?? []} />
        {error && <p className="form-error">{error}</p>}
        <button className="btn btn-primary btn-block">Create group</button>
      </form>
      <div className="auth-links">
        <Link to="/">Back</Link>
      </div>
    </Shell>
  );
}

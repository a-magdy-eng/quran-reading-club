import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "./auth";
import { Icon } from "./components";

export function Layout() {
  const { me, signOut } = useAuth();
  const isAdmin = me?.membership?.role === "admin";
  const links = [
    { to: "/", label: "Group", icon: "users", end: true },
    { to: "/read", label: "Read", icon: "book" },
    { to: "/me", label: "Me", icon: "user" },
    ...(isAdmin ? [{ to: "/admin", label: "Admin", icon: "settings" }] : []),
  ];
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="logo">
            <span className="logo-star" aria-hidden="true">
              ۞
            </span>
            <span className="logo-text">{me?.group?.name ?? "Quran Reading Club"}</span>
          </NavLink>
          <nav className="nav-desktop">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} end={l.end} className="nav-link">
                <Icon name={l.icon} size={17} /> {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-user">
            <span className="muted small hide-sm">{me?.user.display_name}</span>
            <button className="btn btn-icon btn-ghost" title="Sign out" onClick={() => signOut()}>
              <Icon name="logout" size={17} />
            </button>
          </div>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
      <footer className="footer muted small">
        Quran text from the{" "}
        <a href="https://tanzil.net" target="_blank" rel="noreferrer">
          Tanzil Project
        </a>{" "}
        (Uthmani v1.1, CC BY 3.0, verbatim). Madani mushaf page layout.
      </footer>
      <nav className="nav-mobile">
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end} className="nav-mobile-link">
            <Icon name={l.icon} size={20} />
            <span>{l.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

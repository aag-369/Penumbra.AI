import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { useApp } from "../store/AppContext";
import { Badge, Dot } from "./ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", end: true },
  { to: "/keys", label: "Keys" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/advisor", label: "Advisor" },
  { to: "/lab", label: "Crypto Lab" },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      {/* A penumbra: the lit disc with its own shadow across it. */}
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="13" fill="#8b5cf6" />
        <path d="M16 3a13 13 0 000 26z" fill="#08090c" />
        <circle cx="16" cy="16" r="13" fill="none" stroke="#a78bfa" strokeOpacity="0.5" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight text-mist">PENUMBRA</span>
    </div>
  );
}

export default function Layout() {
  const { user, signOut, keyState, backend, metrics } = useApp();
  const navigate = useNavigate();

  const keyBadge =
    keyState === "ready" ? (
      <Badge tone="cipher">
        <Dot tone="cipher" /> key {metrics?.keyId.slice(0, 8) ?? "active"}
      </Badge>
    ) : keyState === "locked" ? (
      <Badge tone="warn">
        <Dot tone="warn" pulse /> key locked
      </Badge>
    ) : keyState === "generating" ? (
      <Badge tone="umbra">
        <Dot tone="umbra" pulse /> working
      </Badge>
    ) : (
      <Badge tone="neutral">
        <Dot /> no key
      </Badge>
    );

  return (
    <div className="flex min-h-screen items-start">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col overflow-y-auto border-r border-ink-700/80 bg-ink-900/50 px-4 py-5 lg:flex">
        <Link to="/" aria-label="PENUMBRA.AI — back to the website" className="rounded-md">
          <Logo />
        </Link>

        <nav className="mt-8 space-y-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-umbra/12 text-white shadow-[inset_2px_0_0_0_#8b5cf6]"
                    : "text-mist-dim hover:bg-ink-800 hover:text-mist"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
          {user?.role === "admin" && (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-umbra/12 text-white shadow-[inset_2px_0_0_0_#8b5cf6]"
                    : "text-mist-dim hover:bg-ink-800 hover:text-mist"
                }`
              }
            >
              Admin
            </NavLink>
          )}
        </nav>

        <div className="mt-auto space-y-3 pt-6">
          <div className="rounded-lg border border-ink-700 bg-ink-900/70 p-3">
            <div className="label mb-1.5">Backend</div>
            <div className="flex items-center gap-2 text-xs text-mist-dim">
              <Dot tone={backend?.mode === "live" ? "ok" : backend?.mode === "unreachable" ? "bad" : "umbra"} />
              {backend?.mode === "live" ? "API connected" : backend?.mode === "unreachable" ? "API unreachable" : "Standalone"}
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-mist-faint">
              Encryption runs in this browser either way.
            </p>
          </div>

          {user && (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-ink-700 px-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate text-xs text-mist">{user.email}</div>
                <div className="text-[11px] text-mist-faint">{user.role}</div>
              </div>
              <button
                onClick={() => void signOut().then(() => navigate("/login"))}
                className="shrink-0 text-[11px] text-mist-faint transition-colors hover:text-bad"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-ink-700/80 bg-ink-950/85 px-5 py-3 backdrop-blur-md lg:px-8">
          <div className="lg:hidden">
            <Link to="/" aria-label="PENUMBRA.AI — back to the website" className="rounded-md">
              <Logo />
            </Link>
          </div>
          <nav className="hidden gap-1 overflow-x-auto lg:hidden" />
          <div className="ml-auto flex items-center gap-2.5">{keyBadge}</div>
        </header>

        {/* Mobile navigation: the sidebar is hidden below lg. */}
        <nav className="flex gap-1 overflow-x-auto border-b border-ink-700/80 px-3 py-2 lg:hidden">
          {[...NAV, ...(user?.role === "admin" ? [{ to: "/admin", label: "Admin", end: false }] : [])].map(
            (item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={"end" in item ? item.end : false}
                className={({ isActive }) =>
                  `shrink-0 rounded-md px-3 py-1.5 text-xs transition-colors ${
                    isActive ? "bg-umbra/15 text-white" : "text-mist-dim hover:text-mist"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ),
          )}
        </nav>

        <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-7 lg:px-8">
          <Outlet />
        </main>

        <footer className="border-t border-ink-700/60 px-5 py-4 text-[11px] text-mist-faint lg:px-8">
          Portfolio data is encrypted with CKKS in this browser. The secret key does not leave this
          device — not to a server, and not to this page's own storage in unsealed form.
        </footer>
      </div>
    </div>
  );
}

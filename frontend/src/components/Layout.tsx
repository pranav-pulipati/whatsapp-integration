import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Account } from "../api/types";
import { useAuth } from "../lib/auth";
import { IconAlert, IconChat, IconLogout, IconMoon, IconOverview, IconPhone, IconPulse, IconSun, IconUsers } from "./icons";

type Theme = "light" | "dark" | null;

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("theme") as Theme) ?? null;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try {
      if (theme) localStorage.setItem("theme", theme);
      else localStorage.removeItem("theme");
    } catch {
      /* ignore */
    }
  }, [theme]);
  const systemDark = typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const effective = theme ?? (systemDark ? "dark" : "light");
  return [effective, () => setTheme(effective === "dark" ? "light" : "dark")];
}

export function Layout() {
  const { user, logout } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const attention = accounts.data?.filter((a) => a.health?.level === "warning").length ?? 0;

  const link = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <div className="brand">
          <span className="brand-mark">
            <IconChat size={16} />
          </span>
          <div>
            WhatsApp Sales
            <small>Unified dashboard</small>
          </div>
        </div>
        <NavLink to="/" end className={link}>
          <IconOverview /> Overview
        </NavLink>
        <NavLink to="/conversations" className={link}>
          <IconChat /> Conversations
        </NavLink>
        <NavLink to="/contacts" className={link}>
          <IconUsers /> Contacts
        </NavLink>
        <NavLink to="/numbers" className={link}>
          <IconPhone /> Numbers
          {accounts.data && (
            <span className="count" title={attention ? `${attention} need attention` : undefined}>
              {attention ? <IconAlert size={13} style={{ color: "var(--warning-ink)" }} /> : accounts.data.length}
            </span>
          )}
        </NavLink>
        {user?.role === "admin" && (
          <>
            <div className="nav-label">Admin</div>
            <NavLink to="/ops" className={link}>
              <IconPulse /> Ingestion
            </NavLink>
          </>
        )}
        <div className="sidebar-footer">
          <span className="who" title={user?.email}>{user?.email}</span>
          <button className="btn btn-ghost btn-icon" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>
          <button className="btn btn-ghost btn-icon" onClick={logout} aria-label="Sign out">
            <IconLogout />
          </button>
        </div>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

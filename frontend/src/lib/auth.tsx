import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, getToken, setToken } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const qc = useQueryClient();

  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    window.addEventListener("auth:expired", logout);
    return () => window.removeEventListener("auth:expired", logout);
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post<{ access_token: string; user: User }>("/auth/login", { email, password });
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  return <AuthContext.Provider value={{ user, ready, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

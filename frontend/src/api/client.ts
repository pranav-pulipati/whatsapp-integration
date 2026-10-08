const TOKEN_KEY = "wa-dashboard-token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function qs(params: Params = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api/v1${path}`, { ...init, headers });
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      /* non-JSON error */
    }
    if (res.status === 401 && path !== "/auth/login") {
      setToken(null);
      window.dispatchEvent(new Event("auth:expired"));
    }
    throw new ApiError(res.status, code, message);
  }
  return res;
}

export const api = {
  async get<T>(path: string, params?: Params): Promise<T> {
    return (await request(path + qs(params))).json();
  },
  async post<T>(path: string, body?: unknown): Promise<T> {
    const res = await request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
    return res.status === 204 ? (undefined as T) : res.json();
  },
  async patch<T>(path: string, body: unknown): Promise<T> {
    return (await request(path, { method: "PATCH", body: JSON.stringify(body) })).json();
  },
  async put(path: string, body: unknown): Promise<void> {
    await request(path, { method: "PUT", body: JSON.stringify(body) });
  },
  async blob(path: string): Promise<Blob> {
    return (await request(path)).blob();
  },
};

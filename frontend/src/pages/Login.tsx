import { useState, type FormEvent } from "react";
import { IconChat } from "../components/icons";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="card login-card">
        <span className="brand-mark" style={{ width: 36, height: 36, borderRadius: 10 }}>
          <IconChat size={18} />
        </span>
        <h1>Sign in to WhatsApp Sales</h1>
        <p className="secondary">Unified view of every sales number.</p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <div className="callout error" role="alert">{error}</div>}
          <button className="btn btn-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </div>
    </div>
  );
}

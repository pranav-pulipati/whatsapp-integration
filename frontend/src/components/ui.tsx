import { useEffect, useState, type ReactNode } from "react";
import type { CaptureHealth } from "../api/types";
import { initials } from "../lib/format";
import { IconAlert, IconCheck, IconClock, IconCopy, IconSearch, IconX } from "./icons";

export function Card({ title, subtitle, actions, children, className = "" }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHead({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Avatar({ name, size }: { name: string; size?: "lg" }) {
  return <span className={`avatar${size ? ` ${size}` : ""}`} aria-hidden="true">{initials(name)}</span>;
}

export function Spinner() {
  return <div className="spinner" role="status" aria-label="Loading" />;
}

export function Loading() {
  return (
    <div className="center">
      <Spinner />
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : "Something went wrong";
  return <div className="callout error" role="alert">{msg}</div>;
}

export function SearchInput({ value, onChange, placeholder, label }: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  label: string;
}) {
  return (
    <div className="search">
      <IconSearch size={15} />
      <input
        className="input"
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label={label}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function Segmented<T extends string | number>({ options, value, onChange, label }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

const STATUS_PILL: Record<string, { cls: string; label: string }> = {
  active: { cls: "pill-good", label: "Active" },
  pending: { cls: "", label: "Awaiting first event" },
  disabled: { cls: "", label: "Disabled" },
  error: { cls: "pill-critical", label: "Error" },
};

export function AccountStatus({ status }: { status: string }) {
  const s = STATUS_PILL[status] ?? { cls: "", label: status };
  return <span className={`pill ${s.cls}`}>{s.label}</span>;
}

/** Capture health always ships icon + label (never colour alone). */
export function HealthPill({ health }: { health: CaptureHealth | null }) {
  if (!health) return null;
  if (health.level === "ok")
    return (
      <span className="pill pill-good">
        <IconCheck size={13} /> Capturing
      </span>
    );
  if (health.level === "warning")
    return (
      <span className="pill pill-warning">
        <IconAlert size={13} /> Needs attention
      </span>
    );
  return (
    <span className="pill">
      <IconClock size={13} /> No data yet
    </span>
  );
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Drawer({ title, onClose, children, footer }: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <header className="drawer-head">
          <h2>{title}</h2>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-foot">{footer}</footer>}
      </aside>
    </>
  );
}

export function CopyBox({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-box">
      <code>{value}</code>
      <button
        className="btn btn-ghost btn-icon"
        aria-label="Copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard blocked */
          }
        }}
      >
        {copied ? <IconCheck /> : <IconCopy />}
      </button>
    </div>
  );
}

export function Pager({ total, limit, offset, onChange }: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total === 0) return null;
  const end = Math.min(total, offset + limit);
  return (
    <div className="table-foot">
      <span className="num">
        {offset + 1}–{end} of {total.toLocaleString()}
      </span>
      <div className="row">
        <button className="btn" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </button>
        <button className="btn" disabled={end >= total} onClick={() => onChange(offset + limit)}>
          Next
        </button>
      </div>
    </div>
  );
}

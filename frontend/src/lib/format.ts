const nf = new Intl.NumberFormat();
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

export function formatNumber(n: number): string {
  return Math.abs(n) >= 10_000 ? compact.format(n) : nf.format(n);
}

export function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}

export function formatPhone(digits: string | null | undefined): string {
  if (!digits) return "—";
  const d = digits.replace(/\D/g, "");
  // India (+91 XXXXX XXXXX) and NANP (+1 XXX XXX XXXX) get grouped; others stay plain.
  if (d.length === 12 && d.startsWith("91")) return `+91 ${d.slice(2, 7)} ${d.slice(7)}`;
  if (d.length === 11 && d.startsWith("1")) return `+1 ${d.slice(1, 4)} ${d.slice(4, 7)} ${d.slice(7)}`;
  return `+${d}`;
}

export function initials(name: string): string {
  const parts = name
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "#";
  if (/^\d/.test(parts[0])) return "#";
  return ((parts[0][0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const diff = now - new Date(iso).getTime();
  if (diff < MINUTE) return "just now";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)}d ago`;
  return formatDate(iso);
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(Date.now() - DAY);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: d.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const TYPE_LABEL: Record<string, string> = {
  image: "Photo",
  video: "Video",
  audio: "Voice message",
  document: "Document",
  sticker: "Sticker",
  location: "Location",
  contacts: "Contact card",
  reaction: "Reaction",
  interactive: "Button reply",
  button: "Button reply",
  order: "Order",
  template: "Template",
  system: "System message",
  unsupported: "Unsupported message",
};

export function messagePreview(m: { type: string; text: string | null }): string {
  if (m.type === "text") return m.text ?? "";
  const label = TYPE_LABEL[m.type] ?? m.type;
  return m.text ? `${label} · ${m.text}` : label;
}

export function typeLabel(t: string): string {
  return TYPE_LABEL[t] ?? (t === "text" ? "Text" : t);
}

export function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * DAY).toISOString();
}

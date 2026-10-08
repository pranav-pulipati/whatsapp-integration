import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Account, Conversation, Message, Paginated } from "../api/types";
import { IconArrowLeft, IconChat, IconFile, IconHistory, IconPin, Ticks } from "../components/icons";
import { Avatar, Card, Empty, ErrorNote, Loading, PageHead, SearchInput, Spinner, useDebounced } from "../components/ui";
import {
  dayLabel,
  formatBytes,
  formatDateTime,
  formatPhone,
  formatTime,
  messagePreview,
  plural,
  timeAgo,
  typeLabel,
} from "../lib/format";

const PAGE = 30;

export function ConversationsPage() {
  const { id } = useParams();
  const selectedId = id ? Number(id) : null;
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounced(q);
  const account = params.get("account") ?? "";
  const status = params.get("status") ?? "";
  const since = params.get("since") ?? "";

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  useEffect(() => setParam("q", debouncedQ), [debouncedQ]); // eslint-disable-line react-hooks/exhaustive-deps

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const filters = {
    q: debouncedQ,
    account_id: account ? Number(account) : undefined,
    status: status || undefined,
    date_from: since ? new Date(Date.now() - Number(since) * 86_400_000).toISOString() : undefined,
  };
  const list = useInfiniteQuery({
    queryKey: ["conversations", filters],
    queryFn: ({ pageParam }) =>
      api.get<Paginated<Conversation>>("/conversations", { ...filters, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.limit < last.total ? last.offset + last.limit : undefined),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;
  const keep = params.toString() ? `?${params}` : "";

  return (
    <>
      <PageHead title="Conversations" description="Every chat across all connected WhatsApp numbers." />
      <Card className={`inbox${selectedId ? " has-selection" : ""}`}>
        <div className="inbox-list">
          <div className="inbox-filters">
            <SearchInput value={q} onChange={setQ} placeholder="Search name or number" label="Search conversations" />
            <select className="select" aria-label="WhatsApp number" value={account} onChange={(e) => setParam("account", e.target.value)}>
              <option value="">All numbers</option>
              {accounts.data?.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <div className="filter-grid">
              <select className="select" aria-label="Status" value={status} onChange={(e) => setParam("status", e.target.value)}>
                <option value="">Any status</option>
                <option value="active">Active (24h)</option>
                <option value="inactive">Inactive</option>
              </select>
              <select className="select" aria-label="Activity date" value={since} onChange={(e) => setParam("since", e.target.value)}>
                <option value="">Any time</option>
                <option value="1">Active today</option>
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
              </select>
            </div>
          </div>
          <div className="conv-scroll" style={{ opacity: list.isPlaceholderData ? 0.6 : 1 }}>
            {list.error && <div style={{ padding: 12 }}><ErrorNote error={list.error} /></div>}
            {list.isLoading ? (
              <Loading />
            ) : items.length === 0 ? (
              <Empty title="No conversations">Try a different search or filter.</Empty>
            ) : (
              items.map((c) => (
                <button
                  key={c.id}
                  className="conv-item"
                  aria-current={c.id === selectedId}
                  onClick={() => navigate(`/conversations/${c.id}${keep}`)}
                >
                  <Avatar name={c.contact.display_name} />
                  <div className="body">
                    <div className="top">
                      <span className="name truncate">{c.contact.display_name}</span>
                      <span className="time">{timeAgo(c.last_message_at)}</span>
                    </div>
                    <div className="preview truncate">
                      {c.last_message?.direction === "outbound" && <span className="muted">You: </span>}
                      {c.last_message ? messagePreview(c.last_message) : "—"}
                    </div>
                    <div className="meta">
                      {c.status === "active" && <span className="dot" style={{ background: "var(--good)" }} aria-label="Active" />}
                      <span className="truncate">{c.account.name}</span>
                      <span>·</span>
                      <span className="num">{plural(c.message_count, "message")}</span>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
          <div className="list-foot">
            <span className="num">{plural(total, "conversation")}</span>
            {list.hasNextPage && (
              <button className="btn" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
                {list.isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        </div>
        {selectedId ? (
          <Thread id={selectedId} backTo={`/conversations${keep}`} />
        ) : (
          <div className="thread">
            <Empty title="Select a conversation" icon={<IconChat size={28} />}>
              Pick a chat on the left to see the full message timeline.
            </Empty>
          </div>
        )}
      </Card>
    </>
  );
}

const TIMELINE_PAGE = 100;

function Thread({ id, backTo }: { id: number; backTo: string }) {
  const conv = useQuery({ queryKey: ["conversation", id], queryFn: () => api.get<Conversation>(`/conversations/${id}`) });
  const msgs = useInfiniteQuery({
    queryKey: ["timeline", id],
    queryFn: ({ pageParam }) =>
      api.get<Paginated<Message>>(`/conversations/${id}/messages`, { order: "desc", limit: TIMELINE_PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.limit < last.total ? last.offset + last.limit : undefined),
  });
  const scroller = useRef<HTMLDivElement>(null);
  const messages = useMemo(
    () => (msgs.data?.pages.flatMap((p) => p.items) ?? []).slice().reverse(),
    [msgs.data],
  );
  const firstPageLoaded = (msgs.data?.pages.length ?? 0) === 1;
  useEffect(() => {
    if (firstPageLoaded && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [firstPageLoaded, id, messages.length]);

  const c = conv.data;
  return (
    <div className="thread">
      {c && (
        <header className="thread-head">
          <Link to={backTo} className="btn btn-ghost btn-icon" aria-label="Back to list">
            <IconArrowLeft />
          </Link>
          <Avatar name={c.contact.display_name} size="lg" />
          <div style={{ minWidth: 0 }}>
            <h2 className="truncate">{c.contact.display_name}</h2>
            <div className="sub">
              {formatPhone(c.contact.wa_id)} · via <b style={{ fontWeight: 500 }}>{c.account.name}</b> ({formatPhone(c.account.display_phone_number)})
            </div>
          </div>
          <div className="thread-stats">
            <div className="kv">Received<b className="num">{c.inbound_count}</b></div>
            <div className="kv">Sent<b className="num">{c.outbound_count}</b></div>
            <div className="kv">First contact<b>{formatDateTime(c.started_at)}</b></div>
            {c.assigned_agent && <div className="kv">Agent<b>{c.assigned_agent}</b></div>}
          </div>
        </header>
      )}
      <div className="timeline" ref={scroller}>
        {msgs.error && <ErrorNote error={msgs.error} />}
        {msgs.isLoading && <Loading />}
        {msgs.hasNextPage && (
          <div className="day-sep">
            <button className="btn" onClick={() => msgs.fetchNextPage()} disabled={msgs.isFetchingNextPage}>
              {msgs.isFetchingNextPage ? <Spinner /> : "Load earlier messages"}
            </button>
          </div>
        )}
        {messages.map((m, i) => {
          const showDay = i === 0 || dayLabel(messages[i - 1].sent_at) !== dayLabel(m.sent_at);
          return (
            <Fragment key={m.id}>
              {showDay && (
                <div className="day-sep">
                  <span>{dayLabel(m.sent_at)}</span>
                </div>
              )}
              <Bubble m={m} />
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

function statusTitle(m: Message): string {
  const parts = [m.source === "echo" ? "Sent from the WhatsApp Business App" : m.source === "history" ? "Imported from chat history" : ""];
  for (const s of m.statuses ?? []) parts.push(`${s.status[0].toUpperCase()}${s.status.slice(1)} ${formatDateTime(s.occurred_at)}`);
  return parts.filter(Boolean).join("\n");
}

function Bubble({ m }: { m: Message }) {
  const out = m.direction === "outbound";
  const failed = m.status === "failed" || m.status === "undeliverable";
  return (
    <div className={`msg ${out ? "out" : "in"}`}>
      <div className="bubble" title={statusTitle(m)}>
        {m.source === "history" && (
          <div className="tag">
            <IconHistory size={12} /> Imported history
          </div>
        )}
        {m.type !== "text" && m.type !== "reaction" && !m.media && (
          <div className="tag">{typeLabel(m.type)}</div>
        )}
        <MessageBody m={m} />
        {failed && (
          <div className="error">
            Not delivered{m.error_title ? `: ${m.error_title}` : ""}
            {m.error_code ? ` (${m.error_code})` : ""}
          </div>
        )}
        <div className="foot">
          <span>{formatTime(m.sent_at)}</span>
          {out && <Ticks status={m.status} />}
        </div>
      </div>
    </div>
  );
}

function MessageBody({ m }: { m: Message }) {
  const c = m.content ?? {};
  if (m.media) return (
    <>
      <MediaView m={m} />
      {m.text && <div className="text">{m.text}</div>}
    </>
  );
  switch (m.type) {
    case "reaction":
      return (
        <div>
          <span className="reaction">{m.text || "∅"}</span>
          <div className="muted" style={{ fontSize: 12 }}>{m.text ? "Reacted to a message" : "Removed a reaction"}</div>
        </div>
      );
    case "location": {
      const lat = Number(c.latitude);
      const lng = Number(c.longitude);
      const ok = Number.isFinite(lat) && Number.isFinite(lng);
      return (
        <div className="attachment">
          <IconPin size={18} />
          <div style={{ minWidth: 0 }}>
            <div>{c.name || "Shared location"}</div>
            {c.address && <div className="muted" style={{ fontSize: 12 }}>{c.address}</div>}
            {ok && (
              <a
                href={`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=16/${lat}/${lng}`}
                target="_blank"
                rel="noreferrer noopener"
                style={{ fontSize: 12, textDecoration: "underline" }}
              >
                Open map ({lat.toFixed(4)}, {lng.toFixed(4)})
              </a>
            )}
          </div>
        </div>
      );
    }
    case "contacts":
      return (
        <div className="stack" style={{ gap: 6 }}>
          {(c.contacts ?? []).map((card: any, i: number) => (
            <div className="attachment" key={i}>
              <Avatar name={card?.name?.formatted_name ?? "?"} />
              <div>
                <div>{card?.name?.formatted_name ?? "Contact"}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {(card?.phones ?? []).map((p: any) => p.phone).filter(Boolean).join(", ")}
                </div>
              </div>
            </div>
          ))}
        </div>
      );
    case "unsupported":
      return <div className="muted">This message type isn’t supported by WhatsApp’s API.</div>;
    default:
      return m.text ? <div className="text">{m.text}</div> : <div className="muted">{typeLabel(m.type)}</div>;
  }
}

function MediaView({ m }: { m: Message }) {
  const media = m.media!;
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const kind = (media.mime_type ?? "").split("/")[0];
  const inline = media.available && (kind === "image" || kind === "video" || kind === "audio");

  useEffect(() => {
    if (!inline) return;
    let revoked = false;
    let objectUrl: string | null = null;
    api
      .blob(`/messages/${m.id}/media`)
      .then((b) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(b);
        setUrl(objectUrl);
      })
      .catch(() => setError(true));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [m.id, inline]);

  const download = async () => {
    const b = await api.blob(`/messages/${m.id}/media`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = media.filename ?? `${m.type}-${m.id}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  if (!media.available || error) {
    const reason =
      media.download_status === "pending" ? "Downloading…" : media.download_status === "failed" ? "Couldn’t be downloaded" : "Not available";
    return (
      <div className="attachment">
        <IconFile size={18} />
        <div>
          <div>{media.filename ?? typeLabel(m.type)}</div>
          <div className="muted" style={{ fontSize: 12 }}>{reason}</div>
        </div>
      </div>
    );
  }
  if (inline && !url) return <div className="attachment"><Spinner /> Loading {typeLabel(m.type).toLowerCase()}…</div>;
  if (kind === "image") return <img className="media" src={url!} alt={m.text ?? typeLabel(m.type)} />;
  if (kind === "video") return <video className="media" src={url!} controls preload="metadata" />;
  if (kind === "audio") return <audio className="media" src={url!} controls preload="metadata" />;
  return (
    <button className="attachment btn-ghost" style={{ border: 0, width: "100%", cursor: "pointer", textAlign: "left" }} onClick={download}>
      <IconFile size={18} />
      <div style={{ minWidth: 0 }}>
        <div className="truncate">{media.filename ?? typeLabel(m.type)}</div>
        <div className="muted" style={{ fontSize: 12 }}>
          {[media.mime_type, formatBytes(media.size_bytes)].filter(Boolean).join(" · ")} · Download
        </div>
      </div>
    </button>
  );
}

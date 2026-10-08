import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Account, Contact, Conversation, Paginated } from "../api/types";
import { Avatar, Card, Drawer, Empty, ErrorNote, Loading, PageHead, Pager, SearchInput, useDebounced } from "../components/ui";
import { formatDate, formatDateTime, formatPhone, plural, timeAgo } from "../lib/format";

const LIMIT = 25;

type SortKey = "name" | "last_activity_at" | "first_seen_at";

export function ContactsPage() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q);
  const [account, setAccount] = useState("");
  const [sort, setSort] = useState<string>("-last_activity_at");
  const [offset, setOffset] = useState(0);
  const openId = params.get("id") ? Number(params.get("id")) : null;

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const contacts = useQuery({
    queryKey: ["contacts", debouncedQ, account, sort, offset],
    queryFn: () =>
      api.get<Paginated<Contact>>("/contacts", {
        q: debouncedQ,
        account_id: account || undefined,
        sort,
        limit: LIMIT,
        offset,
      }),
    placeholderData: keepPreviousData,
  });

  const sortHeader = (key: SortKey, label: string, cls = "") => {
    const active = sort.replace("-", "") === key;
    const desc = sort.startsWith("-");
    return (
      <th className={cls} aria-sort={active ? (desc ? "descending" : "ascending") : undefined}>
        <button
          className="sort-btn"
          aria-sort={active ? (desc ? "descending" : "ascending") : undefined}
          onClick={() => {
            setOffset(0);
            setSort(active && desc ? key : `-${key}`);
          }}
        >
          {label} {active ? (desc ? "↓" : "↑") : ""}
        </button>
      </th>
    );
  };

  const open = (id: number | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("id", String(id));
    else next.delete("id");
    setParams(next, { replace: true });
  };

  const data = contacts.data;
  return (
    <>
      <PageHead title="Contacts" description="Everyone who has chatted with any of your WhatsApp numbers." />
      <div className="filters">
        <SearchInput
          value={q}
          onChange={(v) => {
            setOffset(0);
            setQ(v);
          }}
          placeholder="Search name or number"
          label="Search contacts"
        />
        <select
          className="select"
          aria-label="WhatsApp number"
          value={account}
          onChange={(e) => {
            setOffset(0);
            setAccount(e.target.value);
          }}
        >
          <option value="">All numbers</option>
          {accounts.data?.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>
      {contacts.error && <ErrorNote error={contacts.error} />}
      <Card>
        {!data ? (
          <Loading />
        ) : data.total === 0 ? (
          <Empty title="No contacts found">Contacts appear automatically when customers message one of your numbers.</Empty>
        ) : (
          <div className="table-wrap" style={{ opacity: contacts.isPlaceholderData ? 0.6 : 1 }}>
            <table className="table">
              <thead>
                <tr>
                  {sortHeader("name", "Contact")}
                  <th>WhatsApp numbers</th>
                  <th className="num">Conversations</th>
                  <th className="num">Messages</th>
                  {sortHeader("first_seen_at", "First activity")}
                  {sortHeader("last_activity_at", "Latest activity")}
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => open(c.id)}>
                    <td>
                      <div className="who-cell">
                        <Avatar name={c.display_name} />
                        <div>
                          <div className="primary truncate">{c.display_name}</div>
                          <div className="sub num">{formatPhone(c.wa_id)}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="row" style={{ flexWrap: "wrap", gap: 4 }}>
                        {c.accounts.map((a) => (
                          <span className="pill" key={a.id}>{a.name}</span>
                        ))}
                      </div>
                    </td>
                    <td className="num">{c.conversations}</td>
                    <td className="num">{c.messages.toLocaleString()}</td>
                    <td className="secondary">{formatDate(c.first_seen_at)}</td>
                    <td className="secondary">{timeAgo(c.last_activity_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        )}
      </Card>
      {openId && <ContactDrawer id={openId} onClose={() => open(null)} />}
    </>
  );
}

function ContactDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const contact = useQuery({ queryKey: ["contact", id], queryFn: () => api.get<Contact>(`/contacts/${id}`) });
  const convs = useQuery({
    queryKey: ["contact-conversations", id],
    queryFn: () => api.get<Paginated<Conversation>>("/conversations", { contact_id: id, limit: 50 }),
  });
  const c = contact.data;
  return (
    <Drawer title="Contact" onClose={onClose}>
      {!c ? (
        <Loading />
      ) : (
        <>
          <div className="who-cell">
            <Avatar name={c.display_name} size="lg" />
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{c.display_name}</div>
              <div className="muted num">{formatPhone(c.wa_id)}</div>
            </div>
          </div>
          <dl className="dl">
            <dt>WhatsApp profile name</dt>
            <dd>{c.name ?? "—"}</dd>
            <dt>Saved as (Business App)</dt>
            <dd>{c.saved_name ?? "—"}</dd>
            <dt>WhatsApp ID</dt>
            <dd className="mono">{c.wa_id}</dd>
            <dt>First activity</dt>
            <dd>{formatDateTime(c.first_seen_at)}</dd>
            <dt>Latest activity</dt>
            <dd>{formatDateTime(c.last_activity_at)}</dd>
            <dt>Messages</dt>
            <dd className="num">{c.messages.toLocaleString()}</dd>
          </dl>
          <div>
            <div className="section-title">Conversations</div>
            <div className="card">
              {convs.data?.items.map((cv) => (
                <Link key={cv.id} to={`/conversations/${cv.id}`} className="health-row" style={{ gridTemplateColumns: "1fr auto" }}>
                  <div>
                    <div style={{ fontWeight: 500 }}>{cv.account.name}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {plural(cv.message_count, "message")} · last {timeAgo(cv.last_message_at)}
                    </div>
                  </div>
                  <span className={`pill ${cv.status === "active" ? "pill-good" : ""}`}>
                    {cv.status === "active" ? "Active" : "Inactive"}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </>
      )}
    </Drawer>
  );
}

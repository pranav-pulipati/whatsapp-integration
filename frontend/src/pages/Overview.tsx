import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Account, Overview as OverviewData, TimeseriesPoint } from "../api/types";
import { LineChart, StackedBars, type Series } from "../components/charts";
import { Card, Empty, ErrorNote, HealthPill, Loading, PageHead, Segmented } from "../components/ui";
import { formatNumber, formatPhone, plural, timeAgo } from "../lib/format";

const RANGES = [
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
];

const MESSAGE_SERIES: Series[] = [
  { key: "inbound", label: "From customers", color: "var(--series-in)" },
  { key: "outbound", label: "From sales team", color: "var(--series-out)" },
];
const CONVERSATION_SERIES: Series[] = [
  { key: "conversations", label: "Conversations with activity", color: "var(--series-single)" },
];

const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

function useRangeParams() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get("days")) || 30;
  const account = params.get("account") ? Number(params.get("account")) : null;
  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)));
    setParams(next, { replace: true });
  };
  return { days, account, update };
}

export function OverviewPage() {
  const { days, account, update } = useRangeParams();
  const range = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - days * 86_400_000);
    from.setHours(0, 0, 0, 0);
    return { date_from: from.toISOString(), date_to: to.toISOString() };
  }, [days]);

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const overview = useQuery({
    queryKey: ["overview", range, account],
    queryFn: () => api.get<OverviewData>("/analytics/overview", { ...range, account_id: account }),
    placeholderData: keepPreviousData,
  });
  const series = useQuery({
    queryKey: ["timeseries", range, account],
    queryFn: () => api.get<TimeseriesPoint[]>("/analytics/timeseries", { ...range, account_id: account, tz }),
    placeholderData: keepPreviousData,
  });

  const selected = accounts.data?.find((a) => a.id === account);
  const o = overview.data;

  return (
    <>
      <PageHead
        title="Overview"
        description={`${selected ? selected.name : "All WhatsApp numbers"} · last ${days} days`}
      />
      <div className="filters">
        <Segmented label="Date range" options={RANGES} value={days} onChange={(d) => update({ days: String(d) })} />
        <select
          className="select"
          aria-label="WhatsApp number"
          value={account ?? ""}
          onChange={(e) => update({ account: e.target.value || null })}
        >
          <option value="">All numbers</option>
          {accounts.data?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {formatPhone(a.display_phone_number)}
            </option>
          ))}
        </select>
      </div>

      {overview.error && <ErrorNote error={overview.error} />}
      {!o ? (
        <Loading />
      ) : o.accounts === 0 ? (
        <Card>
          <Empty title="No WhatsApp numbers connected yet">
            Connect your first number on the <Link to="/numbers" className="secondary" style={{ textDecoration: "underline" }}>Numbers</Link> page.
            Messages appear here as soon as 360dialog starts sending webhooks.
          </Empty>
        </Card>
      ) : (
        <div className="stack">
          <div className="grid grid-4">
            <MessagesTile inbound={o.inbound_in_range} outbound={o.outbound_in_range} />
            <Stat label="Active conversations" value={o.active_conversations} sub={`Messages in the last 24 hours · ${formatNumber(o.conversations)} total`} />
            <Stat label="Conversations with activity" value={o.conversations_in_range} sub={`In the selected ${days} days`} />
            <Stat label="New contacts" value={o.new_contacts_in_range} sub={`${formatNumber(o.contacts)} contacts in total`} />
          </div>

          <div className="grid grid-2">
            <Card title="Messages per day" subtitle="Customer messages vs replies sent from the WhatsApp Business App">
              <div className="card-body">
                <LineChart data={series.data ?? []} series={MESSAGE_SERIES} refreshing={series.isPlaceholderData} caption="Messages per day" />
              </div>
            </Card>
            <Card title="Activity by number" subtitle="Messages in range">
              <div className="card-body">
                <StackedBars
                  caption="Messages by WhatsApp number"
                  series={MESSAGE_SERIES}
                  rows={[...o.by_account]
                    .sort((a, b) => b.inbound + b.outbound - (a.inbound + a.outbound))
                    .map((r) => ({
                      key: r.account.id,
                      label: r.account.name,
                      sub: plural(r.conversations, "conversation"),
                      values: { inbound: r.inbound, outbound: r.outbound },
                    }))}
                />
              </div>
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Conversations with activity per day">
              <div className="card-body">
                <LineChart
                  data={series.data ?? []}
                  series={CONVERSATION_SERIES}
                  area
                  height={180}
                  refreshing={series.isPlaceholderData}
                  caption="Conversations with activity per day"
                />
              </div>
            </Card>
            <CaptureHealthCard accounts={accounts.data ?? []} />
          </div>
        </div>
      )}
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{formatNumber(value)}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

function MessagesTile({ inbound, outbound }: { inbound: number; outbound: number }) {
  const total = inbound + outbound;
  return (
    <div className="card stat">
      <div className="stat-label">Messages</div>
      <div className="stat-value">{formatNumber(total)}</div>
      <div className="split" aria-hidden="true">
        {total > 0 && (
          <>
            <span style={{ flex: inbound, background: "var(--series-in)" }} />
            <span style={{ flex: outbound, background: "var(--series-out)" }} />
          </>
        )}
      </div>
      <div className="stat-sub legend" style={{ marginTop: 8 }}>
        <span>
          <i className="key-rect" style={{ background: "var(--series-in)" }} />
          {formatNumber(inbound)} received
        </span>
        <span>
          <i className="key-rect" style={{ background: "var(--series-out)" }} />
          {formatNumber(outbound)} sent
        </span>
      </div>
    </div>
  );
}

function CaptureHealthCard({ accounts }: { accounts: Account[] }) {
  return (
    <Card title="Capture health" subtitle="Are customer messages and app-sent replies arriving for every number?">
      <div style={{ paddingTop: 8 }}>
        {accounts.map((a) => (
          <Link to={`/numbers?id=${a.id}`} key={a.id} className="health-row" style={{ gridTemplateColumns: "1fr auto" }}>
            <div style={{ minWidth: 0 }}>
              <div className="truncate" style={{ fontWeight: 500 }}>{a.name}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                Last customer message {timeAgo(a.health?.last_inbound_at)} · last app reply {timeAgo(a.health?.last_echo_at)}
              </div>
            </div>
            <HealthPill health={a.health} />
          </Link>
        ))}
      </div>
    </Card>
  );
}

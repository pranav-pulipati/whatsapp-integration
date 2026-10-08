import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Account, OpsSummary, Paginated, WebhookEvent } from "../api/types";
import { IconRefresh } from "../components/icons";
import { Card, Empty, ErrorNote, Loading, PageHead, Pager, Segmented } from "../components/ui";
import { formatDateTime, formatNumber, timeAgo } from "../lib/format";

const STATUSES = [
  { value: "dead", label: "Failed" },
  { value: "retry", label: "Retrying" },
  { value: "pending", label: "Queued" },
  { value: "ignored", label: "Ignored" },
  { value: "processed", label: "Processed" },
];
const LIMIT = 25;

export function OpsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("dead");
  const [offset, setOffset] = useState(0);
  const summary = useQuery({
    queryKey: ["ops-summary"],
    queryFn: () => api.get<OpsSummary>("/ops/summary"),
    refetchInterval: 15_000,
  });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const events = useQuery({
    queryKey: ["ops-events", status, offset],
    queryFn: () => api.get<Paginated<WebhookEvent>>("/ops/webhook-events", { status, limit: LIMIT, offset }),
    placeholderData: keepPreviousData,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ops-summary"] });
    qc.invalidateQueries({ queryKey: ["ops-events"] });
  };
  const retry = useMutation({ mutationFn: (id: number) => api.post(`/ops/webhook-events/${id}/retry`), onSuccess: refresh });
  const retryAll = useMutation({ mutationFn: () => api.post("/ops/retry-failed"), onSuccess: refresh });
  const accountName = (id: number | null) => accounts.data?.find((a) => a.id === id)?.name ?? "—";

  const s = summary.data;
  const failed = (s?.events.dead ?? 0) + (s?.media.failed ?? 0);
  return (
    <>
      <PageHead
        title="Ingestion"
        description="Webhook queue health. Events are stored before processing, so nothing is lost when processing fails."
        actions={
          <button className="btn" onClick={() => retryAll.mutate()} disabled={!failed || retryAll.isPending}>
            <IconRefresh /> Retry all failed
          </button>
        }
      />
      {s && (
        <div className="grid grid-4" style={{ marginBottom: 16 }}>
          <Tile label="Processed events" value={s.events.processed ?? 0} />
          <Tile label="Queued / retrying" value={(s.events.pending ?? 0) + (s.events.retry ?? 0)} sub={s.oldest_pending_event_at ? `Oldest ${timeAgo(s.oldest_pending_event_at)}` : "Queue is empty"} />
          <Tile label="Failed events" value={s.events.dead ?? 0} sub="Need a fix or a retry" />
          <Tile label="Media files stored" value={s.media.downloaded ?? 0} sub={`${formatNumber(s.media.pending ?? 0)} pending · ${formatNumber(s.media.failed ?? 0)} failed`} />
        </div>
      )}
      <div className="filters">
        <Segmented label="Event status" options={STATUSES} value={status} onChange={(v) => { setOffset(0); setStatus(v); }} />
      </div>
      {events.error && <ErrorNote error={events.error} />}
      <Card>
        {!events.data ? (
          <Loading />
        ) : events.data.total === 0 ? (
          <Empty title="Nothing here">No events with this status.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Number</th>
                  <th>Kind</th>
                  <th className="num">Attempts</th>
                  <th>Received</th>
                  <th>Error</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {events.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="mono">#{e.id}</td>
                    <td>{accountName(e.account_id)}</td>
                    <td>
                      <span className="pill">{e.event_kind ?? "unknown"}</span>
                      {e.source === "history_import" && <span className="pill" style={{ marginLeft: 4 }}>history</span>}
                    </td>
                    <td className="num">{e.attempts}</td>
                    <td className="secondary">{formatDateTime(e.received_at)}</td>
                    <td className="secondary" style={{ maxWidth: 360, fontSize: 12 }}>{e.last_error ?? "—"}</td>
                    <td className="r">
                      {(e.status === "dead" || e.status === "ignored") && (
                        <button className="btn" onClick={() => retry.mutate(e.id)} disabled={retry.isPending}>Retry</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={events.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        )}
      </Card>
    </>
  );
}

function Tile({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{formatNumber(value)}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

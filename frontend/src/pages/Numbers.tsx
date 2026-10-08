import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Account, WebhookInfo } from "../api/types";
import { IconAlert, IconPlus } from "../components/icons";
import { AccountStatus, Card, CopyBox, Drawer, Empty, ErrorNote, HealthPill, Loading, PageHead } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDateTime, formatNumber, formatPhone, timeAgo } from "../lib/format";

export function NumbersPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const openId = params.get("id") ? Number(params.get("id")) : null;
  const open = (id: number | null) => setParams(id ? { id: String(id) } : {}, { replace: true });
  const selected = accounts.data?.find((a) => a.id === openId);

  return (
    <>
      <PageHead
        title="WhatsApp numbers"
        description="Every connected number. Add more at any time — no code changes needed."
        actions={
          isAdmin && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              <IconPlus /> Connect number
            </button>
          )
        }
      />
      {accounts.error && <ErrorNote error={accounts.error} />}
      {!accounts.data ? (
        <Loading />
      ) : accounts.data.length === 0 ? (
        <Card>
          <Empty title="No numbers yet">
            Connect your first WhatsApp Business number. You’ll need its 360dialog API key (Hub → Channels → API key).
          </Empty>
        </Card>
      ) : (
        <div className="accounts-grid">
          {accounts.data.map((a) => (
            <button key={a.id} className="card account-card" onClick={() => open(a.id)}>
              <div className="row" style={{ alignItems: "flex-start" }}>
                <div style={{ minWidth: 0 }}>
                  <h3 className="truncate">{a.name}</h3>
                  <div className="muted num">{formatPhone(a.display_phone_number)}</div>
                </div>
                <span className="spacer" />
                <HealthPill health={a.health} />
              </div>
              <div className="metrics">
                <div>
                  <b>{formatNumber(a.contacts)}</b>contacts
                </div>
                <div>
                  <b>{formatNumber(a.conversations)}</b>conversations
                </div>
                <div>
                  <b>{formatNumber(a.messages_7d)}</b>messages · 7d
                </div>
              </div>
              <div className="row muted" style={{ fontSize: 12 }}>
                <AccountStatus status={a.status} />
                <span className="spacer" />
                Last event {timeAgo(a.health?.last_event_at)}
              </div>
            </button>
          ))}
        </div>
      )}
      {selected && <AccountDrawer account={selected} isAdmin={isAdmin} onClose={() => open(null)} />}
      {creating && <CreateDrawer onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); open(id); }} />}
    </>
  );
}

function AccountDrawer({ account: a, isAdmin, onClose }: { account: Account; isAdmin: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const webhook = useQuery({
    queryKey: ["webhook", a.id],
    queryFn: () => api.get<WebhookInfo>(`/accounts/${a.id}/webhook`),
    enabled: isAdmin,
  });
  const register = useMutation({
    mutationFn: () => api.post<WebhookInfo>(`/accounts/${a.id}/register-webhook`),
  });
  const [apiKey, setApiKey] = useState("");
  const saveKey = useMutation({
    mutationFn: () => api.put(`/accounts/${a.id}/api-key`, { api_key: apiKey }),
    onSuccess: () => {
      setApiKey("");
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
  const toggle = useMutation({
    mutationFn: () => api.patch<Account>(`/accounts/${a.id}`, { status: a.status === "disabled" ? "active" : "disabled" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const h = a.health;

  return (
    <Drawer
      title={a.name}
      onClose={onClose}
      footer={
        isAdmin && (
          <button className="btn" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
            {a.status === "disabled" ? "Re-enable number" : "Disable number"}
          </button>
        )
      }
    >
      <div className="row">
        <AccountStatus status={a.status} />
        <HealthPill health={h} />
      </div>

      {h && h.reasons.length > 0 && (
        <div className={`callout ${h.level === "warning" ? "warning" : ""}`}>
          <ul className="reasons" style={{ margin: 0, color: "inherit" }}>
            {h.reasons.map((r) => (
              <li key={r} className="row" style={{ alignItems: "flex-start" }}>
                <IconAlert size={14} style={{ marginTop: 2, flex: "none" }} /> {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <div className="section-title">Capture · last 7 days</div>
        <div className="metrics" style={{ borderTop: 0, paddingTop: 0 }}>
          <div>
            <b>{formatNumber(h?.inbound_7d ?? 0)}</b>customer messages
          </div>
          <div>
            <b>{formatNumber(h?.echoes_7d ?? 0)}</b>app-sent replies
          </div>
          <div>
            <b>{formatNumber(h?.orphan_statuses_7d ?? 0)}</b>unmatched statuses
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Replies typed in the WhatsApp Business App arrive as <span className="mono">smb_message_echoes</span>. An
          unmatched status means WhatsApp reported delivery of a message whose content never reached us.
        </p>
      </div>

      <div>
        <div className="section-title">Details</div>
        <dl className="dl">
          <dt>Number</dt>
          <dd className="num">{formatPhone(a.display_phone_number)}</dd>
          <dt>Provider</dt>
          <dd>{a.provider}</dd>
          <dt>Phone number ID</dt>
          <dd className="mono">{a.phone_number_id ?? "Learned from first event"}</dd>
          <dt>WABA ID</dt>
          <dd className="mono">{a.waba_id ?? "—"}</dd>
          <dt>API key</dt>
          <dd>{a.has_api_key ? "Stored (encrypted)" : "Missing — media can’t be downloaded"}</dd>
          <dt>Last customer message</dt>
          <dd>{h?.last_inbound_at ? formatDateTime(h.last_inbound_at) : "—"}</dd>
          <dt>Last app-sent reply</dt>
          <dd>{h?.last_echo_at ? formatDateTime(h.last_echo_at) : "—"}</dd>
          <dt>Totals</dt>
          <dd className="num">
            {formatNumber(a.messages)} messages · {formatNumber(a.conversations)} conversations · {formatNumber(a.contacts)} contacts
          </dd>
        </dl>
      </div>

      {isAdmin && (
        <>
          <div>
            <div className="section-title">Webhook</div>
            {webhook.data && <CopyBox value={webhook.data.webhook_url} />}
            <p className="muted" style={{ fontSize: 12, margin: "8px 0" }}>
              Registering sets this URL on 360dialog together with the <span className="mono">{webhook.data?.secret_header}</span> secret header.
            </p>
            <button className="btn" onClick={() => register.mutate()} disabled={register.isPending || !a.has_api_key}>
              {register.isPending ? "Registering…" : "Register webhook with 360dialog"}
            </button>
            {register.isSuccess && <div className="callout" style={{ marginTop: 8 }}>Webhook registered. Send a test message to this number.</div>}
            {register.error && <div style={{ marginTop: 8 }}><ErrorNote error={register.error} /></div>}
          </div>
          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              saveKey.mutate();
            }}
          >
            <div className="section-title">{a.has_api_key ? "Rotate API key" : "Set API key"}</div>
            <div className="row">
              <input
                className="input"
                style={{ flex: 1 }}
                type="password"
                autoComplete="off"
                placeholder="360dialog D360-API-KEY"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                aria-label="360dialog API key"
              />
              <button className="btn" disabled={apiKey.length < 8 || saveKey.isPending}>Save</button>
            </div>
            {saveKey.isSuccess && <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>Saved.</p>}
            {saveKey.error && <ErrorNote error={saveKey.error} />}
          </form>
        </>
      )}
    </Drawer>
  );
}

function CreateDrawer({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", display_phone_number: "", api_key: "", phone_number_id: "", waba_id: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const create = useMutation({
    mutationFn: () =>
      api.post<Account>("/accounts", {
        name: form.name,
        display_phone_number: form.display_phone_number,
        api_key: form.api_key || null,
        phone_number_id: form.phone_number_id || null,
        waba_id: form.waba_id || null,
      }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      onCreated(a.id);
    },
  });
  return (
    <Drawer
      title="Connect a WhatsApp number"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" form="create-account" disabled={create.isPending}>
            {create.isPending ? "Connecting…" : "Connect number"}
          </button>
        </>
      }
    >
      <p className="secondary">
        Onboard the number in the 360dialog Hub first (coexistence, so the team keeps using the WhatsApp Business App), then
        enter its details here.
      </p>
      <form
        id="create-account"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div className="field">
          <label htmlFor="f-name">Name</label>
          <input id="f-name" className="input" required value={form.name} onChange={set("name")} placeholder="Sales — Bengaluru" />
        </div>
        <div className="field">
          <label htmlFor="f-number">WhatsApp number</label>
          <input id="f-number" className="input" required value={form.display_phone_number} onChange={set("display_phone_number")} placeholder="+91 98765 43210" inputMode="tel" />
          <span className="hint">International format with country code.</span>
        </div>
        <div className="field">
          <label htmlFor="f-key">360dialog API key</label>
          <input id="f-key" className="input" type="password" autoComplete="off" value={form.api_key} onChange={set("api_key")} />
          <span className="hint">Hub → Channels → this number → API key. Stored encrypted; needed for media and webhook setup.</span>
        </div>
        <div className="field">
          <label htmlFor="f-pnid">Phone number ID <span className="muted">(optional)</span></label>
          <input id="f-pnid" className="input" value={form.phone_number_id} onChange={set("phone_number_id")} />
          <span className="hint">Learned automatically from the first webhook if left empty.</span>
        </div>
        <div className="field">
          <label htmlFor="f-waba">WABA ID <span className="muted">(optional)</span></label>
          <input id="f-waba" className="input" value={form.waba_id} onChange={set("waba_id")} />
        </div>
        {create.error && <ErrorNote error={create.error} />}
      </form>
    </Drawer>
  );
}

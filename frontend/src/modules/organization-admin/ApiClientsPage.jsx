import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Check, Copy, Loader2 } from "lucide-react";
import { getStoredUser } from "../../service/api";
import ConfirmDialog from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { Badge, Banner, NotAvailable, Tabs, actionError, card, danger, input, primary, subtle } from "../../components/SecurityUi";
import { API_CLIENT_MAX_DAYS, WEBHOOK_EVENTS, isUnavailable, securityTenant as svc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// API Clients & Webhooks (ZP-PRIV D06). Secrets (client credential, webhook
// signing secret) are returned once by the server and shown once here: they
// live only in the one-time modal's state, are dropped when it closes, and
// are never logged or written to browser storage.
const STATUS_BADGE = {
  active: "bg-emerald-100 text-emerald-800",
  expired: "bg-slate-200 text-slate-700",
  revoked: "bg-red-100 text-red-800",
  disabled: "bg-slate-200 text-slate-700",
};

function OneTimeSecretModal({ title, label, value, onClose }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <Modal title={title} onClose={onClose} maxWidth="max-w-xl">
      <div className="space-y-4 text-sm">
        <Banner tone="warning">
          Copy this {label} now and store it in your secrets manager. You won&apos;t see it again — Zoiko keeps only a
          one-way hash. If it is lost, rotate it.
        </Banner>
        <div className="flex items-start gap-2">
          <code className="flex-1 break-all rounded-lg border border-border-light bg-surface-muted p-3 font-mono text-xs text-foreground">{value}</code>
          <button type="button" className={subtle} onClick={copy} aria-label={`Copy ${label}`}>
            {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />} {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <div className="flex justify-end">
          <button type="button" className={primary} onClick={onClose}>I have stored it</button>
        </div>
      </div>
    </Modal>
  );
}

function CreateClientDialog({ scopes, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState(new Set());
  const [days, setDays] = useState(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const validDays = Number.isInteger(Number(days)) && Number(days) >= 1 && Number(days) <= API_CLIENT_MAX_DAYS;

  function toggle(scope) {
    const next = new Set(chosen);
    if (next.has(scope)) next.delete(scope);
    else next.add(scope);
    setChosen(next);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await svc.createApiClient({ name: name.trim(), scopes: [...chosen], expiresInDays: Number(days) });
      onCreated(res);
    } catch (err) {
      setError(actionError(err, "The API client could not be created."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New API client" onClose={onClose} maxWidth="max-w-xl">
      <div className="space-y-4 text-sm">
        <label className="block space-y-1">
          <span className="font-medium text-foreground">Name</span>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. HRIS sync" />
        </label>
        <fieldset className="space-y-2">
          <legend className="font-medium text-foreground">Scopes (least privilege — no wildcards)</legend>
          {scopes.map((s) => (
            <label key={s.scope} className="flex items-start gap-2 text-foreground">
              <input type="checkbox" className="mt-1" checked={chosen.has(s.scope)} onChange={() => toggle(s.scope)} />
              <span>
                <span className="font-mono text-xs">{s.scope}</span>
                <span className="block text-xs text-foreground-secondary">
                  {(s.routes || []).join(", ")}{(s.fieldClasses || []).length ? ` · fields: ${s.fieldClasses.join(", ")}` : ""}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        <label className="block space-y-1">
          <span className="font-medium text-foreground">Expires in (days, 1–{API_CLIENT_MAX_DAYS})</span>
          <input className={input} type="number" min={1} max={API_CLIENT_MAX_DAYS} value={days} onChange={(e) => setDays(e.target.value)} />
        </label>
        <p className="text-xs text-foreground-secondary">You will be asked for a fresh verification code.</p>
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} onClick={submit} disabled={busy || !name.trim() || chosen.size === 0 || !validDays}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Create client
          </button>
        </div>
      </div>
    </Modal>
  );
}

function CreateWebhookDialog({ onClose, onCreated }) {
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const httpsOk = /^https:\/\/\S+$/.test(url.trim());

  function toggle(ev) {
    const next = new Set(events);
    if (next.has(ev)) next.delete(ev);
    else next.add(ev);
    setEvents(next);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      onCreated(await svc.createWebhook({ url: url.trim(), events: [...events] }));
    } catch (err) {
      setError(actionError(err, "The webhook could not be registered."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New webhook" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <label className="block space-y-1">
          <span className="font-medium text-foreground">Endpoint URL (https only)</span>
          <input className={input} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/zoiko-webhook" />
          {url && !httpsOk && <span className="text-xs text-red-600">The URL must start with https://</span>}
        </label>
        <fieldset className="space-y-1">
          <legend className="font-medium text-foreground">Events</legend>
          {WEBHOOK_EVENTS.map((ev) => (
            <label key={ev} className="flex items-center gap-2 text-foreground">
              <input type="checkbox" checked={events.has(ev)} onChange={() => toggle(ev)} /> <span className="font-mono text-xs">{ev}</span>
            </label>
          ))}
        </fieldset>
        <p className="text-xs text-foreground-secondary">You will be asked for a fresh verification code.</p>
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} onClick={submit} disabled={busy || !httpsOk || events.size === 0}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Register webhook
          </button>
        </div>
      </div>
    </Modal>
  );
}

function ClientsTab({ onSecret }) {
  const [rows, setRows] = useState(null);
  const [scopes, setScopes] = useState([]);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [creating, setCreating] = useState(false);
  const [confirm, setConfirm] = useState(null);

  const load = useCallback(async () => {
    try {
      setRows(await svc.apiClients());
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load API clients.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    svc.apiScopes().then(setScopes).catch(() => setScopes([]));
  }, [load]);

  async function runConfirmed() {
    const { kind, client } = confirm;
    setConfirm(null);
    setError(null);
    try {
      if (kind === "rotate") {
        const res = await svc.rotateApiClient(client.id);
        onSecret({ title: `New secret for ${res.name}`, label: "client credential", value: res.credential });
      } else {
        await svc.revokeApiClient(client.id);
      }
      await load();
    } catch (err) {
      setError(actionError(err));
    }
  }

  if (unavailable) return <NotAvailable what="API clients" />;
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button type="button" className={primary} onClick={() => setCreating(true)} disabled={!scopes.length}>New API client</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <div className={`${card} overflow-x-auto`}>
        {!rows ? <p className="text-sm text-foreground-secondary">Loading…</p> : rows.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No API clients yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr><th className="py-2 pr-3">Client</th><th className="pr-3">Scopes</th><th className="pr-3">Status</th>
                <th className="pr-3">Last used</th><th className="pr-3">Expires</th><th><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {rows.map((c) => (
                <tr key={c.id}>
                  <td className="py-2 pr-3">
                    {c.name}
                    <span className="block text-xs text-foreground-secondary">
                      Created {formatDateTime(c.createdAt)}{c.rotatedAt ? ` · rotated ${formatDateTime(c.rotatedAt)}` : ""}
                    </span>
                  </td>
                  <td className="pr-3 font-mono text-xs">{(c.scopes || []).join(", ")}</td>
                  <td className="pr-3"><Badge className={STATUS_BADGE[c.status] || ""}>{c.status}</Badge></td>
                  <td className="pr-3 whitespace-nowrap">{c.lastUsedAt ? formatDateTime(c.lastUsedAt) : "Never"}</td>
                  <td className="pr-3 whitespace-nowrap">{c.revokedAt ? `Revoked ${formatDateTime(c.revokedAt)}` : formatDateTime(c.expiresAt)}</td>
                  <td className="whitespace-nowrap">
                    {c.status !== "revoked" && (
                      <span className="flex gap-2">
                        <button type="button" className={subtle} onClick={() => setConfirm({ kind: "rotate", client: c })}>Rotate</button>
                        <button type="button" className={danger} onClick={() => setConfirm({ kind: "revoke", client: c })}>Revoke</button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {creating && (
        <CreateClientDialog scopes={scopes} onClose={() => setCreating(false)}
          onCreated={(res) => {
            setCreating(false);
            onSecret({ title: `API client "${res.name}" created`, label: "client credential", value: res.credential });
            load();
          }} />
      )}
      {confirm && (
        <ConfirmDialog
          title={confirm.kind === "rotate" ? "Rotate this client's secret?" : "Revoke this client now?"}
          message={confirm.kind === "rotate"
            ? `The current secret for "${confirm.client.name}" stops working immediately and a new one is shown once.`
            : `"${confirm.client.name}" stops working immediately. This cannot be undone.`}
          confirmLabel={confirm.kind === "rotate" ? "Rotate" : "Revoke"}
          onConfirm={runConfirmed}
          onClose={() => setConfirm(null)}
        />
      )}
    </div>
  );
}

function WebhooksTab({ onSecret }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      setRows(await svc.webhooks());
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load webhooks.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function disable(id) {
    setBusy(id);
    try {
      await svc.disableWebhook(id);
      await load();
    } catch (err) {
      setError(actionError(err));
    } finally {
      setBusy(null);
    }
  }

  if (unavailable) return <NotAvailable what="Webhooks" />;
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button type="button" className={primary} onClick={() => setCreating(true)}>New webhook</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <div className={`${card} overflow-x-auto`}>
        {!rows ? <p className="text-sm text-foreground-secondary">Loading…</p> : rows.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No webhooks registered.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr><th className="py-2 pr-3">URL</th><th className="pr-3">Events</th><th className="pr-3">Status</th>
                <th className="pr-3">Created</th><th><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {rows.map((w) => (
                <tr key={w.id}>
                  <td className="py-2 pr-3 break-all">{w.url}</td>
                  <td className="pr-3 font-mono text-xs">{(w.events || []).join(", ")}</td>
                  <td className="pr-3"><Badge className={STATUS_BADGE[w.status] || "bg-emerald-100 text-emerald-800"}>{w.status}</Badge></td>
                  <td className="pr-3 whitespace-nowrap">{formatDateTime(w.createdAt)}</td>
                  <td>
                    {w.status !== "disabled" && (
                      <button type="button" className={subtle} disabled={busy === w.id} onClick={() => disable(w.id)}>Disable</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {creating && (
        <CreateWebhookDialog onClose={() => setCreating(false)}
          onCreated={(res) => {
            setCreating(false);
            onSecret({ title: "Webhook registered", label: "signing secret", value: res.signingSecret });
            load();
          }} />
      )}
    </div>
  );
}

export default function ApiClientsPage() {
  const role = getStoredUser()?.role;
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "webhooks" ? "webhooks" : "clients";
  // The one-time secret lives here only while its modal is open.
  const [secret, setSecret] = useState(null);

  if (role !== "org_admin") {
    return <div className="p-4 sm:p-6"><NotAvailable what="API clients" /></div>;
  }

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">API Clients & Webhooks</h1>
        <p className="text-sm text-foreground-secondary">
          Machine access to your organization: narrowly scoped, expiring API clients and signed outbound webhooks.
        </p>
      </div>
      <Tabs tabs={[{ key: "clients", label: "API clients" }, { key: "webhooks", label: "Webhooks" }]} value={tab}
        onChange={(key) => setParams((p) => { p.set("tab", key); return p; })} />
      {tab === "clients" ? <ClientsTab onSecret={setSecret} /> : <WebhooksTab onSecret={setSecret} />}
      {secret?.value && (
        <OneTimeSecretModal title={secret.title} label={secret.label} value={secret.value} onClose={() => setSecret(null)} />
      )}
    </div>
  );
}

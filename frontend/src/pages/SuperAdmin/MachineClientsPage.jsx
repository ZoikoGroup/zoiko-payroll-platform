import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getStoredUser } from "../../api/client";
import { Badge, Banner, NotAvailable, card, input, subtle } from "../../components/SecurityUi";
import { isUnavailable, securityPlatform as svc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// Machine client inventory (ZP-PRIV D06): metadata only - no secrets and no
// scope details. Organizations create, rotate and revoke their own clients.
const READERS = ["super_admin", "platform_security"];
const STATUS_BADGE = {
  active: "bg-emerald-100 text-emerald-800",
  expired: "bg-slate-200 text-slate-700",
  revoked: "bg-red-100 text-red-800",
};

export default function MachineClientsPage() {
  const role = getStoredUser()?.role;
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [status, setStatus] = useState("");
  const [org, setOrg] = useState("");

  const load = useCallback(async () => {
    try {
      setRows(await svc.machineClients());
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load machine clients.");
    }
  }, []);

  useEffect(() => {
    if (!READERS.includes(role)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, role]);

  if (!READERS.includes(role) || unavailable) {
    return <div className="p-4 sm:p-6"><NotAvailable what="The machine client inventory" /></div>;
  }

  const needle = org.trim().toLowerCase();
  const shown = (rows || []).filter((c) => (!status || c.status === status) &&
    (!needle || (c.organizationCode || "").toLowerCase().includes(needle)));

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Machine Clients</h1>
          <p className="text-sm text-foreground-secondary">
            Every API client across organizations. Inventory only: secrets are never stored in readable form or shown here.
          </p>
        </div>
        <button type="button" className={subtle} onClick={load}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <div className="flex flex-wrap gap-3">
        <input className={`${input} max-w-xs`} placeholder="Organization code" value={org} onChange={(e) => setOrg(e.target.value)} aria-label="Organization code" />
        <select className={`${input} max-w-[12rem]`} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">Any status</option>
          <option value="active">active</option>
          <option value="expired">expired</option>
          <option value="revoked">revoked</option>
        </select>
      </div>
      <div className={`${card} overflow-x-auto`}>
        {!rows ? <p className="text-sm text-foreground-secondary">Loading…</p> : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr><th className="py-2 pr-3">Client</th><th className="pr-3">Organization</th><th className="pr-3">Scopes</th>
                <th className="pr-3">Status</th><th className="pr-3">Created</th><th className="pr-3">Last used</th>
                <th className="pr-3">Rotated</th><th>Expires / revoked</th></tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {shown.map((c) => (
                <tr key={c.id}>
                  <td className="py-2 pr-3">#{c.id} · {c.name}</td>
                  <td className="pr-3">{c.organizationCode || (c.organizationId ? `#${c.organizationId}` : "—")}</td>
                  <td className="pr-3">{c.scopeCount}</td>
                  <td className="pr-3"><Badge className={STATUS_BADGE[c.status] || ""}>{c.status}</Badge></td>
                  <td className="pr-3 whitespace-nowrap">{formatDateTime(c.createdAt)}</td>
                  <td className="pr-3 whitespace-nowrap">{c.lastUsedAt ? formatDateTime(c.lastUsedAt) : "Never"}</td>
                  <td className="pr-3 whitespace-nowrap">{c.rotatedAt ? formatDateTime(c.rotatedAt) : "—"}</td>
                  <td className="whitespace-nowrap">{c.revokedAt ? `Revoked ${formatDateTime(c.revokedAt)}` : formatDateTime(c.expiresAt)}</td>
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={8} className="py-2 text-foreground-secondary">No machine clients.</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

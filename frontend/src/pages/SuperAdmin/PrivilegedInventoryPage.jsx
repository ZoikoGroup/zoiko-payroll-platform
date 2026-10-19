import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getStoredUser } from "../../api/client";
import { Badge, Banner, NotAvailable, card, subtle } from "../../components/SecurityUi";
import { isUnavailable, securityPlatform as svc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// Privileged access inventory (ZP-PRIV E04): every privileged human, machine
// client and live / emergency support grant. Tenant admins are listed by id
// and organization code only - their account is never shown here.
const READERS = ["super_admin", "platform_security"];
const STATUS_BADGE = {
  active: "bg-emerald-100 text-emerald-800",
  expired: "bg-slate-200 text-slate-700",
  revoked: "bg-red-100 text-red-800",
  pending_approval: "bg-blue-100 text-blue-800",
};

function Stat({ label, value, warn }) {
  return (
    <div className={`${card} min-w-[150px] ${warn ? "border-red-300" : ""}`}>
      <p className={`text-2xl font-bold leading-none ${warn ? "text-red-600" : "text-foreground"}`}>{value ?? "—"}</p>
      <p className="mt-1 text-xs text-foreground-secondary">{label}</p>
    </div>
  );
}

export default function PrivilegedInventoryPage() {
  const role = getStoredUser()?.role;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [onlyNoMfa, setOnlyNoMfa] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await svc.privilegedInventory());
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load the inventory.");
    }
  }, []);

  useEffect(() => {
    if (!READERS.includes(role)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, role]);

  if (!READERS.includes(role) || unavailable) {
    return <div className="p-4 sm:p-6"><NotAvailable what="The privileged inventory" /></div>;
  }

  const s = data?.summary || {};
  const humans = (data?.humans || []).filter((h) => !onlyNoMfa || (!h.mfaEnrolled && h.isActive));

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Privileged Inventory</h1>
          <p className="text-sm text-foreground-secondary">
            Who can do privileged things right now: platform staff, organization admins, machine clients and support grants.
            {data?.generatedAt ? ` Generated ${formatDateTime(data.generatedAt)}.` : ""}
          </p>
        </div>
        <button type="button" className={subtle} onClick={load}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {!data ? <p className="text-sm text-foreground-secondary">Loading…</p> : (
        <>
          <div className="flex flex-wrap gap-3">
            <Stat label="Platform staff" value={s.platformHumans} />
            <Stat label="Organization admins" value={s.tenantAdmins} />
            <Stat label="Active accounts without MFA" value={s.withoutMfa} warn={s.withoutMfa > 0} />
            <Stat label="Machine clients" value={s.machineClients} />
            <Stat label="Live support grants" value={s.liveGrants} />
            <Stat label="Emergency grants awaiting review" value={s.emergencyGrantsAwaitingReview} warn={s.emergencyGrantsAwaitingReview > 0} />
          </div>
          {s.withoutMfa > 0 && (
            <Banner tone="warning">
              {s.withoutMfa} active privileged account(s) have no confirmed MFA. They are highlighted below.
            </Banner>
          )}

          <section className={`${card} space-y-3 overflow-x-auto`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-foreground">Privileged people</h2>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input type="checkbox" checked={onlyNoMfa} onChange={(e) => setOnlyNoMfa(e.target.checked)} /> Only without MFA
              </label>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="text-foreground-secondary">
                <tr><th className="py-2 pr-3">User</th><th className="pr-3">Role</th><th className="pr-3">Plane</th>
                  <th className="pr-3">Account</th><th className="pr-3">Organization</th><th className="pr-3">Active</th>
                  <th className="pr-3">MFA</th><th>Last login</th></tr>
              </thead>
              <tbody className="divide-y divide-border-light text-foreground">
                {humans.map((h) => {
                  const noMfa = !h.mfaEnrolled && h.isActive;
                  return (
                    <tr key={h.userId} className={noMfa ? "bg-red-50 dark:bg-red-900/20" : ""}>
                      <td className="py-2 pr-3">#{h.userId}</td>
                      <td className="pr-3">{h.role}</td>
                      <td className="pr-3">{h.plane}</td>
                      <td className="pr-3">{h.account ?? <span className="text-foreground-secondary">tenant account (hidden)</span>}</td>
                      <td className="pr-3">{h.organizationCode || "—"}</td>
                      <td className="pr-3">{h.isActive ? "Yes" : "No"}</td>
                      <td className="pr-3">
                        {h.mfaEnrolled
                          ? <Badge className="bg-emerald-100 text-emerald-800">Enrolled</Badge>
                          : <Badge className="bg-red-100 text-red-800">No MFA</Badge>}
                      </td>
                      <td className="whitespace-nowrap">{h.lastLogin ? formatDateTime(h.lastLogin) : "Never"}</td>
                    </tr>
                  );
                })}
                {humans.length === 0 && <tr><td colSpan={8} className="py-2 text-foreground-secondary">Nobody to show.</td></tr>}
              </tbody>
            </table>
          </section>

          <section className={`${card} space-y-3 overflow-x-auto`}>
            <h2 className="text-lg font-semibold text-foreground">Machine clients</h2>
            <table className="w-full text-left text-sm">
              <thead className="text-foreground-secondary">
                <tr><th className="py-2 pr-3">Client</th><th className="pr-3">Organization</th><th className="pr-3">Scopes</th>
                  <th className="pr-3">Status</th><th className="pr-3">Last used</th><th>Expires</th></tr>
              </thead>
              <tbody className="divide-y divide-border-light text-foreground">
                {(data.machineClients || []).map((c) => (
                  <tr key={c.id}>
                    <td className="py-2 pr-3">#{c.id} · {c.name}</td>
                    <td className="pr-3">{c.organizationCode || "—"}</td>
                    <td className="pr-3">{(c.scopes || []).join(", ") || "—"}</td>
                    <td className="pr-3"><Badge className={STATUS_BADGE[c.status] || ""}>{c.status}</Badge></td>
                    <td className="pr-3 whitespace-nowrap">{c.lastUsedAt ? formatDateTime(c.lastUsedAt) : "Never"}</td>
                    <td className="whitespace-nowrap">{formatDateTime(c.expiresAt)}</td>
                  </tr>
                ))}
                {(data.machineClients || []).length === 0 && <tr><td colSpan={6} className="py-2 text-foreground-secondary">No machine clients.</td></tr>}
              </tbody>
            </table>
          </section>

          <section className={`${card} space-y-3 overflow-x-auto`}>
            <h2 className="text-lg font-semibold text-foreground">Live and emergency support grants</h2>
            <table className="w-full text-left text-sm">
              <thead className="text-foreground-secondary">
                <tr><th className="py-2 pr-3">Grant</th><th className="pr-3">Organization</th><th className="pr-3">Status</th>
                  <th className="pr-3">Scope</th><th className="pr-3">Requested by</th><th className="pr-3">Expires</th><th>Review</th></tr>
              </thead>
              <tbody className="divide-y divide-border-light text-foreground">
                {(data.grants || []).map((g) => (
                  <tr key={g.grantId} className={g.isBreakGlass && !g.reviewed ? "bg-amber-50 dark:bg-amber-900/20" : ""}>
                    <td className="py-2 pr-3">#{g.grantId}{g.isBreakGlass ? " · emergency" : ""}</td>
                    <td className="pr-3">{g.organizationCode || "—"}</td>
                    <td className="pr-3"><Badge className={STATUS_BADGE[g.status] || "bg-slate-200 text-slate-700"}>{g.status.replaceAll("_", " ")}</Badge></td>
                    <td className="pr-3">{g.scopeType}</td>
                    <td className="pr-3">#{g.requestedByUserId}</td>
                    <td className="pr-3 whitespace-nowrap">{formatDateTime(g.expiresAt)}</td>
                    <td className="whitespace-nowrap">
                      {g.isBreakGlass ? (g.reviewed ? "Reviewed" : `Due ${formatDateTime(g.reviewDueAt)}`) : "—"}
                    </td>
                  </tr>
                ))}
                {(data.grants || []).length === 0 && <tr><td colSpan={7} className="py-2 text-foreground-secondary">No live grants.</td></tr>}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { getStoredUser } from "../../service/api";
import Modal from "../../components/Modal";
import { Badge, Banner, NotAvailable, actionError, card, input, primary, subtle } from "../../components/SecurityUi";
import { DSAR_TYPES, isUnavailable, securityTenant as svc } from "../../service/securityService";
import { getEmployees } from "../../service/payrollService";
import { formatDateTime } from "../../utils/time";

// Data Region & Retention (ZP-PRIV F02/F03): where your data lives, how long
// it is kept, legal holds (four-eyes release) and data-subject requests.
const HOLD_BADGE = { active: "bg-amber-100 text-amber-800", released: "bg-slate-200 text-slate-700" };
const REQUEST_BADGE = { received: "bg-blue-100 text-blue-800", completed: "bg-emerald-100 text-emerald-800" };

function EmployeePicker({ employees, value, onChange, allowNone }) {
  if (!employees.length) {
    return (
      <input className={input} type="number" min={1} placeholder={allowNone ? "Employee id (blank = whole organization)" : "Employee id"}
        value={value} onChange={(e) => onChange(e.target.value)} aria-label="Employee id" />
    );
  }
  return (
    <select className={input} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Employee">
      <option value="">{allowNone ? "Whole organization" : "Choose an employee"}</option>
      {employees.map((e) => <option key={e.id} value={e.id}>{e.name}{e.employeeCode ? ` · ${e.employeeCode}` : ""}</option>)}
    </select>
  );
}

function TextDialog({ title, label, note, action, required = true, onSubmit, onClose }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-3 text-sm">
        {note && <Banner tone="info">{note}</Banner>}
        <textarea className={input} rows={3} placeholder={label} value={text} onChange={(e) => setText(e.target.value)} />
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} disabled={busy || (required && !text.trim())}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onSubmit(text.trim());
                onClose();
              } catch (err) {
                setError(actionError(err));
              } finally {
                setBusy(false);
              }
            }}>
            {action}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function DataGovernancePage() {
  const me = getStoredUser();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [employees, setEmployees] = useState([]);
  const [hold, setHold] = useState({ employeeId: "", reason: "", reference: "" });
  const [request, setRequest] = useState({ requestType: "access", employeeId: "" });
  const [releasing, setReleasing] = useState(null);
  const [completing, setCompleting] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await svc.dataGovernance());
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load data governance.");
    }
  }, []);

  useEffect(() => {
    if (me?.role !== "org_admin") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    getEmployees({ limit: 500 }).then(setEmployees).catch(() => setEmployees([]));
  }, [load, me?.role]);

  const nameOf = useMemo(() => {
    const map = new Map(employees.map((e) => [e.id, e.name]));
    return (id) => (id == null ? "Whole organization" : map.get(id) || `Employee #${id}`);
  }, [employees]);

  if (me?.role !== "org_admin" || unavailable) {
    return <div className="p-4 sm:p-6"><NotAvailable what="Data region and retention" /></div>;
  }

  async function run(fn, msg) {
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(msg);
      await load();
    } catch (err) {
      setError(actionError(err));
    }
  }

  const toId = (v) => (v === "" || v == null ? null : Number(v));

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Data Region & Retention</h1>
        <p className="text-sm text-foreground-secondary">
          Where your organization&apos;s data lives, how long it is kept, legal holds and data-subject requests.
        </p>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {notice && <Banner tone="success">{notice}</Banner>}
      {!data ? <p className="text-sm text-foreground-secondary">Loading…</p> : (
        <>
          <div className="grid gap-5 lg:grid-cols-2">
            <section className={`${card} space-y-2`}>
              <h2 className="text-lg font-semibold text-foreground">Data region</h2>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div><dt className="text-xs text-foreground-secondary">Your data region</dt><dd className="font-medium text-foreground">{data.dataRegion || "—"}</dd></div>
                <div><dt className="text-xs text-foreground-secondary">This deployment</dt><dd className="text-foreground">{data.deploymentRegion || "—"}</dd></div>
                <div className="sm:col-span-2"><dt className="text-xs text-foreground-secondary">Supported regions</dt><dd className="text-foreground">{(data.supportedRegions || []).join(", ")}</dd></div>
              </dl>
              {data.regionPolicy && <p className="text-sm text-foreground-secondary">{data.regionPolicy}</p>}
            </section>
            <section className={`${card} space-y-2`}>
              <h2 className="text-lg font-semibold text-foreground">Retention</h2>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div><dt className="text-xs text-foreground-secondary">Worker data after leaving</dt><dd className="font-medium text-foreground">{data.retention?.workerDataYearsAfterLeaving ?? "—"} years</dd></div>
                <div><dt className="text-xs text-foreground-secondary">Audit records</dt><dd className="font-medium text-foreground">{data.retention?.auditYears ?? "—"} years</dd></div>
              </dl>
              <p className="text-xs text-foreground-secondary">A legal hold pauses deletion for the people it covers until it is released.</p>
            </section>
          </div>

          <section className={`${card} space-y-3`}>
            <h2 className="text-lg font-semibold text-foreground">Legal holds</h2>
            <div className="grid gap-3 sm:grid-cols-4">
              <EmployeePicker employees={employees} allowNone value={hold.employeeId} onChange={(v) => setHold({ ...hold, employeeId: v })} />
              <input className={input} placeholder="Reason (required)" value={hold.reason} onChange={(e) => setHold({ ...hold, reason: e.target.value })} />
              <input className={input} placeholder="Reference (optional)" value={hold.reference} onChange={(e) => setHold({ ...hold, reference: e.target.value })} />
              <button type="button" className={primary} disabled={!hold.reason.trim()}
                onClick={() => run(async () => {
                  await svc.placeHold({ employeeId: toId(hold.employeeId), reason: hold.reason.trim(), reference: hold.reference.trim() || undefined });
                  setHold({ employeeId: "", reason: "", reference: "" });
                }, "Legal hold placed.")}>
                Place hold
              </button>
            </div>
            <p className="text-xs text-foreground-secondary">A hold must be released by a different administrator from the one who placed it.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-foreground-secondary">
                  <tr><th className="py-2 pr-3">Covers</th><th className="pr-3">Status</th><th className="pr-3">Reason</th>
                    <th className="pr-3">Placed</th><th className="pr-3">Released</th><th><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody className="divide-y divide-border-light text-foreground">
                  {(data.legalHolds || []).map((h) => (
                    <tr key={h.id}>
                      <td className="py-2 pr-3">{nameOf(h.employeeId)}{h.scope ? <span className="text-foreground-secondary"> · {h.scope}</span> : null}</td>
                      <td className="pr-3"><Badge className={HOLD_BADGE[h.status] || "bg-slate-200 text-slate-700"}>{h.status}</Badge></td>
                      <td className="pr-3">{h.reason}{h.reference ? <span className="text-foreground-secondary"> ({h.reference})</span> : null}</td>
                      <td className="pr-3 whitespace-nowrap">{formatDateTime(h.placedAt)}{h.placedBy === me?.id ? " · by you" : ""}</td>
                      <td className="pr-3 whitespace-nowrap">{h.releasedAt ? formatDateTime(h.releasedAt) : "—"}</td>
                      <td>
                        {h.status === "active" && (
                          <button type="button" className={subtle} disabled={h.placedBy === me?.id}
                            title={h.placedBy === me?.id ? "A different administrator must release this hold" : undefined}
                            onClick={() => setReleasing(h)}>
                            Release
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(data.legalHolds || []).length === 0 && <tr><td colSpan={6} className="py-2 text-foreground-secondary">No legal holds.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className={`${card} space-y-3`}>
            <h2 className="text-lg font-semibold text-foreground">Data-subject requests</h2>
            <div className="grid gap-3 sm:grid-cols-3">
              <select className={input} value={request.requestType} onChange={(e) => setRequest({ ...request, requestType: e.target.value })} aria-label="Request type">
                {DSAR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <EmployeePicker employees={employees} value={request.employeeId} onChange={(v) => setRequest({ ...request, employeeId: v })} />
              <button type="button" className={primary} disabled={!request.employeeId}
                onClick={() => run(async () => {
                  await svc.createRequest({ requestType: request.requestType, employeeId: toId(request.employeeId) });
                  setRequest({ requestType: "access", employeeId: "" });
                }, "Request recorded.")}>
                Record request
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-foreground-secondary">
                  <tr><th className="py-2 pr-3">Type</th><th className="pr-3">Employee</th><th className="pr-3">Status</th>
                    <th className="pr-3">Received</th><th className="pr-3">Due</th><th className="pr-3">Outcome</th><th><span className="sr-only">Actions</span></th></tr>
                </thead>
                <tbody className="divide-y divide-border-light text-foreground">
                  {(data.requests || []).map((r) => (
                    <tr key={r.id}>
                      <td className="py-2 pr-3">{r.requestType}</td>
                      <td className="pr-3">{nameOf(r.employeeId)}</td>
                      <td className="pr-3"><Badge className={REQUEST_BADGE[r.status] || "bg-slate-200 text-slate-700"}>{r.status}</Badge></td>
                      <td className="pr-3 whitespace-nowrap">{formatDateTime(r.receivedAt)}</td>
                      <td className="pr-3 whitespace-nowrap">{formatDateTime(r.dueAt)}</td>
                      <td className="pr-3">{r.completedAt ? `${formatDateTime(r.completedAt)}${r.outcome ? ` · ${r.outcome}` : ""}` : "—"}</td>
                      <td>
                        {r.status !== "completed" && (
                          <button type="button" className={subtle} onClick={() => setCompleting(r)}>Complete</button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(data.requests || []).length === 0 && <tr><td colSpan={7} className="py-2 text-foreground-secondary">No requests.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {releasing && (
        <TextDialog title="Release legal hold" label="Reason (required)" action="Release hold"
          note="A different administrator from the one who placed the hold must release it (four-eyes)."
          onClose={() => setReleasing(null)}
          onSubmit={async (reason) => { await svc.releaseHold(releasing.id, reason); setNotice("Legal hold released."); await load(); }} />
      )}
      {completing && (
        <TextDialog title={`Complete ${completing.requestType} request`} label="Outcome (optional)" action="Mark complete" required={false}
          note={completing.requestType === "erasure" ? "An erasure cannot be completed while a legal hold covers this employee." : null}
          onClose={() => setCompleting(null)}
          onSubmit={async (outcome) => { await svc.completeRequest(completing.id, outcome); setNotice("Request completed."); await load(); }} />
      )}
    </div>
  );
}

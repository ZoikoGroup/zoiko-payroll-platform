import { useCallback, useEffect, useState } from "react";
import {
  getHkEmpfFilingView, grantHkMpfReveal, listHkMpfRevealHolders, revealHkMpfAccount, revokeHkMpfReveal,
} from "../../../service/payrollService";
import { listOrgUsers } from "../../../service/orgAdminService";

// Hong Kong MPF member account access (G5 finding F-1). The API returns the
// account masked (last 4). The full number is read only by a user holding the
// HK_MPF_ACCOUNT_REVEAL permission, with a stated purpose; the server refuses
// otherwise and logs every read and refusal in the HK access log. These
// controls only route the request — they are not the security boundary.
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-2 py-1 text-[11px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";

function usePurposeAction() {
  const [purpose, setPurpose] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function run(fn) {
    setError(null); setBusy(true);
    try { return await fn(purpose.trim()); } catch (e) { setError(e?.message || "Refused."); return null; } finally { setBusy(false); }
  }
  return { purpose, setPurpose, error, busy, run };
}

export function MpfAccountReveal({ employeeId }) {
  const a = usePurposeAction();
  const [value, setValue] = useState(null);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Reveal MPF member account">
      <input className={input} aria-label="Purpose of reading the full MPF account" placeholder="Purpose (e.g. eMPF filing for 2026-05)"
        value={a.purpose} onChange={(e) => a.setPurpose(e.target.value)} />
      <button type="button" className={btn} disabled={a.busy || !a.purpose.trim()}
        onClick={async () => { const r = await a.run((p) => revealHkMpfAccount(employeeId, p)); if (r) setValue(r.mpfMemberAccount); }}>
        Reveal full MPF account (logged)
      </button>
      {value && <span className="font-mono text-[12px] text-foreground">{value}</span>}
      {a.error && <span role="alert" className="text-[12px] text-error">{a.error}</span>}
    </div>
  );
}

export function EmpfFilingView({ submissionId }) {
  const a = usePurposeAction();
  const [view, setView] = useState(null);
  return (
    <div className="mt-2 space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <input className={input} aria-label={`Purpose for eMPF filing view #${submissionId}`} placeholder="Purpose (filing on the eMPF platform)"
          value={a.purpose} onChange={(e) => a.setPurpose(e.target.value)} />
        <button type="button" className={btn} disabled={a.busy || !a.purpose.trim()}
          onClick={async () => { const r = await a.run((p) => getHkEmpfFilingView(submissionId, p)); if (r) setView(r); }}>
          Filing view with full accounts (logged)
        </button>
        {view && <button type="button" className={btn} onClick={() => setView(null)}>Hide</button>}
      </div>
      {a.error && <p role="alert" className="text-[12px] text-error">{a.error}</p>}
      {view && (
        <table className="w-full text-[12px]" aria-label={`eMPF filing rows #${submissionId}`}>
          <thead><tr><th className="text-left">Payslip</th><th className="text-left">Member account</th><th className="text-left">Relevant income</th><th className="text-left">Employer</th><th className="text-left">Employee</th></tr></thead>
          <tbody>
            {view.rows.map((r) => (
              <tr key={r.payslipId}><td>#{r.payslipId}</td><td className="font-mono">{r.memberAccount || "—"}</td><td>{r.relevantIncome}</td><td>{r.employerMandatory}</td><td>{r.employeeMandatory}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function MpfRevealPermissions() {
  const [holders, setHolders] = useState([]);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ userId: "", reason: "" });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const load = useCallback(() => {
    listHkMpfRevealHolders().then(setHolders).catch(() => setHolders([]));
    listOrgUsers().then((r) => setUsers(Array.isArray(r) ? r : r?.data || r?.users || [])).catch(() => setUsers([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  const who = (id) => { const u = users.find((x) => x.id === id); return u ? `${u.first_name || u.firstName || ""} ${u.last_name || u.lastName || ""} <${u.email}>` : `#${id}`; };
  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); load(); } catch (e) { setError(e?.message || "Refused."); }
  }
  const active = holders.filter((h) => !h.revokedAt);
  return (
    <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="hk-mpf-perm">
      <h3 id="hk-mpf-perm" className="mb-1 text-[14px] font-semibold text-foreground">MPF account access (HK_MPF_ACCOUNT_REVEAL)</h3>
      <p className="mb-2 text-[12px] text-foreground-secondary">
        MPF member accounts are masked everywhere. Grant full-number access only to users who file with the trustee / eMPF.
        Only an organisation admin can grant it, never to themselves; every grant, revoke and read is logged.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[12px] text-success">{notice}</p>}
      <ul className="mb-2 space-y-1 text-[12px]">
        {active.length === 0 && <li className="text-foreground-muted">Nobody holds this permission.</li>}
        {active.map((h) => (
          <li key={h.id} className="flex flex-wrap items-center gap-2">
            <span>{who(h.userId)} — {h.reason}</span>
            <button type="button" className={btn} onClick={() => act(() => revokeHkMpfReveal(h.userId, "revoked by org admin"), "Access revoked.")}>Revoke</button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <select className={input} aria-label="User to grant MPF account access" value={form.userId} onChange={(e) => setForm({ ...form, userId: e.target.value })}>
          <option value="">Select user…</option>
          {users.map((u) => <option key={u.id} value={u.id}>{who(u.id)}</option>)}
        </select>
        <input className={input} aria-label="Reason for granting MPF account access" placeholder="Reason (e.g. eMPF filing duty)"
          value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <button type="button" className={btn} disabled={!form.userId || !form.reason.trim()}
          onClick={() => act(() => grantHkMpfReveal(Number(form.userId), form.reason.trim()), "Access granted.")}>Grant</button>
      </div>
    </section>
  );
}

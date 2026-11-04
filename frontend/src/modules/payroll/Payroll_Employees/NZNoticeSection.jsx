import { useState } from "react";
import { approveNzNotice, importNzNotice, listNzNotices, revokeNzNotice } from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import {
  NOTICE_ISSUERS, NOTICE_TYPES, PROTECTED_POLICIES, errorText, period,
} from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Authority deduction notices (spec §5, NZ-010): child support, student-loan
// extra, IRD deduction notices, court attachments. The notice FILE is hashed
// and never stored; a change is a new version; a second user approves.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const FIELDS = [
  ["deduction_type", "Type *", NOTICE_TYPES], ["notice_id", "Notice id *"], ["issuer", "Issuer *", NOTICE_ISSUERS],
  ["received_at", "Received *", "datetime"], ["effective_from", "Effective from *", "date"],
  ["effective_to", "Effective to", "date"], ["amount_per_payday", "Amount per payday"], ["rate_pct", "Rate %"],
  ["protected_earnings_policy", "Protected earnings *", PROTECTED_POLICIES],
  ["protected_earnings_amount", "Protected amount (court)"], ["reason_code", "Reason code"],
  ["evidence_ref", "Evidence reference"],
];

export default function NZNoticeSection({ employeeId }) {
  const [rows, loadError, loading, reload] = useLoad(() => listNzNotices(employeeId));
  const [values, setValues] = useState({});
  const [file, setFile] = useState(null);
  const [fileKey, setFileKey] = useState(0);
  const [state, setState] = useState({ busy: false, error: null, notice: null });

  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload();
    } catch (e) {
      setState({ busy: false, error: errorText(e), notice: null });
    }
  };

  const submit = (e) => {
    e.preventDefault();
    const meta = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "" && v != null));
    run(async () => {
      await importNzNotice(employeeId, file, meta);
      setValues({});
      setFile(null);
      setFileKey((k) => k + 1);
    }, "Notice imported (hash only) — a second user must approve it.");
  };

  const revoke = (row) => {
    const reason = window.prompt("Why is this notice being revoked?");
    if (reason && reason.trim()) run(() => revokeNzNotice(row.id, reason.trim()), "Notice revoked.");
  };

  return (
    <section className={card} data-testid="nz-notices">
      <h3 className="text-[14px] font-semibold text-foreground">Authority deduction notices</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Only the notice&apos;s SHA-256 is kept, never its contents. Child support is taken after the tax deductions and
        never beyond the protected-net share.
      </p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No authority notices."
          columns={[
            { label: "Type", key: "deduction_type" }, { label: "Notice", render: (r) => `${r.notice_id} v${r.version}` },
            { label: "In force", render: period },
            { label: "Per payday", render: (r) => r.amount_per_payday ?? (r.rate_pct != null ? `${r.rate_pct}%` : "—") },
            { label: "File hash", render: (r) => <span className="font-mono text-[10px]">{String(r.file_hash || "").slice(0, 12)}…</span> },
            { label: "Status", key: "status" },
            { label: "Actions", render: (r) => (
              <div className="flex gap-1">
                {r.status === "IMPORTED" && (
                  <button type="button" className={btn} disabled={state.busy}
                    onClick={() => run(() => approveNzNotice(r.id), "Notice approved.")}>Approve</button>
                )}
                {r.status === "APPROVED" && (
                  <button type="button" className={btn} disabled={state.busy} onClick={() => revoke(r)}>Revoke</button>
                )}
              </div>
            ) },
          ]} />
      )}
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Import a notice">
        <label className={labelCls}>
          Notice file *
          <input key={fileKey} className={input} type="file" required onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        {FIELDS.map(([key, label, kind]) => (
          <label key={key} className={labelCls}>
            {label}
            {Array.isArray(kind) ? (
              <select className={input} value={values[key] ?? ""} onChange={(e) => setValues({ ...values, [key]: e.target.value })}>
                <option value="">—</option>
                {kind.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input className={input} type={kind === "date" ? "date" : kind === "datetime" ? "datetime-local" : "text"}
                value={values[key] ?? ""} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
            )}
          </label>
        ))}
        <div className="flex items-end">
          <button type="submit" className={btn} disabled={state.busy || !file}>Import notice</button>
        </div>
      </form>
    </section>
  );
}

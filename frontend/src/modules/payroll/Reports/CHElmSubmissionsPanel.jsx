import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Loader2, Send, Inbox, XCircle } from "lucide-react";
import { buildSwissElmSubmissions, listSwissElmSubmissions, transitionSwissElmSubmission, transmitSwissElmSubmission } from "../../../service/payrollService";
import { CH_ELM_DOMAINS } from "../../../components/jurisdiction/switzerland/chComponentConfig";

// Switzerland ELM (electronic salary statement for the cantonal authorities)
// — filing-side view embedded in the Swiss Employer Profile tab. Envelopes
// come ONLY from COMMITTED payslips; building never opens a network call
// (transport stays NOT_SENT until you transmit, which the backend refuses
// while CH_ELM_TRANSMIT_ENABLED=False). Authority RECEIVE/REJECT is recorded
// manually here — a rejection never touches payroll.

const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";

function todayYear() {
  return new Date().getFullYear();
}

function StatusChip({ value }) {
  const tone = ["VALID", "SENT", "ACCEPTED", "SETTLED", "RECEIVED", "OK"].includes(value)
    ? "bg-primary/10 text-primary"
    : ["REJECTED", "ERROR", "FAILED"].includes(value)
    ? "bg-error/10 text-error"
    : "bg-foreground-muted/10 text-foreground-muted";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${tone}`}>{value || "—"}</span>;
}

function ElmRow({ sub, onChanged, busy }) {
  const [showPayload, setShowPayload] = useState(false);
  const [receipt, setReceipt] = useState("");
  const [reason, setReason] = useState("");
  const [acting, setActing] = useState("");
  const [rowError, setRowError] = useState(null);

  async function act(action) {
    setActing(action); setRowError(null);
    try {
      if (action === "RECEIVE") await transitionSwissElmSubmission(sub.submissionId, { action: "RECEIVE", receiptReference: receipt.trim() || null });
      if (action === "REJECT") await transitionSwissElmSubmission(sub.submissionId, { action: "REJECT", reason: reason.trim() });
      if (action === "TRANSMIT") await transmitSwissElmSubmission(sub.submissionId);
      onChanged();
    } catch (e) {
      setRowError(e?.message || "Action failed.");
    } finally {
      setActing("");
    }
  }

  const notSent = sub.transportStatus === "NOT_SENT" || sub.transportStatus === "RECEIVED";

  return (
    <div className="px-3 py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setShowPayload((s) => !s)} className="inline-flex items-center gap-1 text-[12px] font-bold text-foreground">
          {showPayload ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          {sub.domain} · {sub.periodKey}
        </button>
        <span className="text-[11px] text-foreground-muted">receiver {sub.receiverId}</span>
        <span className="text-[11px] text-foreground-muted">canton {sub.canton || "—"}</span>
        {sub.correctionOfId && <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-bold text-warning">correction of #{sub.correctionOfId}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-foreground-muted">
        <span>transport <StatusChip value={sub.transportStatus} /></span>
        <span>validation <StatusChip value={sub.receiverValidationStatus} /></span>
        <span>ack <StatusChip value={sub.authorityAckStatus} /></span>
        <span>settlement <StatusChip value={sub.settlementStatus} /></span>
      </div>
      {sub.receiptReference && <p className="text-[11px] text-foreground-muted">Receipt: <span className="font-mono">{sub.receiptReference}</span></p>}
      {sub.rejectionDetail && <p className="text-[11px] text-error">Rejected: {sub.rejectionDetail}</p>}
      {rowError && <p className="text-[11px] font-medium text-error">{rowError}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => act("TRANSMIT")} disabled={busy || acting !== "" || !notSent}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] font-bold text-foreground-muted hover:text-foreground disabled:opacity-40" title="Transmit envelope to the authority (refused server-side while transmit is disabled)">
          <Send size={12} /> {acting === "TRANSMIT" ? <Loader2 size={12} className="animate-spin" /> : "Transmit"}
        </button>
        <input className={`${input} w-40 py-1.5`} value={receipt} onChange={(e) => setReceipt(e.target.value)} placeholder="Receipt reference" />
        <button type="button" onClick={() => act("RECEIVE")} disabled={busy || acting !== "" || !receipt.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 px-3 py-1.5 text-[11px] font-bold text-primary hover:bg-primary/20 disabled:opacity-40">
          <Inbox size={12} /> {acting === "RECEIVE" ? <Loader2 size={12} className="animate-spin" /> : "Receive"}
        </button>
        <input className={`${input} w-40 py-1.5`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Rejection reason (required)" />
        <button type="button" onClick={() => act("REJECT")} disabled={busy || acting !== "" || !reason.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-error/10 px-3 py-1.5 text-[11px] font-bold text-error hover:bg-error/20 disabled:opacity-40">
          <XCircle size={12} /> {acting === "REJECT" ? <Loader2 size={12} className="animate-spin" /> : "Reject"}
        </button>
      </div>
      {showPayload && sub.payload && (
        <pre className="max-h-48 overflow-auto rounded-lg bg-muted/50 border border-border p-3 text-[10px] leading-relaxed text-foreground-muted whitespace-pre-wrap">
          {sub.payload}
        </pre>
      )}
    </div>
  );
}

export default function CHElmSubmissionsPanel() {
  const [year, setYear] = useState(String(todayYear()));
  const [month, setMonth] = useState("");
  const [domain, setDomain] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState(null);
  const [list, setList] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [transmitEnabled, setTransmitEnabled] = useState(null);

  const fetchList = () => {
    setListLoading(true);
    listSwissElmSubmissions()
      .then((rows) => setList(Array.isArray(rows) ? rows : []))
      .catch((e) => setListError(e?.message || "Failed to list ELM submissions."))
      .finally(() => setListLoading(false));
  };

  useEffect(() => { fetchList(); }, []);

  async function build() {
    setBuilding(true); setBuildMsg(null);
    try {
      const res = await buildSwissElmSubmissions({
        year: Number(year),
        month: month ? Number(month) : null,
        domain: domain || null,
      });
      setTransmitEnabled(res?.transmitEnabled ?? null);
      const subs = res?.submissions || [];
      setBuildMsg(`Built ${subs.length} envelope${subs.length === 1 ? "" : "s"} for ${res?.periodKey}.`);
      setList(subs);
    } catch (e) {
      setBuildMsg(null);
      setListError(e?.message || "Failed to build ELM submissions.");
    } finally {
      setBuilding(false);
    }
  }

  return (
    <div className="bg-surface border border-border rounded-[18px] p-5 space-y-4">
      <div>
        <h3 className="text-[15px] font-bold text-foreground">ELM submissions</h3>
        <p className="mt-1 text-[12px] text-foreground-muted">
          Electronic salary statements for the cantonal authorities, built from committed Swiss payslips for a period.
          Building is idempotent and sends nothing; transmit to the authority is a separate, refused-while-disabled step.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="ch-elm-year" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Year</label>
          <input id="ch-elm-year" className={`${input} mt-1.5 w-24`} inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} />
        </div>
        <div>
          <label htmlFor="ch-elm-month" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Month (optional)</label>
          <select id="ch-elm-month" className={`${input} mt-1.5 w-28`} value={month} onChange={(e) => setMonth(e.target.value)}>
            <option value="">Whole year</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="ch-elm-domain" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Domain (optional)</label>
          <select id="ch-elm-domain" className={`${input} mt-1.5 w-28`} value={domain} onChange={(e) => setDomain(e.target.value)}>
            <option value="">All domains</option>
            {CH_ELM_DOMAINS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <button type="button" onClick={build} disabled={building || !year}
          className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
          {building ? <Loader2 size={14} className="inline animate-spin" /> : "Build ELM submissions"}
        </button>
      </div>

      {transmitEnabled !== null && (
        <p className="text-[11px] text-foreground-muted">
          Authority transmission is {transmitEnabled ? "enabled" : "DISABLED on this platform"} — envelopes hold at NOT_SENT until a transmit succeeds.
        </p>
      )}
      {buildMsg && <p role="status" className="text-[12px] font-medium text-primary">{buildMsg}</p>}
      {listError && <p role="alert" className="text-[12px] font-medium text-error">{listError}</p>}

      <div className="overflow-hidden rounded-xl border border-border">
        {listLoading ? (
          <p className="flex items-center gap-2 px-4 py-6 text-[12px] text-foreground-muted">
            <Loader2 size={13} className="animate-spin" /> Loading ELM submissions…
          </p>
        ) : list.length === 0 ? (
          <p className="px-4 py-8 text-center text-[12px] text-foreground-disabled">
            No ELM submissions yet — commit Swiss payslips for a period, then build them here.
          </p>
        ) : (
          <div className="divide-y divide-border-light">
            {list.map((sub) => <ElmRow key={sub.submissionId} sub={sub} onChanged={fetchList} busy={listLoading} />)}
          </div>
        )}
      </div>
    </div>
  );
}
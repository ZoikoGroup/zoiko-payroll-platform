import { useCallback, useEffect, useState } from "react";
import {
  approveMxJournalMapping, createMxJournalMapping, exportMxRunJournal, getMxRunJournal, listMxJournalMappings,
  voidMxJournalExport, withdrawMxJournalMapping,
} from "../../../service/payrollService";
import { Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

const link = "text-[12px] text-primary underline disabled:opacity-40";

// Payroll journal (ZP-MX-ENG-001 §20, Phase 10b). The employer maps each line
// type to an account of its own chart (versioned, approved by a second
// person); the journal of a committed run balances, keeps every authority
// liability on its own line and is exported as a CSV — nothing is posted to
// any ledger. A current export refuses the run's reset until it is voided.
export default function MXJournalPanel() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [runId, setRunId] = useState("");
  const [journal, setJournal] = useState(null);
  const [voidReason, setVoidReason] = useState("");
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    listMxJournalMappings()
      .then((d) => { if (active) { setData(d); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The journal mappings could not be loaded."));
    return () => { active = false; };
  }, [tick]);

  useEffect(() => {
    let active = true;
    if (!runId) return undefined;
    getMxRunJournal(Number(runId))
      .then((j) => active && setJournal(j))
      .catch((e) => active && setJournal({ error: e?.message || "The journal could not be built." }));
    return () => { active = false; };
  }, [runId, tick]);

  const lineTypes = data?.lineTypes || [];
  const approved = (data?.mappings || []).find((m) => m.status === "APPROVED");

  return (
    <Panel title="Payroll journal" testId="mx-journal"
      hint="Map each line type to your own accounts; a second person approves the mapping. The journal is a CSV for your accounting system — nothing is posted.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      <Messages error={error} notice={notice} />

      <div className="flex flex-col gap-2" data-testid="mx-journal-mappings">
        <p className="text-[12px] font-medium text-foreground">Account mappings</p>
        <Table rows={data?.mappings || []} empty="No mapping yet." columns={[
          { key: "version", label: "Version", render: (m) => `v${m.version}` },
          { key: "status", label: "Status", render: (m) => <Badge value={m.status} /> },
          { key: "accounts", label: "Accounts", render: (m) => `${Object.keys(m.accounts).length} mapped` },
          { key: "note", label: "Note", render: (m) => m.note || "—" },
          { key: "act", label: "", render: (m) => (m.status === "DRAFT" ? (
            <span className="flex gap-3">
              <button type="button" className={link} disabled={busy}
                onClick={() => run(() => approveMxJournalMapping(m.id), `Mapping v${m.version} approved.`)}>
                Approve (another person)
              </button>
              <button type="button" className="text-[12px] text-foreground-muted underline" disabled={busy}
                onClick={() => run(() => withdrawMxJournalMapping(m.id), "Withdrawn.")}>Withdraw</button>
            </span>
          ) : "") },
        ]} />
        {lineTypes.length > 0 && (
          <MiniForm
            testId="mx-new-journal-mapping" submitLabel="Propose mapping" busy={busy}
            initial={approved ? { ...approved.accounts } : {}}
            fields={[
              ...lineTypes.map((t) => ({ key: t.code, label: `${t.code} (${t.side.toLowerCase()})`, placeholder: "account" })),
              { key: "note", label: "Note" },
            ]}
            onSubmit={(s) => {
              const { note, ...accounts } = s;
              return run(() => createMxJournalMapping({ accounts, note }), "Mapping proposed — another person approves it.");
            }}
          />
        )}
      </div>

      <div className="flex flex-col gap-2" data-testid="mx-run-journal">
        <p className="text-[12px] font-medium text-foreground">Journal of a committed run</p>
        <MiniForm
          testId="mx-journal-run" submitLabel="Show journal" busy={busy}
          fields={[{ key: "runId", label: "Committed run id", required: true }]}
          onSubmit={(s) => { setRunId(String(s.runId || "")); return true; }}
        />
        {journal?.error && <p className="text-[12px] text-error" role="alert">{journal.error}</p>}
        {journal && !journal.error && (
          <>
            <p className="flex flex-wrap items-center gap-2 text-[12px] text-foreground-muted">
              Run #{journal.runId} · {journal.runType} · {journal.periodLabel} · pay date {journal.payDate} ·
              {journal.mappingVersion ? ` mapping v${journal.mappingVersion}` : " no approved mapping"} ·
              debits {journal.debitTotal} · credits {journal.creditTotal} ·
              <Badge value={journal.balanced ? "BALANCED" : "UNBALANCED"} />
            </p>
            <Table rows={journal.lines} rowKey={(l) => `${l.lineType}|${l.dimension}`} columns={[
              { key: "lineType", label: "Line type" },
              { key: "dimension", label: "Registration / state / kind", render: (l) => l.dimension || "—" },
              { key: "account", label: "Account", render: (l) => l.account || "— unmapped" },
              { key: "debit", label: "Debit", render: (l) => (l.side === "DEBIT" ? l.amount : "") },
              { key: "credit", label: "Credit", render: (l) => (l.side === "CREDIT" ? l.amount : "") },
            ]} />
            {journal.problems.map((p) => (
              <p key={p.code} className="text-[12px] text-error">{p.code}: {p.message}</p>
            ))}
            <span className="flex flex-wrap gap-3">
              <button type="button" className={link} disabled={busy || journal.problems.length > 0}
                onClick={() => run(() => exportMxRunJournal(journal.runId), "Journal exported — nothing was posted.")}>
                Export journal (CSV)
              </button>
            </span>
            <Table rows={journal.exports} empty="Not exported yet." columns={[
              { key: "id", label: "Export", render: (e) => `#${e.id}` },
              { key: "status", label: "Status", render: (e) => <Badge value={e.status} /> },
              { key: "lineCount", label: "Lines" },
              { key: "debitTotal", label: "Total" },
              { key: "sha256", label: "SHA-256", render: (e) => `${e.sha256.slice(0, 12)}…` },
              { key: "act", label: "", render: (e) => (e.status === "CURRENT" ? (
                <span className="flex items-center gap-2">
                  <input aria-label={`Void reason ${e.id}`} placeholder="reason (reversed / never posted)"
                    className="rounded border border-border px-1 text-[12px]" value={voidReason}
                    onChange={(ev) => setVoidReason(ev.target.value)} />
                  <button type="button" className={link} disabled={busy}
                    onClick={() => run(() => voidMxJournalExport(e.id, voidReason), "Export voided.")}>Void</button>
                </span>
              ) : (e.voidedReason || "")) },
            ]} />
          </>
        )}
      </div>
    </Panel>
  );
}

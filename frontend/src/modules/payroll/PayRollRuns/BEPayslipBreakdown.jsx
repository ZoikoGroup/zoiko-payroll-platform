import { beBaseLines, beEmployeeLines, beEmployerLines, beObligationLines } from "./bePayslipLines";

// Belgium payslip breakdown in the run detail (ZP-BE-ENG-001 spec §11; Block
// B3): the separate bases, the employee lines, the employer contribution
// composition and the obligation deltas — all from the frozen snapshot. Net pay
// is shown, never editable; the national number appears only masked.

function Lines({ title, rows, testId }) {
  if (!rows.length) return null;
  return (
    <div className="mt-2" data-testid={testId}>
      <p className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted">{title}</p>
      <dl className="mt-1 space-y-0.5 text-[12px]">
        {rows.map((r) => (
          <div key={r.key} className="flex justify-between gap-3">
            <dt className="text-foreground-muted">{r.label}</dt><dd className="font-mono text-foreground">{r.amount}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function BEPayslipBreakdown({ snapshot, employeeName }) {
  if (!snapshot) return null;
  const sector = snapshot.sector || {};
  const correction = snapshot.correctionOf;
  return (
    <div className="mt-2 rounded-lg border border-border bg-surface-muted/40 p-3" data-testid="be-payslip-breakdown">
      {snapshot.demo && <p className="mb-2 rounded-md border-2 border-error bg-error/10 px-2 py-1 text-center text-[13px] font-bold uppercase tracking-wider text-error" data-testid="be-demo-watermark">DEMO — NOT FOR PAYROLL</p>}
      <p className="text-[12px] font-semibold text-foreground">
        Belgium — {employeeName}{snapshot.identifierMasked ? ` · ${snapshot.identifierMasked}` : ""}
        {snapshot.documentVersion ? ` · ${snapshot.documentVersion}` : ""}
      </p>
      {correction ? (
        <p className="mt-1 text-[12px] text-warning" data-testid="be-payslip-correction">
          Correction of payslip #{correction}: {snapshot.reason} (evidence {snapshot.evidenceRef}). Net change{" "}
          <span className="font-mono">{snapshot.netDelta}</span>.
        </p>
      ) : (
        <>
          <p className="mt-1 text-[12px] text-foreground-muted">
            Joint Committee {sector.jointCommittee || "—"}{sector.subCommittee ? `/${sector.subCommittee}` : ""} ·
            function {sector.functionClass || "—"} · line {snapshot.employmentLine || "—"}
          </p>
          <Lines title="Bases" rows={beBaseLines(snapshot)} testId="be-payslip-bases" />
          <Lines title="Employee" rows={beEmployeeLines(snapshot)} testId="be-payslip-employee" />
          <Lines title="Employer (not deducted)" rows={beEmployerLines(snapshot)} testId="be-payslip-employer" />
          <Lines title="Obligations (paid to funds)" rows={beObligationLines(snapshot)} testId="be-payslip-obligations" />
          <p className="mt-2 text-[12px] font-semibold text-foreground">
            Net pay <span className="font-mono">{snapshot.be_net}</span>
          </p>
        </>
      )}
      {(snapshot.exceptions || []).length > 0 && (
        <ul className="mt-2 list-disc pl-4 text-[11px] text-warning">
          {snapshot.exceptions.map((e) => <li key={e.code}><span className="font-mono">{e.code}</span> — {e.detail}</li>)}
        </ul>
      )}
    </div>
  );
}

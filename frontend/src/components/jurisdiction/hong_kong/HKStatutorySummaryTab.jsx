import { Fragment, useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import { getHongKongStatutorySummary } from "../../../service/superAdminService";
import HKEvidencePanel from "./HKEvidencePanel";
import HKContributionDayDisruptions from "./HKContributionDayDisruptions";

// Hong Kong statutory summary (ZP-HK-ENG-001) — renders
// GET /super-admin/compliance/hong-kong/statutory-summary as returned: packs,
// sources, release gates G1–G7, [G1] certification items and external
// blockers. Nothing is computed here. Tenant-independent.
const STATE_STYLE = {
  PASS: { cls: "text-success", Icon: CheckCircle2 },
  SUBMITTED: { cls: "text-warning", Icon: AlertTriangle },
  REJECTED: { cls: "text-error", Icon: AlertTriangle },
  EVIDENCE_REQUIRED: { cls: "text-warning", Icon: AlertTriangle },
};

function GateState({ state }) {
  const s = STATE_STYLE[state] || { cls: "text-foreground-muted", Icon: CircleDashed };
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-bold ${s.cls}`}>
      <s.Icon size={13} aria-hidden="true" /> {state}
    </span>
  );
}

const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground";

export default function HKStatutorySummaryTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(() => {
    getHongKongStatutorySummary().then(setData).catch((err) => setError(err?.message || "Could not load the summary."));
  }, []);
  useEffect(() => { load(); }, [load]);
  const cert = data?.goldenCertification;

  if (error) return <p role="alert" className="text-[13px] text-error">{error}</p>;
  if (!data) return <p className="text-[13px] text-foreground-muted">Loading Hong Kong statutory summary…</p>;

  return (
    <div className="space-y-4">
      <section className={card} aria-labelledby="hk-arch">
        <h3 id="hk-arch" className="mb-2 text-[14px] font-semibold text-foreground">Architecture</h3>
        <ul className="space-y-1 text-[12px] text-foreground-secondary">
          <li><strong>Payroll withholding:</strong> {data.architecture.payrollWithholding}</li>
          <li><strong>IR56G:</strong> {data.architecture.ir56gHold}</li>
          <li><strong>Calculator:</strong> {data.architecture.calculator}</li>
          <li><strong>Service registry:</strong> {data.serviceRegistry}</li>
        </ul>
      </section>

      {cert && (
        <section className={card} aria-labelledby="hk-cert">
          <h3 id="hk-cert" className="mb-2 text-[14px] font-semibold text-foreground">Golden-vector certification</h3>
          <p className="text-[12px] text-foreground-secondary">
            <GateState state={cert.status === "PASS" ? "PASS" : cert.status === "NOT_RUN" ? "EVIDENCE_REQUIRED" : "REJECTED"} />{" "}
            Latest HK run: <strong>{cert.status}</strong>
            {cert.runId ? ` (#${cert.runId}, ${cert.passedCases}/${cert.totalCases} cases passed, ${cert.runAt})` : ""} ·
            Eligible for pack activation: <strong>{cert.eligibleForActivation ? "Yes" : "No"}</strong>
          </p>
          <p className="mt-1 text-[12px] text-foreground-muted">{cert.detail} Run it from the Golden Vectors tab.</p>
        </section>
      )}

      <section className={card} aria-labelledby="hk-packs">
        <h3 id="hk-packs" className="mb-2 text-[14px] font-semibold text-foreground">Rule packs (year of assessment)</h3>
        <table className="w-full">
          <thead><tr><th className={th}>Pack</th><th className={th}>YA</th><th className={th}>Window</th><th className={th}>Status</th><th className={th}>Rows</th><th className={th}>[G1] rows</th></tr></thead>
          <tbody>
            {data.packs.map((p) => (
              <tr key={p.id} className="border-t border-border">
                <td className={td}>{p.packId} v{p.version}</td>
                <td className={td}>{p.yearOfAssessment}</td>
                <td className={td}>{p.effectiveFrom} – {p.effectiveTo}</td>
                <td className={td}>{p.status}</td>
                <td className={td}>{p.contributionRates} rates · {p.taxSlabs} bands{p.unsourcedRows.length ? ` · ${p.unsourcedRows.length} unsourced` : ""}</td>
                <td className={td}>{p.g1CertificationRows}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={card} aria-labelledby="hk-gates">
        <h3 id="hk-gates" className="mb-2 text-[14px] font-semibold text-foreground">Production release gates</h3>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Submit each gate&apos;s signed document below (tagged with the gate, e.g. HK-GATE-G1; the server computes its SHA-256);
          a different Super Admin accepts or rejects it. G1 is enforced at pack activation; G1–G7 at service opening.
        </p>
        <table className="w-full">
          <thead><tr><th className={th}>Gate</th><th className={th}>Requirement</th><th className={th}>State</th><th className={th}>Evidence</th></tr></thead>
          <tbody>
            {data.gates.map((g) => (
              <Fragment key={g.gate}>
                <tr className="border-t border-border">
                  <td className={td}>{g.gate}</td><td className={td}>{g.requirement}</td><td className={td}><GateState state={g.state} /></td>
                  <td className={td}>
                    <button type="button" className="text-[12px] font-semibold text-primary underline" aria-expanded={open === g.gate}
                      onClick={() => setOpen(open === g.gate ? null : g.gate)}>
                      {open === g.gate ? "Hide" : `Evidence (${(g.evidence || []).length})`}
                    </button>
                  </td>
                </tr>
                {open === g.gate && (
                  <tr><td colSpan={4} className="px-2 pb-2"><HKEvidencePanel tag={g.evidenceTag} items={g.evidence} onChanged={load} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        <div className="mt-3">
          <h4 className="mb-1 text-[12px] font-semibold text-foreground">Production read-only verification (HK-PRODUCTION-VERIFICATION)</h4>
          <HKEvidencePanel tag="HK-PRODUCTION-VERIFICATION" items={data.productionVerificationEvidence} onChanged={load} />
        </div>
      </section>

      <HKContributionDayDisruptions />

      <section className={card} aria-labelledby="hk-blockers">
        <h3 id="hk-blockers" className="mb-2 text-[14px] font-semibold text-foreground">External blockers</h3>
        <ul className="list-disc space-y-1 pl-5 text-[12px] text-foreground-secondary">
          {data.externalBlockers.map((b) => <li key={b}>{b}</li>)}
        </ul>
      </section>

      <section className={card} aria-labelledby="hk-sources">
        <h3 id="hk-sources" className="mb-2 text-[14px] font-semibold text-foreground">Official sources ({data.sources.length})</h3>
        <table className="w-full">
          <thead><tr><th className={th}>Authority</th><th className={th}>Document</th><th className={th}>SHA-256</th><th className={th}>Reviewed</th></tr></thead>
          <tbody>
            {data.sources.map((s) => (
              <tr key={s.id} className="border-t border-border">
                <td className={td}>{s.agency}</td>
                <td className={td}><a className="text-primary underline" href={s.url} target="_blank" rel="noreferrer">{s.title}</a></td>
                <td className={`${td} font-mono text-[11px]`}>{s.sha256 ? `${s.sha256.slice(0, 12)}…` : <span className="text-warning">not retrieved (G1)</span>}</td>
                <td className={td}>{s.reviewed ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={card} aria-labelledby="hk-g1">
        <h3 id="hk-g1" className="mb-2 text-[14px] font-semibold text-foreground">Rows awaiting Hong Kong specialist certification (G1)</h3>
        <ul className="max-h-64 list-disc space-y-0.5 overflow-auto pl-5 text-[12px] text-foreground-secondary">
          {data.certificationItems.map((c) => <li key={c}>{c}</li>)}
        </ul>
      </section>
    </div>
  );
}

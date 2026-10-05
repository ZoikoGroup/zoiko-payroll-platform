import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import { getHongKongStatutorySummary } from "../../../service/superAdminService";

// Hong Kong statutory summary (ZP-HK-ENG-001) — renders
// GET /super-admin/compliance/hong-kong/statutory-summary as returned: packs,
// sources, release gates G1–G7, [G1] certification items and external
// blockers. Nothing is computed here. Tenant-independent.
const STATE_STYLE = {
  PASS: { cls: "text-success", Icon: CheckCircle2 },
  SUBMITTED: { cls: "text-warning", Icon: AlertTriangle },
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

  useEffect(() => {
    getHongKongStatutorySummary().then(setData).catch((err) => setError(err?.message || "Could not load the summary."));
  }, []);

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
          Evidence is recorded as a Source Evidence artifact tagged with the gate (e.g. HK-GATE-G1), with the signed document uploaded;
          a different Super Admin reviews it. G1 is enforced at pack activation.
        </p>
        <table className="w-full">
          <thead><tr><th className={th}>Gate</th><th className={th}>Requirement</th><th className={th}>State</th></tr></thead>
          <tbody>
            {data.gates.map((g) => (
              <tr key={g.gate} className="border-t border-border">
                <td className={td}>{g.gate}</td><td className={td}>{g.requirement}</td><td className={td}><GateState state={g.state} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

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

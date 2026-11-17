import { useMemo, useState } from "react";
import { getBeActivationReadiness } from "../../../service/superAdminService";
import { inputClass } from "../constants";
import { card, td, th, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// Activation readiness of the selected Belgium pack — READ-ONLY (backend belgium_activation_readiness).
// The verdict is the governed activation gate's own; every blocking row lists ALL its reasons, its source state and
// who clears each reason; a second list shows what would still block payroll after activation (engine gaps, keys
// without a vocabulary, open questions, unsourced amendments, quarterly ONSS rate files). Nothing here signs,
// approves or activates. The release gates G1–G7 stay on the Overview.

const CLEARER = {
  BELGIAN_SPECIALIST: "Belgian specialist",
  SECOND_SUPER_ADMIN: "Second Super Admin (signs)",
  SOURCE_REVIEWER: "Source reviewer",
  ENGINEERING: "Engineering",
  OWNER: "Owner",
  THIRD_SUPER_ADMIN: "Third Super Admin (activates)",
};
const REASON = {
  MISSING: "row missing", UNSIGNED: "unsigned", EMPTY: "no value", UNSOURCED: "no source",
  SLAB_ROWS: "band / formula rows missing or unsigned",
};
const chip = "mr-1 inline-block rounded border px-1.5 py-0.5 text-[11px]";

function Count({ label, value, tone }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${tone}`}>
      <div className="text-[11px] uppercase tracking-wide text-foreground-muted">{label}</div>
      <div className="text-[18px] font-semibold text-foreground">{value}</div>
    </div>
  );
}

function Verdict({ report }) {
  const { verdict, pack, summary } = report;
  const ok = verdict.canActivate;
  return (
    <div className={card} data-testid="be-readiness-verdict">
      <h3 className="text-[14px] font-semibold text-foreground">
        {pack.packId} v{pack.version} ({pack.status}) — {ok ? "the activation gate would accept it" : "cannot be activated yet"}
      </h3>
      {!ok && <p className="mt-1 text-[12px] text-error" data-testid="be-readiness-gate">{verdict.gateRefusal}</p>}
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Count label="Blocking rows" value={`${verdict.blockingRows} / ${verdict.catalogueRows}`}
          tone={verdict.blockingRows ? "border-error/30 bg-error/5" : "border-success/30 bg-success/5"} />
        <Count label="Blocking conditions" value={verdict.blockingConditions}
          tone={verdict.blockingConditions ? "border-error/30 bg-error/5" : "border-success/30 bg-success/5"} />
        {Object.entries(summary.byClearer || {}).slice(0, 2).map(([who, n]) => (
          <Count key={who} label={`Waiting on: ${CLEARER[who] || who}`} value={n} tone="border-border" />
        ))}
      </div>
      <p className="mt-2 text-[11px] text-foreground-muted">
        Read-only. Signing, approval and activation stay four-eyes actions on their own tabs; nobody who edited or
        signed a row of this version may activate it.
      </p>
    </div>
  );
}

function Conditions({ items }) {
  return (
    <div className={card} data-testid="be-readiness-conditions">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Conditions</h3>
      <ul className="space-y-1 text-[12px]">
        {items.map((c) => (
          <li key={c.code} className={c.blocking ? "text-error" : "text-foreground-secondary"}>
            <strong>{c.code}</strong>{c.blocking ? " — blocks activation" : ""}: {c.detail}
            <div className="text-foreground-muted">→ {CLEARER[c.by] || c.by}: {c.action}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Rows({ rows }) {
  const [who, setWho] = useState("");
  const [onlyBlocking, setOnlyBlocking] = useState(true);
  const shown = useMemo(() => rows.filter((r) => (!onlyBlocking || r.blocks.length)
    && (!who || r.clearedBy.some((c) => c.by === who) || r.payrollBlockers.some((p) => p.by === who))), [rows, who, onlyBlocking]);
  return (
    <div className={card} data-testid="be-readiness-rows">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h3 className="text-[14px] font-semibold text-foreground">Rows ({shown.length})</h3>
        <select className={`${inputClass} w-auto`} value={who} onChange={(e) => setWho(e.target.value)}
          aria-label="Filter by who clears it">
          <option value="">Everyone</option>
          {Object.entries(CLEARER).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="text-[12px] text-foreground-secondary">
          <input type="checkbox" className="mr-1" checked={onlyBlocking} onChange={(e) => setOnlyBlocking(e.target.checked)} />
          only rows that block activation
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead><tr><th className={th}>Key</th><th className={th}>Blocks activation</th><th className={th}>Source</th>
            <th className={th}>Who clears it</th><th className={th}>Also blocks payroll</th></tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.key} className="border-t border-border" data-testid={`be-readiness-row-${r.key}`}>
                <td className={td}><code>{r.key}</code><div className="text-[11px] text-foreground-muted">{r.group}</div></td>
                <td className={td}>{r.blocks.length ? r.blocks.map((b) => (
                  <span key={b} className={`${chip} border-error/30 text-error`}>{REASON[b] || b}</span>)) : "—"}</td>
                <td className={td}>{r.source.reference || "—"}<div className="text-[11px] text-foreground-muted">{r.source.state}</div></td>
                <td className={td}>{r.clearedBy.map((c, i) => (
                  <div key={`${c.reason}${i}`}><strong>{CLEARER[c.by] || c.by}</strong>: {c.action}</div>))}</td>
                <td className={td}>{r.payrollBlockers.map((p) => (
                  <div key={p.code}><span className={`${chip} border-warning/30 text-warning`}>{p.code}</span>{p.detail}</div>))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AfterActivation({ after }) {
  return (
    <div className={card} data-testid="be-readiness-after">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Still blocks payroll after activation</h3>
      <h4 className="text-[12px] font-semibold text-foreground">Quarterly ONSS rate files</h4>
      <ul className="mb-3 text-[12px]">
        {after.rateFiles.map((q) => (
          <li key={q.quarter} className={q.state === "READY" ? "text-success" : "text-foreground-secondary"}>
            {q.quarter} ({q.from} – {q.to}): <strong>{q.state}</strong>
            {q.action ? <span className="text-foreground-muted"> → {CLEARER[q.by] || q.by}: {q.action}</span> : null}
          </li>
        ))}
      </ul>
      <h4 className="text-[12px] font-semibold text-foreground">Owner decisions</h4>
      <ul className="mb-3 text-[12px]">
        {after.decisions.map((d) => (
          <li key={d.gap} className={d.state === "DECIDED" ? "text-success" : "text-foreground-secondary"}>
            {d.gap} — {d.question}: <strong>{d.state}</strong>
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-foreground-muted">Release gates G1–G7: {after.releaseGates}</p>
    </div>
  );
}

export default function BEActivationReadinessTab({ pack }) {
  const [report, error, loading, reload] = useLoad(() => getBeActivationReadiness(pack.id));
  if (error) return <ErrorNote message={error} />;
  if (loading && !report) return <p className="text-[12px] text-foreground-muted">Loading activation readiness…</p>;
  if (!report) return null;
  return (
    <div className="space-y-3" data-testid="be-activation-readiness">
      <div className="flex justify-end">
        <button type="button" onClick={reload} className="rounded-lg border border-border px-3 py-1.5 text-[12px]">Refresh</button>
      </div>
      <Verdict report={report} />
      <Conditions items={report.conditions} />
      <Rows rows={report.rows} />
      <AfterActivation after={report.afterActivation} />
    </div>
  );
}

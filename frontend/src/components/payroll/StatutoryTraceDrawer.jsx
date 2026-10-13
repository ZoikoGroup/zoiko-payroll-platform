import { useEffect } from "react";
import Drawer from "../Drawer";

// Generic statutory trace drawer. Renders a calculation snapshot's lines[]
// exactly as the engine recorded them — obligation, base, rate or rule, cap,
// scope (canton / fund / insurer / tariff file), version and source — with
// employer costs in their own section. It never computes a figure: a line
// carries no amount because rounding (CHF 0.05) and caps are applied by the
// engine, so the only amounts shown are the snapshot's own totals.
//
// `snapshot` may hold the lines directly ({ lines: [...] }) or under `trace`
// (Switzerland: { totals, trace: { lines, input_hash, rule_hash, ... } }).
// Line keys are read in snake_case or camelCase.

const pick = (obj, ...keys) => {
  for (const k of keys) if (obj?.[k] !== undefined && obj?.[k] !== null && obj?.[k] !== "") return obj[k];
  return null;
};

function formatRate(value, rateFormat) {
  const n = Number(value);
  if (value === null || value === "" || Number.isNaN(n)) return value ?? "—"; // a rule name, e.g. NO_MANDATORY_FLOOR
  if (rateFormat === "fraction") return `${(n * 100).toLocaleString(undefined, { maximumFractionDigits: 4 })}%`;
  if (rateFormat === "percent") return `${n.toLocaleString(undefined, { maximumFractionDigits: 4 })}%`;
  return String(value);
}

function label(obligation) {
  return String(obligation || "—").replace(/^[a-z]{2}_/, "").replace(/_/g, " ").toUpperCase();
}

function LineTable({ lines, rateFormat, currency }) {
  if (!lines.length) return <p className="text-xs text-foreground-muted">None.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-xs">
        <thead className="bg-surface-muted text-left text-foreground-muted">
          <tr>
            <th scope="col" className="px-2 py-1.5 font-medium">Obligation</th>
            <th scope="col" className="px-2 py-1.5 font-medium text-right">Base ({currency})</th>
            <th scope="col" className="px-2 py-1.5 font-medium text-right">Rate / rule</th>
            <th scope="col" className="px-2 py-1.5 font-medium text-right">Cap</th>
            <th scope="col" className="px-2 py-1.5 font-medium">Scope · version · source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {lines.map((l, i) => (
            <tr key={`${pick(l, "obligation")}-${pick(l, "side")}-${i}`}>
              <td className="px-2 py-1.5 font-medium text-foreground">{label(pick(l, "obligation"))}</td>
              <td className="px-2 py-1.5 text-right font-mono text-foreground">{pick(l, "base") ?? "—"}</td>
              <td className="px-2 py-1.5 text-right font-mono text-foreground">
                {formatRate(pick(l, "rate_or_rule", "rateOrRule", "rate"), rateFormat)}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-foreground-muted">{pick(l, "cap") ?? "—"}</td>
              <td className="px-2 py-1.5 text-foreground-muted">
                <span className="font-mono">{pick(l, "scope_id", "scopeId") ?? "—"}</span>
                {" · v"}{pick(l, "scope_version", "scopeVersion", "rule_version", "ruleVersion") ?? "—"}
                {" · "}{pick(l, "source_label", "sourceLabel") ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function StatutoryTraceDrawer({
  open, onClose, snapshot, title = "Statutory calculation trace", subtitle, currency = "",
  rateFormat = "fraction", employeeTotalKey = "ch_employee_total", employerTotalKey = "ch_employer_total",
  layerClass = "",
}) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;

  const trace = snapshot?.trace || snapshot || {};
  const lines = Array.isArray(trace.lines) ? trace.lines : [];
  const side = (l) => String(pick(l, "side") || "").toLowerCase();
  const employee = lines.filter((l) => side(l) === "employee");
  const employer = lines.filter((l) => side(l) === "employer");
  const other = lines.filter((l) => !["employee", "employer"].includes(side(l)));
  const totals = snapshot?.totals || {};
  const correction = snapshot?.correction;
  const versions = trace.resolved_versions || trace.resolvedVersions;

  // layerClass lifts the drawer above an already-open overlay (e.g. the
  // payslip modal at z-[9999]) by giving it its own stacking context.
  return (
    <div className={layerClass ? `relative ${layerClass}` : undefined}>
    <Drawer title={title} subtitle={subtitle} onClose={onClose} width="max-w-3xl">
      {!lines.length ? (
        <p className="text-sm text-foreground-muted">This payslip carries no statutory trace lines.</p>
      ) : (
        <div className="space-y-5">
          {correction && (
            <p role="note" className="rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-xs text-foreground-secondary">
              Correction {correction.sequence} of payslip #{correction.originalPayslipId}: {correction.reason}
            </p>
          )}
          <section aria-labelledby="trace-employee" className="space-y-2">
            <div className="flex items-baseline justify-between">
              <h4 id="trace-employee" className="text-sm font-semibold text-foreground">Employee deductions</h4>
              {totals[employeeTotalKey] != null && (
                <span className="text-xs text-foreground-muted">Total {currency} {totals[employeeTotalKey]}</span>
              )}
            </div>
            <LineTable lines={employee} rateFormat={rateFormat} currency={currency} />
          </section>
          <section aria-labelledby="trace-employer" className="space-y-2">
            <div className="flex items-baseline justify-between">
              <h4 id="trace-employer" className="text-sm font-semibold text-foreground">Employer costs</h4>
              {totals[employerTotalKey] != null && (
                <span className="text-xs text-foreground-muted">Total {currency} {totals[employerTotalKey]}</span>
              )}
            </div>
            <LineTable lines={employer} rateFormat={rateFormat} currency={currency} />
          </section>
          {other.length > 0 && (
            <section aria-labelledby="trace-checks" className="space-y-2">
              <h4 id="trace-checks" className="text-sm font-semibold text-foreground">Checks</h4>
              <LineTable lines={other} rateFormat={rateFormat} currency={currency} />
            </section>
          )}
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 border-t border-border pt-3 text-[11px] sm:grid-cols-2">
            {versions && Object.entries(versions).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-foreground-muted">{k.replace(/_/g, " ")}</dt>
                <dd className="font-mono text-foreground">{v ?? "—"}</dd>
              </div>
            ))}
            {trace.input_hash && (<><dt className="text-foreground-muted">input hash</dt><dd className="font-mono break-all text-foreground">{trace.input_hash}</dd></>)}
            {trace.rule_hash && (<><dt className="text-foreground-muted">rule hash</dt><dd className="font-mono break-all text-foreground">{trace.rule_hash}</dd></>)}
          </dl>
        </div>
      )}
    </Drawer>
    </div>
  );
}

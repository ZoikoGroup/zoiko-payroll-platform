import Notice from "../../../../components/jurisdiction/Notice";
import { TaxSlabsTable } from "../../../../components/jurisdiction/PackRowTables";
import { useLoad } from "../../../../components/jurisdiction/japan/jpFormat";
import { getGermanyWageTaxTariff } from "../../../../service/superAdminService";
import { PapTab } from "../../GermanyStatutoryRegistriesPage";
import { DE_TARIFF_WARNING, loadPapWarning } from "./deShared";

// Germany Tax Slabs tab. Germany has no tax-slab rows: wage tax comes from the
// section 32a EStG tariff built into engine/jurisdictions/germany/tax.py, an
// internal reference tariff that is NOT BMF-certified. This tab shows (1) that
// warning, (2) the tariff zones read-only, as GET .../germany/wage-tax-tariff
// reads them from tax.py's _TARIFF_VERSIONS (no figure is typed here), in the
// shared slab table, and (3) the PAP panel (assets, releases, gates).

const cell = "px-3 py-2 text-foreground-secondary";

export function DEWageTaxWarning({ testId = "de-wage-tax-warning" }) {
  const [text, error] = useLoad(loadPapWarning);
  return (
    <Notice tone="error" title="Wage tax is not BMF-certified" testId={testId}>
      {text || (error ? `${DE_TARIFF_WARNING} (PAP release list could not be loaded: ${error})` : "Loading…")}
    </Notice>
  );
}

function ParameterTable({ title, rows, testId }) {
  if (!rows?.length) return null;
  return (
    <div className="space-y-1" data-testid={testId}>
    <p className="text-xs font-semibold text-foreground">{title}</p>
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-xs">
        <thead className="bg-background text-left text-foreground-muted">
          <tr><th className="px-3 py-2">Parameter</th><th className="px-3 py-2">Value</th><th className="px-3 py-2">Status</th></tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.key} className="border-t border-border-light">
              <td className="px-3 py-2">
                <p className="font-semibold text-foreground">{p.label}</p>
                <p className="font-mono text-[10px] text-foreground-disabled">{p.key}</p>
              </td>
              <td className={cell}>{p.value ?? "—"}</td>
              <td className={cell}>{p.status}{p.sourceFile ? ` · ${p.sourceFile.split("/").pop()}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </div>
  );
}

export default function DETaxSlabsTab() {
  const [tariff, error] = useLoad(getGermanyWageTaxTariff);
  return (
    <div className="space-y-4" data-testid="de-tax-slabs">
      <DEWageTaxWarning />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold text-foreground">Section 32a EStG tariff zones</h3>
          {tariff && (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-[11px] font-semibold text-warning"
              data-testid="de-tariff-status">{tariff.status}</span>
          )}
        </div>
        {error && <p className="text-xs text-error">{error}</p>}
        {!tariff && !error && <p className="text-xs text-foreground-muted">Loading…</p>}
        {tariff && (
          <>
            <p className="text-xs text-foreground-muted">
              Read-only, read from {tariff.sourceFile.split("/").slice(-3).join("/")} ({tariff.provenance}). {tariff.note}
            </p>
            <TaxSlabsTable
              sections={tariff.versions.map((v) => ({
                key: v.taxYear,
                label: `${v.taxYear} · from ${v.effectiveFrom}${v.effectiveToExclusive ? ` until ${v.effectiveToExclusive} (exclusive)` : " · open-ended"}${v.inForceToday ? " · in force today" : ""}`,
                rows: v.zones.map((z) => ({ ...z, id: `${v.taxYear}-${z.zone}`, rateLabel: `Zone ${z.zone}: ${z.label}` })),
              }))}
              hideColumns={["state", "filingStatus"]}
              extraColumns={[{ key: "formula", label: "Formula", cellClass: "px-3 py-2 font-mono text-[11px] text-foreground-secondary", render: (z) => z.formula }]}
            />
            {tariff.versions.map((v) => (
              <ParameterTable key={v.taxYear} testId={`de-tariff-params-${v.taxYear}`} title={`Tariff parameters · ${v.taxYear}`}
                rows={v.parameters.map((p) => ({ ...p, status: `Built into engine (tax.py), ${v.taxYear}` }))} />
            ))}
            <ParameterTable testId="de-engine-tax-params" title="Solidarity surcharge and lump sums (engine constants)" rows={tariff.engineParameters} />
          </>
        )}
      </div>

      <h3 className="pt-1 text-[13px] font-semibold text-foreground">PAP (BMF Programmablaufplan)</h3>
      <PapTab />
    </div>
  );
}

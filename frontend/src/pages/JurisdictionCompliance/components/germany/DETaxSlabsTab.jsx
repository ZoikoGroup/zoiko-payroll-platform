import Collapsible from "../../../../components/jurisdiction/Collapsible";
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

const periodLabel = (v) => `${v.taxYear} · from ${v.effectiveFrom}${v.effectiveToExclusive ? ` until ${v.effectiveToExclusive} (exclusive)` : " · open-ended"}`;

function TariffZones({ version }) {
  return (
    <>
      <TaxSlabsTable
        sections={[{
          key: version.taxYear, label: periodLabel(version),
          rows: version.zones.map((z) => ({ ...z, id: `${version.taxYear}-${z.zone}`, rateLabel: `Zone ${z.zone}: ${z.label}` })),
        }]}
        hideColumns={["state", "filingStatus"]}
        extraColumns={[{ key: "formula", label: "Formula", cellClass: "px-3 py-2 font-mono text-[11px] text-foreground-secondary", render: (z) => z.formula }]}
      />
      <ParameterTable testId={`de-tariff-params-${version.taxYear}`} title={`Tariff parameters · ${version.taxYear}`}
        rows={version.parameters.map((p) => ({ ...p, status: `Built into engine (tax.py), ${version.taxYear}` }))} />
    </>
  );
}

export default function DETaxSlabsTab({ pack }) {
  const [tariff, error] = useLoad(() => getGermanyWageTaxTariff(pack.id));
  const applies = tariff?.versions?.find((v) => v.appliesToPack) || null;
  const others = (tariff?.versions || []).filter((v) => v !== applies);
  return (
    <div className="space-y-4" data-testid="de-tax-slabs">
      <DEWageTaxWarning />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold text-foreground">Section 32a EStG tariff for this pack</h3>
          {tariff && (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-[11px] font-semibold text-warning"
              data-testid="de-tariff-status">{tariff.status}</span>
          )}
        </div>
        {error && <p className="text-xs text-error">{error}</p>}
        {!tariff && !error && <p className="text-xs text-foreground-muted">Loading…</p>}
        {tariff && (
          <>
            <p className="text-xs text-foreground-muted" data-testid="de-tariff-basis">
              {applies
                ? <>The engine applies the <strong>{applies.taxYear}</strong> tariff to payslips of {pack.packId} ({tariff.pack?.basis}),
                  as tax.py resolves it from each payslip&apos;s pay date.</>
                : <>No tariff in tax.py covers {pack.packId}: {tariff.pack?.note}</>}
              {" "}Read-only, read from {tariff.sourceFile.split("/").slice(-3).join("/")}. {tariff.note}
            </p>
            {applies && <TariffZones version={applies} />}
            {others.map((v) => (
              <Collapsible key={v.taxYear} testId={`de-tariff-other-${v.taxYear}`}
                title={`${v.endsBeforePack ? "Historical" : "Other tariff"}: not used for this pack`}
                summary={periodLabel(v)}>
                <TariffZones version={v} />
              </Collapsible>
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

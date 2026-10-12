import { useState } from "react";
import { AlertTriangle, Calculator, Pencil, Plus, Trash2 } from "lucide-react";
import StatusPill from "../../StatusPill";
import { STATUS_PILL_MAP, inputClass, labelClass } from "../constants";
import SGBandFormModal from "./SGBandFormModal";
import { previewSingaporeCalculation } from "../../../service/superAdminService";
import {
  CPF_AGE_BANDS, CPF_BLOCKED, CPF_COHORTS, CPF_WAGE_BANDS, IR21_STATUSES, IR21_WORKFLOW, NOT_BUILT, NOT_CONFIGURED, SHG_FUNDS,
  IR8A_STATUS, describeBand, findCpfCell, formatDate, formatPct, formatSgdAuto, fractionToPct, rateByKey, shgRows,
  wageBandRange,
} from "./sgComponentConfig";

// Singapore "Statutory Components" tab — every figure is read from the
// selected pack's canonical ContributionRate/TaxSlab rows. Band rows are
// edited through SGBandFormModal; scalar rows reuse JurisdictionLayout's own
// shared RateFormModal (onAddRate/onEditRate) and ConfirmDialog
// (onDeleteRate/onDeleteSlab). Operational workflows that don't exist in
// this phase (IR21 hold/release, AIS API, CPF EZPay, MOM bill import) are
// shown as status only — no action buttons are offered for them.
const SECTIONS = [
  { key: "cpf", label: "CPF" },
  { key: "sdl", label: "SDL" },
  { key: "shg", label: "Self-Help Groups" },
  { key: "foreign", label: "Foreign Workforce" },
  { key: "lqs", label: "LQS / PWM" },
  { key: "iras", label: "IRAS AIS" },
  { key: "ir21", label: "IR21" },
];

export default function SGStatutoryComponentsTab({ pack, rates, slabs, onReload, onAddRate, onEditRate, onDeleteRate, onDeleteSlab }) {
  const [section, setSection] = useState("cpf");
  const [band, setBand] = useState(null); // { kind, slab?, initial? }

  const ctx = { pack, rates, slabs, onAddRate, onEditRate, onDeleteRate, onDeleteSlab, openBand: setBand };

  return (
    <div className="space-y-4">
      <nav aria-label="Singapore statutory components" className="flex flex-wrap gap-1 rounded-lg border border-border bg-surface-muted p-1">
        {SECTIONS.map((s) => (
          <button
            key={s.key} type="button" onClick={() => setSection(s.key)} aria-current={section === s.key ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring ${
              section === s.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"
            }`}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {section === "cpf" && <CpfSection {...ctx} />}
      {section === "sdl" && <SdlSection {...ctx} />}
      {section === "shg" && <ShgSection {...ctx} />}
      {section === "foreign" && <ForeignWorkforceSection {...ctx} />}
      {section === "lqs" && <LqsSection {...ctx} />}
      {section === "iras" && <IrasSection {...ctx} />}
      {section === "ir21" && <Ir21Section {...ctx} />}

      {band && (
        <SGBandFormModal
          pack={pack} slabs={slabs} kind={band.kind} slab={band.slab} initial={band.initial}
          onClose={() => setBand(null)}
          onSaved={() => { setBand(null); onReload?.(); }}
        />
      )}
    </div>
  );
}

// ── shared bits ──────────────────────────────────────────────────────────

function Card({ title, subtitle, action, children }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-foreground">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-foreground-muted">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Blocked({ children = NOT_CONFIGURED }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-error">
      <AlertTriangle size={12} aria-hidden="true" /> {children}
    </span>
  );
}

function StatusText({ label }) {
  return <span className="rounded-md bg-warning/10 px-2 py-0.5 text-[11px] font-semibold text-warning">{label}</span>;
}

function sourceLabel(row, pack) {
  if (row?.sourceDocumentId) return `Source artifact #${row.sourceDocumentId}`;
  if (pack?.sourceDocumentId) return `Pack evidence #${pack.sourceDocumentId}`;
  return "Not linked";
}

function effectiveLabel(row, pack) {
  return formatDate(row?.effectiveFrom || pack?.effectiveFrom) + (row?.effectiveTo ? ` → ${formatDate(row.effectiveTo)}` : "");
}

// One table for scalar ContributionRate rows — label, value, effective,
// source, pack status, edit/delete via the layout's shared modals.
function ParameterTable({ caption, keys, pack, rates, onAddRate, onEditRate, onDeleteRate, format = {} }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-background text-left text-foreground-muted">
          <tr>
            <th scope="col" className="px-3 py-2">Parameter</th>
            <th scope="col" className="px-3 py-2">Value</th>
            <th scope="col" className="px-3 py-2">Effective</th>
            <th scope="col" className="px-3 py-2">Source</th>
            <th scope="col" className="px-3 py-2">Status</th>
            <th scope="col" className="w-16 px-3 py-2"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {keys.flatMap(({ key, label }) => {
            const rows = (rates || []).filter((r) => r.componentKey === key)
              .sort((x, y) => String(x.effectiveFrom || "").localeCompare(String(y.effectiveFrom || "")));
            return (rows.length ? rows : [null]).map((row, i) => {
              const value = !row ? null
                : format[key] ? format[key](row)
                  : row.textValue ?? (row.flatAmount != null ? formatSgdAuto(row.flatAmount) : fractionToPct(row.employerRatePct ?? row.employeeRatePct));
              return (
                <tr key={row ? row.id : `${key}-missing`} className="border-t border-border-light">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <p className="font-semibold text-foreground">{row?.label || label}</p>
                    <p className="font-mono text-[10px] text-foreground-disabled">{key}{rows.length > 1 ? ` (${i + 1}/${rows.length})` : ""}</p>
                  </th>
                  <td className="px-3 py-2 font-semibold text-foreground">{row ? value : <Blocked />}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{row ? effectiveLabel(row, pack) : "—"}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{row ? sourceLabel(row, pack) : "—"}</td>
                  <td className="px-3 py-2">{row ? <StatusPill status={STATUS_PILL_MAP[pack.status] || "pending"} label={pack.status} /> : "—"}</td>
                  <td className="px-3 py-2">
                    {row ? (
                      <div className="flex items-center gap-1">
                        <button type="button" aria-label={`Edit ${key}`} onClick={() => onEditRate(row)} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted hover:text-primary"><Pencil size={12} /></button>
                        <button type="button" aria-label={`Delete ${key}`} onClick={() => onDeleteRate(row)} className="rounded p-1 text-foreground-disabled hover:bg-error-light hover:text-error"><Trash2 size={12} /></button>
                      </div>
                    ) : (
                      <button type="button" aria-label={`Add ${key}`} onClick={onAddRate} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted hover:text-primary"><Plus size={12} /></button>
                    )}
                  </td>
                </tr>
              );
            });
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── CPF ──────────────────────────────────────────────────────────────────

function CpfSection({ pack, rates, slabs, onAddRate, onEditRate, onDeleteRate, onDeleteSlab, openBand }) {
  const [cohort, setCohort] = useState("SC_SPR3");
  const cohortLabel = CPF_COHORTS.find((c) => c.key === cohort)?.label;

  return (
    <div className="space-y-4">
      <Card title="CPF ceilings and contribution calendar" subtitle="OW is capped monthly; the annual ceiling limits Additional Wages (AW ceiling = annual ceiling − YTD OW subject to CPF − YTD AW already subject).">
        <ParameterTable
          caption="CPF ceilings" pack={pack} rates={rates} onAddRate={onAddRate} onEditRate={onEditRate} onDeleteRate={onDeleteRate}
          keys={[
            { key: "cpf_ow_ceiling_monthly", label: "CPF Ordinary Wage ceiling (monthly)" },
            { key: "cpf_annual_wage_ceiling", label: "CPF annual wage ceiling" },
            { key: "cpf_age_band_semantics", label: "CPF age-band boundary rule" },
            { key: "cpf_enforcement_day_following_month", label: "CPF enforcement day (following month)" },
          ]}
          format={{ cpf_enforcement_day_following_month: (r) => `After the ${Number(r.flatAmount)}th` }}
        />
      </Card>

      <Card
        title="CPF rate matrix"
        subtitle="Each cell is its own effective-dated statutory row — the full-rate percentage is never extrapolated to lower wage bands."
        action={(
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="sg-cpf-cohort">Cohort</label>
            <select id="sg-cpf-cohort" className={inputClass + " w-auto"} value={cohort} onChange={(e) => setCohort(e.target.value)}>
              {CPF_COHORTS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
        )}
      >
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <caption className="sr-only">CPF rates for {cohortLabel}, by age band and total-wage band</caption>
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th scope="col" className="px-3 py-2">Age band</th>
                {CPF_WAGE_BANDS.map((b) => <th key={b.basis} scope="col" className="px-3 py-2">{b.label} <span className="font-normal">({wageBandRange(slabs, b.basis)})</span><span className="block font-mono text-[10px] text-foreground-disabled">{b.basis}</span></th>)}
              </tr>
            </thead>
            <tbody>
              {CPF_AGE_BANDS.map((age) => (
                <tr key={age.key} className="border-t border-border-light align-top">
                  <th scope="row" className="px-3 py-2 text-left font-semibold text-foreground">{age.label}</th>
                  {CPF_WAGE_BANDS.map((b) => (
                    <td key={b.basis} className="px-3 py-2">
                      <CpfCell
                        rows={findCpfCell(slabs, cohort, age.key, b.basis)} basis={b.basis} pack={pack}
                        onAdd={() => openBand({ kind: "CPF", initial: { filingStatus: cohort, taxRegime: age.key, assessmentBasis: b.basis } })}
                        onEdit={(slab) => openBand({ kind: "CPF", slab })} onDelete={onDeleteSlab}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="CPF rounding (statutory sequence)" subtitle="Applied by the payroll engine to every CPF row (ZP-SG-ENG-001 SG-008).">
        <ol className="list-decimal space-y-1 pl-5 text-xs text-foreground-secondary">
          <li>Calculate total CPF on the capped Ordinary Wages plus the CPF-subject Additional Wages.</li>
          <li>Round total CPF to the nearest dollar.</li>
          <li>Calculate the employee share.</li>
          <li>Round the employee share down to the nearest dollar.</li>
          <li>Employer share = rounded total − rounded employee share, so the total always reconciles exactly.</li>
        </ol>
      </Card>

      <FormulaInspector pack={pack} />
    </div>
  );
}

function CpfCell({ rows, basis, pack, onAdd, onEdit, onDelete }) {
  if (rows.length === 0) {
    return (
      <div className="space-y-1">
        <Blocked />
        <p className="text-[11px] text-foreground-muted">{CPF_BLOCKED}</p>
        <button type="button" onClick={onAdd} className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline">
          <Plus size={11} /> Add row
        </button>
      </div>
    );
  }
  if (rows.length > 1) return <Blocked>Overlapping rules — configuration invalid</Blocked>;
  const row = rows[0];
  return (
    <div className="space-y-0.5">
      {basis === "NIL" && <p className="font-semibold text-foreground">No CPF</p>}
      {basis === "ER_ONLY" && <p className="font-semibold text-foreground">Employer {formatPct(row.employerRatePct)} × TW</p>}
      {basis === "PHASE_IN" && <p className="font-semibold text-foreground">ER {formatPct(row.employerRatePct)} × TW + {Number(row.ratePct) / 100} × (TW − {formatSgdAuto(row.minAmount)})</p>}
      {basis === "FULL" && <p className="font-semibold text-foreground">EE {formatPct(row.ratePct)} · ER {formatPct(row.employerRatePct)}</p>}
      <p className="font-mono text-[10px] text-foreground-disabled">{row.rateLabel}</p>
      <p className="text-[11px] text-foreground-muted">From {effectiveLabel(row, pack)} · {sourceLabel(row, pack)}</p>
      <div className="flex items-center gap-1 pt-0.5">
        <button type="button" aria-label={`Edit ${row.rateLabel}`} onClick={() => onEdit(row)} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted hover:text-primary"><Pencil size={12} /></button>
        <button type="button" aria-label={`Delete ${row.rateLabel}`} onClick={() => onDelete(row)} className="rounded p-1 text-foreground-disabled hover:bg-error-light hover:text-error"><Trash2 size={12} /></button>
      </div>
    </div>
  );
}

// Backend calculation preview (approved D-A) — the inputs below are sent to
// POST /api/super-admin/compliance/singapore/calculation-preview, which runs
// the production engine against THIS pack's rows and writes nothing. Every
// figure shown comes back from the server; this component does no
// statutory arithmetic of its own.
const PREVIEW_DEFAULTS = {
  payDate: "2026-01-31", gross: "21000", additionalWages: "12000", residencyStatus: "SC", sprEffectiveDate: "",
  contributionArrangement: "", workPass: "NONE", shgFunds: "NONE", dateOfBirth: "1986-03-15", dateOfLeaving: "",
  employmentType: "Full-time", employerHiresForeignWorkers: "", ytdOwSubjectBefore: "0", ytdAwSubjectBefore: "0",
  ytdAwPaidBefore: "0",
};

function FormulaInspector({ pack }) {
  const [form, setForm] = useState(PREVIEW_DEFAULTS);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const orNull = (v) => (v === "" ? null : v);
      setResult(await previewSingaporeCalculation({
        jurisdictionPackId: pack.id, payDate: form.payDate, gross: form.gross, additionalWages: form.additionalWages || "0",
        residencyStatus: form.residencyStatus, sprEffectiveDate: orNull(form.sprEffectiveDate),
        contributionArrangement: orNull(form.contributionArrangement), workPass: form.workPass, shgFunds: form.shgFunds,
        dateOfBirth: orNull(form.dateOfBirth), dateOfLeaving: orNull(form.dateOfLeaving), employmentType: form.employmentType,
        employerHiresForeignWorkers: form.employerHiresForeignWorkers === "" ? null : form.employerHiresForeignWorkers === "true",
        ytdOwSubjectBefore: orNull(form.ytdOwSubjectBefore), ytdAwSubjectBefore: orNull(form.ytdAwSubjectBefore),
        ytdAwPaidBefore: orNull(form.ytdAwPaidBefore), awLedger: [],
      }));
    } catch (err) {
      setError(err.message || "Preview failed.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const input = (id, label, key, props = {}) => (
    <div>
      <label className={labelClass} htmlFor={id}>{label}</label>
      <input id={id} className={inputClass} value={form[key]} onChange={set(key)} {...props} />
    </div>
  );
  const choice = (id, label, key, options) => (
    <div>
      <label className={labelClass} htmlFor={id}>{label}</label>
      <select id={id} className={inputClass} value={form[key]} onChange={set(key)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
  const trace = result?.trace;
  const cpf = trace?.cpf;
  const aw = cpf?.additionalWages;

  return (
    <Card
      title={<span className="flex items-center gap-1.5"><Calculator size={14} aria-hidden="true" /> Calculation preview &amp; formula inspector</span>}
      subtitle="Runs the production payroll engine on the server against this pack's rows (any status) — read-only, nothing is saved. Figures below are the engine's, not the browser's."
    >
      <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {input("sgp-pay-date", "Pay date (wage month)", "payDate", { type: "date" })}
        {input("sgp-gross", "Gross wages (S$)", "gross", { inputMode: "decimal" })}
        {input("sgp-aw", "of which Additional Wages (S$)", "additionalWages", { inputMode: "decimal" })}
        {input("sgp-dob", "Date of birth", "dateOfBirth", { type: "date" })}
        {choice("sgp-res", "Residency", "residencyStatus", [["SC", "Singapore Citizen"], ["SPR", "SPR"], ["FOREIGN", "Foreign"]])}
        {input("sgp-spr", "SPR effective date", "sprEffectiveDate", { type: "date" })}
        {choice("sgp-arr", "SPR arrangement (years 1–2)", "contributionArrangement", [["", "Default (G/G)"], ["GG", "G/G"], ["FG", "F/G"], ["FF", "F/F"]])}
        {choice("sgp-pass", "Work pass", "workPass", [["NONE", "None"], ["EP", "Employment Pass"], ["S_PASS", "S Pass"], ["WORK_PERMIT", "Work Permit"]])}
        {input("sgp-shg", "SHG fund(s)", "shgFunds")}
        {input("sgp-leave", "Last day of employment", "dateOfLeaving", { type: "date" })}
        {input("sgp-ytd-ow", "YTD OW subject before", "ytdOwSubjectBefore", { inputMode: "decimal" })}
        {input("sgp-ytd-aw", "YTD AW subject before", "ytdAwSubjectBefore", { inputMode: "decimal" })}
        {input("sgp-ytd-awp", "YTD AW paid before", "ytdAwPaidBefore", { inputMode: "decimal" })}
        {choice("sgp-fw", "Employer hires foreign workers (LQS)", "employerHiresForeignWorkers", [["", "Not supplied"], ["true", "Yes"], ["false", "No"]])}
      </div>
      <button type="button" onClick={run} disabled={loading}
        className="mb-3 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
        {loading ? "Calculating…" : "Run backend preview"}
      </button>
      <div aria-live="polite">
        {error && <Blocked>{error}</Blocked>}
        {result?.blocked && <Blocked>{result.blockedReason}</Blocked>}
        {result && !result.blocked && (
          <div className="space-y-3 text-xs">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-4">
              <InspectorRow term="Employee CPF" value={formatSgdAuto(result.result.employeeCpf)} />
              <InspectorRow term="Employer CPF" value={formatSgdAuto(result.result.employerCpf)} />
              <InspectorRow term="SHG (employee)" value={formatSgdAuto(result.result.shg)} />
              <InspectorRow term="SDL (employer)" value={formatSgdAuto(result.result.sdl)} />
              <InspectorRow term="FWL (employer)" value={formatSgdAuto(result.result.fwl)} />
              <InspectorRow term="Net pay" value={formatSgdAuto(result.result.netPay)} />
              <InspectorRow term="Employer cost" value={formatSgdAuto(trace.result.employerCost)} />
              <InspectorRow term="Pack" value={`${result.pack.packId} v${result.pack.version} (${result.pack.status})`} />
            </dl>
            {cpf?.rule ? (
              <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 border-t border-border-light pt-2 sm:grid-cols-2">
                <InspectorRow term="Cohort / age band" value={`${trace.cohort} · ${cpf.ageBand}`} />
                <InspectorRow term="Rule" value={cpf.rule} mono />
                <InspectorRow term="Formula type" value={cpf.formulaType} />
                <InspectorRow term="Rates" value={`Employee ${formatPct(cpf.employeeRatePct)} · Employer ${formatPct(cpf.employerRatePct)}`} />
                <InspectorRow term="OW / ceiling / subject" value={`${formatSgdAuto(cpf.owActual)} / ${formatSgdAuto(cpf.owCeiling)} / ${formatSgdAuto(cpf.owSubject)}`} />
                {aw?.ceilingBasis && (
                  <InspectorRow term={`AW ceiling (${aw.ceilingBasis})`}
                    value={`${formatSgdAuto(aw.annualWageCeiling)} − ${formatSgdAuto(aw.annualOwUsed)} = ${formatSgdAuto(aw.awCeiling)}`} />
                )}
                {aw && <InspectorRow term="AW paid / subject" value={`${formatSgdAuto(aw.awPaid)} / ${formatSgdAuto(aw.awSubjectThisPayment)}`} />}
                {aw?.shortfallAwSubject && aw.shortfallAwSubject !== "0" && (
                  <InspectorRow term="True-up shortfall AW" value={formatSgdAuto(aw.shortfallAwSubject)} />
                )}
                {aw?.excess && <InspectorRow term="Excess AW" value={`${formatSgdAuto(aw.excess.excessAwSubject)} — refund application`} />}
                <InspectorRow term="Rounding" value={`total ${cpf.rounding.totalRaw} → ${cpf.rounding.total}; employee ${cpf.rounding.employeeRaw} → ${cpf.rounding.employee}; employer ${cpf.rounding.employer}`} />
                <InspectorRow term="Effective" value={effectiveLabel(null, pack)} />
                <InspectorRow term="Authority" value={pack.regulatoryAuthority || "—"} />
              </dl>
            ) : (
              <p className="text-foreground-muted">{cpf?.detail}</p>
            )}
            <p className="text-foreground-muted">
              LQS: {trace.lqs.status}{trace.lqs.threshold ? ` (threshold ${formatSgdAuto(trace.lqs.threshold)})` : ""} · FWL: {trace.fwl.status} · IR21: {trace.ir21.status}
            </p>
            {cpf?.specClarification && <p className="text-[11px] text-foreground-disabled">{cpf.specClarification}</p>}
          </div>
        )}
      </div>
    </Card>
  );
}

function InspectorRow({ term, value, mono }) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="text-foreground-muted">{term}:</dt>
      <dd className={`font-semibold text-foreground ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}

// ── SDL ──────────────────────────────────────────────────────────────────

function SdlSection(props) {
  return (
    <Card title="Skills Development Levy" subtitle="EMPLOYER COST — never an employee deduction, and legally distinct from CPF and SHG. Applies to every employee working in Singapore, including foreign employees with nil CPF.">
      <ParameterTable
        caption="SDL parameters" {...props}
        keys={[
          { key: "sdl", label: "SDL rate (employer)" },
          { key: "sdl_min_monthly", label: "SDL minimum per employee" },
          { key: "sdl_max_monthly", label: "SDL maximum per employee" },
        ]}
      />
      <p className="mt-2 text-[11px] text-foreground-muted">The authority&apos;s round-down applies to the employer&apos;s monthly total (SG_SDL_MONTHLY statutory output), never per payslip; the CPF EZPay contribution file is {NOT_BUILT.cpfEzpay}.</p>
    </Card>
  );
}

// ── SHG ──────────────────────────────────────────────────────────────────

function ShgSection({ pack, slabs, openBand, onDeleteSlab }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-foreground-muted">
        Employee deductions by fund. Eligibility comes from an authority/HR-derived fund code on the employee — never from race or religion
        attributes. More than one fund may apply.
      </p>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {SHG_FUNDS.map((fund) => {
          const rows = shgRows(slabs, fund.key);
          return (
            <Card
              key={fund.key} title={fund.label} subtitle="Monthly contribution by total wages"
              action={(
                <button type="button" onClick={() => openBand({ kind: "SHG", initial: { filingStatus: fund.key } })}
                  className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                  <Plus size={12} /> Add band
                </button>
              )}
            >
              {rows.length === 0 ? <Blocked /> : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-xs">
                    <caption className="sr-only">{fund.label} contribution bands</caption>
                    <thead className="bg-background text-left text-foreground-muted">
                      <tr>
                        <th scope="col" className="px-3 py-2">Total wages</th>
                        <th scope="col" className="px-3 py-2">Monthly</th>
                        <th scope="col" className="px-3 py-2">Effective</th>
                        <th scope="col" className="w-16 px-3 py-2"><span className="sr-only">Actions</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.id} className="border-t border-border-light">
                          <th scope="row" className="px-3 py-1.5 text-left font-normal text-foreground">{describeBand(r)}</th>
                          <td className="px-3 py-1.5 font-semibold text-foreground">{formatSgdAuto(r.flatAmount)}</td>
                          <td className="px-3 py-1.5 text-foreground-secondary">{effectiveLabel(r, pack)}</td>
                          <td className="px-3 py-1.5">
                            <div className="flex items-center gap-1">
                              <button type="button" aria-label={`Edit ${fund.label} band ${describeBand(r)}`} onClick={() => openBand({ kind: "SHG", slab: r })} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted hover:text-primary"><Pencil size={12} /></button>
                              <button type="button" aria-label={`Delete ${fund.label} band ${describeBand(r)}`} onClick={() => onDeleteSlab(r)} className="rounded p-1 text-foreground-disabled hover:bg-error-light hover:text-error"><Trash2 size={12} /></button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ── Foreign workforce ────────────────────────────────────────────────────

function ForeignWorkforceSection(props) {
  const sPass = rateByKey(props.rates, "fwl_s_pass_monthly");
  const lqs = rateByKey(props.rates, "lqs_full_time_monthly");
  const wpRows = (props.rates || []).filter((r) => (r.componentKey || "").startsWith("fwl_wp__"))
    .sort((a, b) => a.componentKey.localeCompare(b.componentKey));
  const passes = [
    { key: "EP", label: "Employment Pass", levy: "Nil" },
    { key: "S_PASS", label: "S Pass", levy: sPass ? `${formatSgdAuto(sPass.flatAmount)} / month` : null },
    { key: "WORK_PERMIT", label: "Work Permit", levy: "Authority bill — sector / skill / quota-tier driven; not calculated from salary" },
  ];
  return (
    <div className="space-y-4">
      <Card title="Work-pass treatment" subtitle="MOM levy = EMPLOYER COST. Singapore law prohibits recovering levy costs from migrant-worker wages — it is never an employee deduction.">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <caption className="sr-only">Payroll treatment by work pass</caption>
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th scope="col" className="px-3 py-2">Work pass</th>
                <th scope="col" className="px-3 py-2">CPF</th>
                <th scope="col" className="px-3 py-2">SDL</th>
                <th scope="col" className="px-3 py-2">MOM levy (employer cost)</th>
                <th scope="col" className="px-3 py-2">IR21</th>
                <th scope="col" className="px-3 py-2">LQS / PWM impact</th>
              </tr>
            </thead>
            <tbody>
              {passes.map((p) => (
                <tr key={p.key} className="border-t border-border-light align-top">
                  <th scope="row" className="px-3 py-2 text-left font-semibold text-foreground">{p.label}</th>
                  <td className="px-3 py-2 text-foreground-secondary">None unless the employee becomes an SPR</td>
                  <td className="px-3 py-2 text-foreground-secondary">Applies</td>
                  <td className="px-3 py-2 text-foreground-secondary">{p.levy || <Blocked />}</td>
                  <td className="px-3 py-2 text-foreground-secondary">May apply on cessation / departure — {IR21_WORKFLOW}</td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    Employer hiring foreign workers must meet LQS{lqs ? ` (${formatSgdAuto(lqs.flatAmount)} FT)` : ""} / PWM for local employees
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-foreground-muted">MOM levy bill import / reconciliation: {NOT_BUILT.momLevyImport}. Work Permit levy rows in this pack: {wpRows.length}{wpRows.length ? "" : " — not configured"}; values MOM does not publish stay unconfigured (BLOCKED), never defaulted.</p>
      </Card>
      <Card title="Levy configuration">
        <ParameterTable caption="Foreign worker levy" {...props}
          keys={[{ key: "fwl_s_pass_monthly", label: "Foreign Worker Levy — S Pass (monthly)" },
            ...wpRows.map((r) => ({ key: r.componentKey, label: r.label || r.componentKey }))]} />
      </Card>
    </div>
  );
}

// ── LQS / PWM ────────────────────────────────────────────────────────────

function LqsSection(props) {
  return (
    <div className="space-y-4">
      <Card title="LQS / PWM compliance" subtitle="Conditional local-wage floors for employers hiring foreign workers — there is no universal Singapore minimum wage.">
        <ParameterTable
          caption="Local Qualifying Salary" {...props}
          keys={[
            { key: "lqs_full_time_monthly", label: "LQS — full-time (monthly)" },
            { key: "lqs_part_time_hourly", label: "LQS — part-time (hourly)" },
          ]}
          format={{ lqs_part_time_hourly: (r) => `${formatSgdAuto(r.flatAmount)} / hour` }}
        />
        <p className="mt-2 text-[11px] text-foreground-muted">
          Each row applies only within its own effective window (the full-time S$1,600 row to 30 Jun 2026, S$1,800
          from 1 Jul 2026). The part-time rate before 1 Jul 2026 is not stated by MOM: BLOCKED — AUTHORITATIVE
          VALUE REQUIRED, never back-filled from the current value.
        </p>
      </Card>
      <Card title="Progressive Wage Model" subtitle="Sector × occupation × job level wage floors.">
        <Blocked>No PWM sector tables configured — an applicable PWM cohort blocks &ldquo;compliant&rdquo; status.</Blocked>
      </Card>
    </div>
  );
}

// ── IRAS AIS ─────────────────────────────────────────────────────────────

function IrasSection(props) {
  return (
    <Card title="IRAS annual reporting (AIS)" subtitle="Year-end employment-income reporting — never a monthly withholding. 2026 income is reported for YA2027; IR8A with Appendix 8A (benefits-in-kind) and 8B (share gains).">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-foreground-muted">IR8A data extract:</span> <StatusText label={IR8A_STATUS} />
        <span className="text-foreground-muted">AIS-API submission:</span> <StatusText label={NOT_BUILT.aisApi} />
      </div>
      <ParameterTable
        caption="IRAS AIS configuration" {...props}
        keys={[
          { key: "ais_mandatory_employee_threshold", label: "AIS mandatory threshold (employees)" },
          { key: "ais_submission_mode", label: "AIS submission mode" },
        ]}
        format={{ ais_mandatory_employee_threshold: (r) => `${Number(r.flatAmount)}+ employees` }}
      />
      <p className="mt-2 text-[11px] text-foreground-muted">The submission deadline comes from the Statutory Filing Calendar (see Overview → Compliance clocks).</p>
    </Card>
  );
}

// ── IR21 ─────────────────────────────────────────────────────────────────

function Ir21Section(props) {
  return (
    <div className="space-y-4">
      <Card title="IR21 tax clearance" subtitle="Event-driven cash control for non-citizen employees on cessation, overseas posting or long departure — not a locally calculated tax.">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-foreground-muted">Workflow:</span> <StatusText label={IR21_WORKFLOW} />
          <span className="text-foreground-muted">— no filing, hold or release actions exist in this phase.</span>
        </div>
        <ParameterTable
          caption="IR21 configuration" {...props}
          keys={[
            { key: "ir21_departure_trigger_months", label: "Trigger: departure longer than (months)" },
            { key: "ir21_filing_lead_months", label: "Filing target: months before cessation / departure" },
          ]}
          format={{
            ir21_departure_trigger_months: (r) => `> ${Number(r.flatAmount)} months`,
            ir21_filing_lead_months: (r) => `≥ ${Number(r.flatAmount)} month(s)`,
          }}
        />
      </Card>
      <Card title="IR21 case lifecycle" subtitle="Tracked per employee by each organization's IR21 Tax Clearance tab; pay is held until a distinct approver releases it.">
        <ol className="flex flex-wrap gap-1.5" aria-label="IR21 statuses in order">
          {IR21_STATUSES.map((s) => (
            <li key={s} className="rounded-md border border-border-light bg-surface-muted px-2 py-0.5 font-mono text-[10px] text-foreground-secondary">{s}</li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

import { useState } from "react";
import { ShieldAlert, X } from "lucide-react";
import {
  closeBrAlimonyOrder, createEmployeeStatutoryProfile, getBrEmployer, getBrEmployeeReadiness, getBrEmployeeRecord,
  listBrEmployers, recordBrAlimonyOrder, recordBrConcurrentInss, recordBrValeTransporte,
} from "../../../service/payrollService";
import { Field, Messages, Table, btnPrimary, card, input, useAction, useLoad } from "../../../components/jurisdiction/brazil/brShared";
import { Badge, MiniForm, ReadinessDateBar } from "../../../components/jurisdiction/brazil/employer/brEmployerShared";
import { localToday } from "../../../components/jurisdiction/brazil/employer/brEmployerUtils";

// Brazil employee record (ZP-BR-ENG-001 §7 — the spec's "People → Employee →
// Payroll → Brazil"). FACTS only: no INSS/IRRF/FGTS figure, no alimony
// deduction and no vale-transporte 6% cap is typed here (the engine derives
// them in Phase 5). CPF / PIS-NIS / PIX / account arrive masked from the API.
// Each save is a new effective-dated version; nothing is edited in place.
const camel = (k) => k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());

const ESOCIAL_CATEGORIES = ["101", "103"];
const CONTRACT_TYPES = ["INDEFINITE", "DETERMINED", "INTERMITTENT"];
const ALIMONY_METHODS = ["FIXED_AMOUNT", "PERCENTAGE"];
const ALIMONY_BASES = ["GROSS", "NET", "BASE_INSS", "BASE_IRRF"];

const PROFILE_FIELDS = [
  ["Employment", [
    ["br_esocial_category", "eSocial category (Tabela 01)", "select", ESOCIAL_CATEGORIES],
    ["br_cbo_code", "CBO code", "text"], ["br_contract_type", "Contract type", "select", CONTRACT_TYPES],
    ["br_weekly_hours", "Weekly hours (≤ 44)", "number"],
    ["br_simplified_irrf_opt_out", "Simplified IRRF opted out", "checkbox"],
  ]],
  ["IRRF dependants (fact only — the engine computes the deduction)", [
    ["br_irrf_dependents_count", "Dependants count", "number"],
    ["br_irrf_dependents_evidence_ref", "Evidence reference", "text"],
  ]],
  ["Salário-família dependants", [
    ["br_salario_familia_dependents_count", "Dependants count", "number"],
    ["br_salario_familia_dependents_evidence_ref", "Evidence reference", "text"],
  ]],
];

function Section({ title, children }) {
  return (
    <fieldset className="rounded-xl border border-border p-4">
      <legend className="px-1 text-[12px] font-semibold text-foreground">{title}</legend>
      <div className="flex flex-col gap-3">{children}</div>
    </fieldset>
  );
}

export default function BrazilStatutoryProfilePanel({ employee, onClose }) {
  const [record, recordError, , reload] = useLoad(() => getBrEmployeeRecord(employee.id), [employee.id]);
  const [employers] = useLoad(() => listBrEmployers(), []);
  const [employerId, setEmployerId] = useState(null);
  const effectiveEmployer = employerId ?? employers?.[0]?.employerId ?? null;
  const [detail] = useLoad(() => (effectiveEmployer ? getBrEmployer(effectiveEmployer) : Promise.resolve(null)),
    [effectiveEmployer]);
  const [on, setOn] = useState(localToday);
  const [readiness, readinessError, , reloadReadiness] = useLoad(() => getBrEmployeeReadiness(employee.id, on),
    [employee.id, on]);
  const { run, error, notice, busy } = useAction(() => { reload(); reloadReadiness(); });
  const [changes, setChanges] = useState({});
  const [effectiveFrom, setEffectiveFrom] = useState(localToday);

  const versions = record?.profiles || [];
  const current = versions[versions.length - 1] || {};
  const value = (k) => (k in changes ? changes[k] : current[camel(k)] ?? "");
  const setFact = (k) => (e) => {
    const next = e.target.type === "checkbox" ? e.target.checked : (e.target.value === "" ? null : e.target.value);
    setChanges((c) => ({ ...c, [k]: next }));
  };

  const save = async (e) => {
    e.preventDefault();
    const payload = { countryCode: "BR", effectiveFrom };
    Object.entries(changes).forEach(([k, v]) => { payload[camel(k)] = v; });
    if (await run(() => createEmployeeStatutoryProfile(employee.id, payload),
      `New Brazil profile version recorded, effective ${effectiveFrom}. Earlier versions are unchanged.`)) {
      setChanges({});
    }
  };

  const establishments = (detail?.establishments || []).filter((est) => !est.activeTo);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col border-l border-border bg-surface" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-[15px] font-semibold text-foreground">Brazil statutory profile</h2>
          <button type="button" className="rounded-lg border border-border p-1.5 text-foreground-muted hover:bg-surface-muted" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="flex flex-col gap-4 overflow-y-auto p-6">
          <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3" data-testid="br-profile-warning">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <p className="text-[12px] text-foreground">
              Facts only. INSS, IRRF, FGTS, the alimony deduction and the vale-transporte 6% cap are computed by the
              engine (Phase 5); every Brazil payroll path stays blocked until the release gates are signed.
            </p>
          </div>

          {record && (
            <section className={card} data-testid="br-identifiers">
              <h3 className="text-[13px] font-semibold text-foreground">Identity (held masked on the employee record)</h3>
              <div className="mt-2 flex flex-wrap gap-4 text-[12px] text-foreground">
                {["cpf", "pis_nis", "pix_key", "bank_account"].map((k) => (
                  <span key={k}><span className="font-semibold uppercase">{k}</span> {record.identifiers[k] || "not recorded"}</span>
                ))}
              </div>
            </section>
          )}

          <Messages error={recordError || error || undefined} notice={notice || undefined} />

          <form className="flex flex-col gap-4" onSubmit={save} data-testid="br-profile-form">
            <section className={card}>
              <h3 className="text-[13px] font-semibold text-foreground">Employment</h3>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field label="Legal employer">
                  <select className={input} value={effectiveEmployer ?? ""} onChange={(e) => setEmployerId(Number(e.target.value))}>
                    {(employers || []).map((e) => <option key={e.employerId} value={e.employerId}>{e.legalName || e.cnpjRoot}</option>)}
                  </select>
                </Field>
                <Field label="Establishment (active)">
                  <select className={input} value={value("br_establishment_id")} onChange={setFact("br_establishment_id")}>
                    <option value="">—</option>
                    {establishments.map((est) => <option key={est.id} value={est.id}>{est.establishmentName} ({est.cnpj})</option>)}
                  </select>
                </Field>
              </div>
            </section>

            {PROFILE_FIELDS.map(([title, fields]) => (
              <section key={title} className={card}>
                <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  {fields.map(([k, label, type, choices]) => (
                    <Field key={k} label={label}>
                      {type === "select" ? (
                        <select className={input} value={value(k)} onChange={setFact(k)}>
                          <option value="">—</option>
                          {choices.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      ) : type === "checkbox" ? (
                        <input type="checkbox" checked={Boolean(value(k))} onChange={setFact(k)} />
                      ) : (
                        <input className={input} type={type} value={value(k)} onChange={setFact(k)} />
                      )}
                    </Field>
                  ))}
                </div>
              </section>
            ))}

            <div className="flex flex-wrap items-end gap-3">
              <Field label="Effective from">
                <input type="date" className={input} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
              </Field>
              <button type="submit" className={btnPrimary} disabled={busy}>Record new version</button>
            </div>
          </form>

          <section className={card}>
            <h3 className="text-[13px] font-semibold text-foreground">Versions</h3>
            <div className="mt-2">
              <Table rows={versions} empty="No Brazil profile version yet." columns={[
                { key: "effectiveFrom", label: "From" }, { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
                { key: "brEsocialCategory", label: "Category" }, { key: "brCboCode", label: "CBO" },
                { key: "brContractType", label: "Contract" }, { key: "brWeeklyHours", label: "Weekly hours" },
              ]} />
            </div>
          </section>

          <section className={card} data-testid="br-concurrent-inss">
            <h3 className="text-[13px] font-semibold text-foreground">Concurrent-employment INSS (BR-009)</h3>
            <div className="mt-2">
              <Table rows={record?.concurrentInssDeclarations || []} empty="No declaration recorded." columns={[
                { key: "competenceMonth", label: "Competência" }, { key: "baseExternal", label: "External base" },
                { key: "deductedExternal", label: "Deducted" },
                { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
              ]} />
            </div>
            <div className="mt-3">
              <MiniForm testId="br-inss-form" submitLabel="Record declaration" busy={busy}
                fields={[
                  { key: "competenceMonth", label: "Competência", type: "date", required: true },
                  { key: "baseExternal", label: "External base", type: "number" },
                  { key: "deductedExternal", label: "External deducted", type: "number" },
                  { key: "evidenceRef", label: "Evidence reference" },
                ]}
                onSubmit={(s) => run(() => recordBrConcurrentInss(employee.id, s), "Concurrent-employment INSS declaration recorded.")} />
            </div>
          </section>

          <section className={card} data-testid="br-alimony">
            <h3 className="text-[13px] font-semibold text-foreground">Court-ordered alimony</h3>
            <div className="mt-2">
              <Table rows={record?.alimonyOrders || []} empty="No alimony order recorded." columns={[
                { key: "orderReference", label: "Reference" }, { key: "method", label: "Method" },
                { key: "fixedAmount", label: "Fixed" }, { key: "percentage", label: "Pct" }, { key: "base", label: "Base" },
                { key: "effectiveFrom", label: "From" }, { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
                { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
              ]} />
            </div>
            <div className="mt-3 flex flex-col gap-3">
              <MiniForm testId="br-alimony-form" submitLabel="Record alimony order" busy={busy}
                fields={[
                  { key: "orderReference", label: "Order reference", required: true },
                  { key: "method", label: "Method", type: "select", options: ALIMONY_METHODS, required: true },
                  { key: "fixedAmount", label: "Fixed amount", type: "number" },
                  { key: "percentage", label: "Percentage", type: "number" },
                  { key: "base", label: "Base", type: "select", options: ALIMONY_BASES },
                  { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
                  { key: "evidenceRef", label: "Evidence reference" },
                ]}
                onSubmit={(s) => run(() => recordBrAlimonyOrder(employee.id, s), "Alimony order recorded.")} />
              {(record?.alimonyOrders || []).some((a) => a.status === "ACTIVE") && (
                <MiniForm testId="br-alimony-close" submitLabel="Close order" busy={busy}
                  fields={[
                    { key: "orderId", label: "Order", type: "select", required: true,
                      options: (record.alimonyOrders || []).filter((a) => a.status === "ACTIVE").map((a) => ({ value: String(a.id), label: a.orderReference })) },
                    { key: "effectiveTo", label: "Close from", type: "date", required: true },
                  ]}
                  onSubmit={(s) => run(() => closeBrAlimonyOrder(Number(s.orderId), { effectiveTo: s.effectiveTo }), "Alimony order closed.")} />
              )}
            </div>
          </section>

          <section className={card} data-testid="br-vale-transporte">
            <h3 className="text-[13px] font-semibold text-foreground">Vale-transporte elections</h3>
            <div className="mt-2">
              <Table rows={record?.valeTransporteElections || []} empty="No vale-transporte election recorded." columns={[
                { key: "elected", label: "Elected", render: (r) => (r.elected ? "Yes" : "No") },
                { key: "dailyCost", label: "Daily cost" }, { key: "effectiveFrom", label: "From" },
                { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
                { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
              ]} />
            </div>
            <div className="mt-3">
              <MiniForm testId="br-vt-form" submitLabel="Record election" busy={busy}
                fields={[
                  { key: "elected", label: "Elected", type: "checkbox" },
                  { key: "dailyCost", label: "Declared daily cost", type: "number" },
                  { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
                  { key: "evidenceRef", label: "Evidence reference" },
                ]}
                onSubmit={(s) => run(() => recordBrValeTransporte(employee.id, s), "Vale-transporte election recorded.")} />
            </div>
          </section>

          <section className={card} data-testid="br-employee-readiness">
            <h3 className="text-[13px] font-semibold text-foreground">Readiness</h3>
            <div className="mt-2"><ReadinessDateBar on={on} onChange={setOn} /></div>
            <Messages error={readinessError || undefined} />
            {readiness && (
              <div className="mt-2">
                <Table rows={readiness.items} rowKey={(r) => r.key} columns={[
                  { key: "label", label: "Item" }, { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
                  { key: "detail", label: "Detail" },
                  { key: "gates", label: "Feeds gate", render: (r) => (r.gates?.length ? r.gates.join(", ") : "unmapped") },
                ]} />
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

import React, { useEffect, useState } from "react";
import { X, ShieldAlert, History, Upload } from "lucide-react";
import {
  getEmployeeStatutoryProfile,
  getEmployeeStatutoryProfileHistory,
  createEmployeeStatutoryProfile,
  importEmployeeElstamPayload,
  getEmployeeElstamImportAttempts,
} from "../../../service/payrollService";
import { listU1Tariffs } from "../../../service/superAdminService";

// Matches backend/app/modules/payroll/engine/germany_pap/core.py's own
// CHURCH_TAX_LAND_RATES keys exactly (ZP-TAX-DE-2026-001 §3/§8) — not the
// generic address-region list in utils/registrationRegions.js, which has
// no DE-XX codes and is used for postal addresses, not statutory data.
const CHURCH_TAX_LAENDER = [
  { code: "DE-BW", label: "Baden-Württemberg (8%)" },
  { code: "DE-BY", label: "Bavaria (8%)" },
  { code: "DE-BE", label: "Berlin (9%)" },
  { code: "DE-BB", label: "Brandenburg (9%)" },
  { code: "DE-HB", label: "Bremen (9%)" },
  { code: "DE-HH", label: "Hamburg (9%)" },
  { code: "DE-HE", label: "Hesse (9%)" },
  { code: "DE-MV", label: "Mecklenburg-Western Pomerania (9%)" },
  { code: "DE-NI", label: "Lower Saxony (9%)" },
  { code: "DE-NW", label: "North Rhine-Westphalia (9%)" },
  { code: "DE-RP", label: "Rhineland-Palatinate (9%)" },
  { code: "DE-SL", label: "Saarland (9%)" },
  { code: "DE-SN", label: "Saxony (9%)" },
  { code: "DE-ST", label: "Saxony-Anhalt (9%)" },
  { code: "DE-SH", label: "Schleswig-Holstein (9%)" },
  { code: "DE-TH", label: "Thuringia (9%)" },
];

const TAX_CLASSES = ["I", "II", "III", "IV", "V", "VI"];
const EMPLOYMENT_CLASSES = ["REGULAR", "MINIJOB", "MIDIJOB"];

function emptyForm() {
  const today = new Date().toISOString().slice(0, 10);
  return {
    effectiveFrom: today,
    reason: "",
    deTaxClass: "",
    deFactor: "",
    deChurchTaxLiable: false,
    deChurchTaxLand: "",
    // Master audit gap closure — these were real, live-consumed backend
    // columns (resolve_germany_church_tax_exception's own inputs) with no
    // schema field and no form field anywhere, making every published
    // church-tax exception (e.g. Bad Wimpfen) permanently unreachable.
    deChurchTaxDenomination: "",
    deChurchTaxMunicipalityPostalCode: "",
    deChildCount: "",
    deChildless: false,
    deSaxony: false,
    deHealthInsuranceStatus: "",
    deHealthFundCode: "",
    deU1TariffId: "",
    dePensionInsuranceExempt: false,
    deUnemploymentInsuranceExempt: false,
    deEmploymentClassification: "",
    deVocationalTrainee: false,
    deElstamSource: "",
    deElstamFallbackReason: "",
    deMainEmployment: "", // "" = not recorded, "true" = main, "false" = secondary
    deZkfOverride: "",
    deJfreib: "",
    deLzzfreib: "",
    deJhinzu: "",
    deLzzhinzu: "",
    dePkpv: "",
    dePkpvagz: "",
    // Phase 8AB — explicit, effective-dated overtime/premium Grundlohn
    // source. Never auto-calculated from salary.
    deGrundlohnHourly: "",
  };
}

// EmployeeStatutoryProfileResponse (backend) uses camelCase aliases already
// — this maps a response row straight into the edit form's shape so
// "start a new version from the current one" doesn't require re-typing
// everything that hasn't changed.
function formFromProfile(profile) {
  if (!profile) return emptyForm();
  const base = emptyForm();
  return {
    ...base,
    deTaxClass: profile.deTaxClass || "",
    deFactor: profile.deFactor ?? "",
    deChurchTaxLiable: !!profile.deChurchTaxLiable,
    deChurchTaxLand: profile.deChurchTaxLand || "",
    deChurchTaxDenomination: profile.deChurchTaxDenomination || "",
    deChurchTaxMunicipalityPostalCode: profile.deChurchTaxMunicipalityPostalCode || "",
    deChildCount: profile.deChildCount ?? "",
    deChildless: !!profile.deChildless,
    deSaxony: !!profile.deSaxony,
    deHealthInsuranceStatus: profile.deHealthInsuranceStatus || "",
    deHealthFundCode: profile.deHealthFundCode || "",
    deU1TariffId: profile.deU1TariffId || "",
    dePensionInsuranceExempt: !!profile.dePensionInsuranceExempt,
    deUnemploymentInsuranceExempt: !!profile.deUnemploymentInsuranceExempt,
    deEmploymentClassification: profile.deEmploymentClassification || "",
    deVocationalTrainee: !!profile.deVocationalTrainee,
    deElstamSource: profile.deElstamSource || "",
    deElstamFallbackReason: profile.deElstamFallbackReason || "",
    deMainEmployment: profile.deMainEmployment === true ? "true" : profile.deMainEmployment === false ? "false" : "",
    deZkfOverride: profile.deZkfOverride ?? "",
    deJfreib: profile.deJfreib ?? "",
    deLzzfreib: profile.deLzzfreib ?? "",
    deJhinzu: profile.deJhinzu ?? "",
    deLzzhinzu: profile.deLzzhinzu ?? "",
    dePkpv: profile.dePkpv ?? "",
    dePkpvagz: profile.dePkpvagz ?? "",
    deGrundlohnHourly: profile.deGrundlohnHourly ?? "",
  };
}

// Converts the form's string-typed inputs into the API payload shape.
// Blank string -> undefined (omit) for every optional field, never "" or
// NaN — the backend treats an omitted field as "not set," matching this
// form's own "not recorded" semantics.
function buildPayload(form) {
  const num = (v) => (v === "" || v === null || v === undefined ? undefined : Number(v));
  const str = (v) => (v === "" ? undefined : v);
  const bool = (v) => !!v;
  return {
    effectiveFrom: form.effectiveFrom,
    reason: str(form.reason),
    deTaxClass: str(form.deTaxClass),
    deFactor: num(form.deFactor),
    deChurchTaxLiable: bool(form.deChurchTaxLiable),
    deChurchTaxLand: form.deChurchTaxLiable ? str(form.deChurchTaxLand) : undefined,
    deChurchTaxDenomination: form.deChurchTaxLiable ? str(form.deChurchTaxDenomination) : undefined,
    deChurchTaxMunicipalityPostalCode: form.deChurchTaxLiable ? str(form.deChurchTaxMunicipalityPostalCode) : undefined,
    deChildCount: num(form.deChildCount),
    deChildless: bool(form.deChildless),
    deSaxony: bool(form.deSaxony),
    deHealthInsuranceStatus: str(form.deHealthInsuranceStatus),
    deHealthFundCode: str(form.deHealthFundCode),
    deU1TariffId: str(form.deU1TariffId),
    dePensionInsuranceExempt: bool(form.dePensionInsuranceExempt),
    deUnemploymentInsuranceExempt: bool(form.deUnemploymentInsuranceExempt),
    deEmploymentClassification: str(form.deEmploymentClassification),
    deVocationalTrainee: bool(form.deVocationalTrainee),
    deElstamSource: str(form.deElstamSource),
    deElstamFallbackReason: form.deElstamSource === "FALLBACK_CERTIFICATE" ? str(form.deElstamFallbackReason) : undefined,
    deMainEmployment: form.deMainEmployment === "" ? undefined : form.deMainEmployment === "true",
    deZkfOverride: num(form.deZkfOverride),
    deJfreib: num(form.deJfreib),
    deLzzfreib: num(form.deLzzfreib),
    deJhinzu: num(form.deJhinzu),
    deLzzhinzu: num(form.deLzzhinzu),
    dePkpv: num(form.dePkpv),
    dePkpvagz: num(form.dePkpvagz),
    deGrundlohnHourly: num(form.deGrundlohnHourly),
    // Only meaningful for a structured ELStAM import (see the STRUCTURED
    // entry-mode branch below, which sends these two under schemaVersion/
    // importReference at the top level of the import request, not here) —
    // omitted from a plain manual-entry create.
  };
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

const inputCls =
  "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground outline-none transition-colors focus:border-primary";
const selectCls = inputCls;

export default function GermanyStatutoryProfilePanel({ employee, onClose }) {
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [importAttempts, setImportAttempts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [showImportLog, setShowImportLog] = useState(false);

  // "MANUAL" writes a plain new version (de_elstam_source records
  // provenance as usual). "STRUCTURED_IMPORT" sends the SAME field set
  // through the dedicated import boundary (schema_version/import_reference
  // recorded, and — on rejection — the failed attempt itself is still
  // logged). Neither mode ever calls ELSTER/BZSt; both are caller-supplied
  // structured data, exactly like the rest of this form.
  const [entryMode, setEntryMode] = useState("MANUAL");
  const [form, setForm] = useState(emptyForm());
  const [schemaVersion, setSchemaVersion] = useState("ELSTAM-2026-01");
  const [importReference, setImportReference] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState("");

  // Phase 8X — fund-scoped U1 tariff selector. Only PUBLISHED
  // GermanyHealthFundU1Tariff rows for the currently selected health fund
  // are offered; the value stored is the tariff identifier (de_u1_tariff_id),
  // matching the backend's employment-selection contract exactly.
  const [u1Tariffs, setU1Tariffs] = useState([]);

  useEffect(() => {
    let cancelled = false;
    const fundCode = (form.deHealthFundCode || "").trim();
    if (!fundCode) {
      setU1Tariffs([]);
      set("deU1TariffId", "");
      return undefined;
    }
    listU1Tariffs(fundCode)
      .then((rows) => {
        if (cancelled) return;
        const published = (rows || [])
          .filter((r) => r.status === "PUBLISHED")
          .sort((a, b) => (a.tariffIdentifier || "").localeCompare(b.tariffIdentifier || ""));
        setU1Tariffs(published);
        const current = (form.deU1TariffId || "").trim();
        if (current && !published.some((r) => r.tariffIdentifier === current)) {
          set("deU1TariffId", "");
        }
      })
      .catch(() => {
        if (!cancelled) setU1Tariffs([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.deHealthFundCode]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError("");
      try {
        const [current, hist] = await Promise.all([
          getEmployeeStatutoryProfile(employee.id).catch(() => null),
          getEmployeeStatutoryProfileHistory(employee.id).catch(() => []),
        ]);
        if (cancelled) return;
        setProfile(current);
        setHistory(hist || []);
        setForm(formFromProfile(current));
      } catch (err) {
        if (!cancelled) setLoadError(err.message || "Could not load this employee's Germany statutory profile.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [employee.id]);

  function loadImportAttempts() {
    getEmployeeElstamImportAttempts(employee.id)
      .then((rows) => setImportAttempts(rows || []))
      .catch(() => setImportAttempts([]));
  }

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setSaveError("");
    setSaveSuccess("");
    try {
      const payload = buildPayload(form);
      let result;
      if (entryMode === "STRUCTURED_IMPORT") {
        const attempt = await importEmployeeElstamPayload(employee.id, {
          schemaVersion: schemaVersion || "ELSTAM-2026-01",
          importReference: importReference || undefined,
          payload,
        });
        setSaveSuccess("ELStAM structured import applied — a new statutory profile version was created.");
        result = attempt;
      } else {
        await createEmployeeStatutoryProfile(employee.id, payload);
        setSaveSuccess("New statutory profile version saved.");
      }
      const [current, hist] = await Promise.all([
        getEmployeeStatutoryProfile(employee.id).catch(() => null),
        getEmployeeStatutoryProfileHistory(employee.id).catch(() => []),
      ]);
      setProfile(current);
      setHistory(hist || []);
      setForm(formFromProfile(current));
      if (showImportLog) loadImportAttempts();
    } catch (err) {
      // A rejected structured import is still logged server-side (see
      // service.import_elstam_structured_payload) — surface that here so
      // the user knows the attempt was recorded, not silently dropped.
      const suffix = entryMode === "STRUCTURED_IMPORT" ? " This rejected attempt has been recorded in the import log." : "";
      setSaveError((err.message || "Could not save this statutory profile version.") + suffix);
    } finally {
      setSaving(false);
    }
  }

  const isFactorEligible = form.deTaxClass === "IV";
  const isFallback = form.deElstamSource === "FALLBACK_CERTIFICATE";

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-2xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Germany statutory profile</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee.name} · {employee.employeeCode}</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="border border-border bg-surface-muted rounded-[12px] p-2 text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
          >
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Live ELStAM connector status — never a fake "Sync" button. */}
          <div className="mb-5 flex items-start gap-3 rounded-[14px] border border-warning/30 bg-warning/10 px-4 py-3">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <div className="text-[12px] text-foreground">
              <span className="font-bold">Live ELStAM connector: not connected.</span>{" "}
              Zoiko holds no ELSTER organizational certificate — this data is entered manually, from the
              employee's paper "Bescheinigung für den Lohnsteuerabzug," or via a structured import of data
              already validated outside this system. Nothing on this screen contacts ELSTER/BZSt.
            </div>
          </div>

          {loading && <div className="text-[13px] text-foreground-muted">Loading…</div>}
          {loadError && (
            <div className="mb-4 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">
              {loadError}
            </div>
          )}

          {!loading && (
            <>
              <div className="mb-4 rounded-[14px] bg-surface-muted p-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                    Currently effective
                  </h4>
                  <button
                    type="button"
                    onClick={() => setShowHistory((v) => !v)}
                    className="flex items-center gap-1.5 text-[12px] font-semibold text-primary"
                  >
                    <History size={13} /> {showHistory ? "Hide" : "Show"} history ({history.length})
                  </button>
                </div>
                {profile ? (
                  <p className="mt-2 text-[13px] text-foreground">
                    Tax class <strong>{profile.deTaxClass || "—"}</strong>, effective from {profile.effectiveFrom}
                    {profile.effectiveTo ? ` to ${profile.effectiveTo}` : " (current)"}. Source:{" "}
                    <strong>{profile.deElstamSource || "not recorded"}</strong>.
                  </p>
                ) : (
                  <p className="mt-2 text-[13px] text-foreground-muted">
                    No statutory profile recorded yet for this employee — Germany payroll cannot be calculated until one is.
                  </p>
                )}
                {showHistory && history.length > 0 && (
                  <div className="mt-3 max-h-48 overflow-y-auto rounded-[10px] border border-border">
                    <table className="w-full text-[12px]">
                      <thead className="bg-surface text-foreground-muted">
                        <tr>
                          <th className="px-3 py-2 text-left font-semibold">Effective</th>
                          <th className="px-3 py-2 text-left font-semibold">Tax class</th>
                          <th className="px-3 py-2 text-left font-semibold">Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.map((h) => (
                          <tr key={h.id} className="border-t border-border">
                            <td className="px-3 py-2">{h.effectiveFrom} → {h.effectiveTo || "current"}</td>
                            <td className="px-3 py-2">{h.deTaxClass || "—"}</td>
                            <td className="px-3 py-2">{h.deElstamSource || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="mb-4 flex items-center justify-between rounded-[14px] bg-surface-muted p-4">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                  ELStAM import log
                </h4>
                <button
                  type="button"
                  onClick={() => {
                    setShowImportLog((v) => !v);
                    if (!showImportLog) loadImportAttempts();
                  }}
                  className="flex items-center gap-1.5 text-[12px] font-semibold text-primary"
                >
                  <Upload size={13} /> {showImportLog ? "Hide" : "Show"} import attempts
                </button>
              </div>
              {showImportLog && (
                <div className="mb-4 max-h-40 overflow-y-auto rounded-[10px] border border-border">
                  {importAttempts.length === 0 ? (
                    <p className="px-3 py-3 text-[12px] text-foreground-muted">No import attempts recorded yet.</p>
                  ) : (
                    <table className="w-full text-[12px]">
                      <thead className="bg-surface text-foreground-muted">
                        <tr>
                          <th className="px-3 py-2 text-left font-semibold">Imported</th>
                          <th className="px-3 py-2 text-left font-semibold">Schema</th>
                          <th className="px-3 py-2 text-left font-semibold">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {importAttempts.map((a) => (
                          <tr key={a.id} className="border-t border-border">
                            <td className="px-3 py-2">{a.importedAt ? new Date(a.importedAt).toLocaleString() : "—"}</td>
                            <td className="px-3 py-2">{a.schemaVersion}</td>
                            <td className="px-3 py-2">
                              <span className={a.validationStatus === "APPLIED" ? "text-primary font-semibold" : "text-error font-semibold"}>
                                {a.validationStatus}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-5">
                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                    New version — entry type
                  </h4>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setEntryMode("MANUAL")}
                      className={`flex-1 rounded-[10px] border px-3 py-2 text-[12px] font-semibold transition-colors ${
                        entryMode === "MANUAL" ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground-muted"
                      }`}
                    >
                      Manual entry / fallback certificate
                    </button>
                    <button
                      type="button"
                      onClick={() => setEntryMode("STRUCTURED_IMPORT")}
                      className={`flex-1 rounded-[10px] border px-3 py-2 text-[12px] font-semibold transition-colors ${
                        entryMode === "STRUCTURED_IMPORT" ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground-muted"
                      }`}
                    >
                      Structured ELStAM import
                    </button>
                  </div>
                  {entryMode === "STRUCTURED_IMPORT" && (
                    <div className="mt-3 grid grid-cols-2 gap-3">
                      <Field label="Schema version">
                        <input className={inputCls} value={schemaVersion} onChange={(e) => setSchemaVersion(e.target.value)} placeholder="ELSTAM-2026-01" />
                      </Field>
                      <Field label="Import reference" hint="e.g. the change-list batch reference">
                        <input className={inputCls} value={importReference} onChange={(e) => setImportReference(e.target.value)} placeholder="BATCH-2026-07-001" />
                      </Field>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Field label="Effective from">
                    <input type="date" required className={inputCls} value={form.effectiveFrom} onChange={(e) => set("effectiveFrom", e.target.value)} />
                  </Field>
                  <Field label="Reason">
                    <input className={inputCls} value={form.reason} onChange={(e) => set("reason", e.target.value)} placeholder="e.g. ELStAM change list 2026-07" />
                  </Field>
                </div>

                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Tax class & church tax</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Tax class (STKL)">
                      <select className={selectCls} value={form.deTaxClass} onChange={(e) => set("deTaxClass", e.target.value)}>
                        <option value="">Not recorded</option>
                        {TAX_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </Field>
                    <Field label="Factor (class IV only)" hint={!isFactorEligible ? "Only usable with tax class IV" : undefined}>
                      <input
                        type="number" step="0.0001" min="0" max="1" className={inputCls} disabled={!isFactorEligible}
                        value={form.deFactor} onChange={(e) => set("deFactor", e.target.value)}
                      />
                    </Field>
                    <Field label="Main / secondary employment">
                      <select className={selectCls} value={form.deMainEmployment} onChange={(e) => set("deMainEmployment", e.target.value)}>
                        <option value="">Not recorded</option>
                        <option value="true">Main / first employment</option>
                        <option value="false">Secondary / additional employment</option>
                      </select>
                    </Field>
                    <Field label="Employment classification">
                      <select className={selectCls} value={form.deEmploymentClassification} onChange={(e) => set("deEmploymentClassification", e.target.value)}>
                        <option value="">Not recorded</option>
                        {EMPLOYMENT_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </Field>
                    <label className="flex items-center gap-2 text-[13px] text-foreground">
                      <input type="checkbox" checked={form.deChurchTaxLiable} onChange={(e) => set("deChurchTaxLiable", e.target.checked)} />
                      Church-tax liable
                    </label>
                    <Field label="Church-tax Land" hint={!form.deChurchTaxLiable ? "Only usable when church-tax liable" : undefined}>
                      <select className={selectCls} disabled={!form.deChurchTaxLiable} value={form.deChurchTaxLand} onChange={(e) => set("deChurchTaxLand", e.target.value)}>
                        <option value="">Not recorded</option>
                        {CHURCH_TAX_LAENDER.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                      </select>
                    </Field>
                    <Field
                      label="Denomination (for sub-Land exceptions, e.g. Bad Wimpfen RC)"
                      hint={!form.deChurchTaxLiable ? "Only usable when church-tax liable" : "Free text — only needed if a published church-tax exception applies to this employee"}
                    >
                      <input
                        className={inputCls} disabled={!form.deChurchTaxLiable}
                        value={form.deChurchTaxDenomination} onChange={(e) => set("deChurchTaxDenomination", e.target.value)}
                        placeholder="e.g. ROMAN_CATHOLIC"
                      />
                    </Field>
                    <Field
                      label="Church-tax residence postal code"
                      hint={!form.deChurchTaxLiable ? "Only usable when church-tax liable" : "The employee's residence PLZ — the exact key a sub-Land exception is matched against"}
                    >
                      <input
                        className={inputCls} disabled={!form.deChurchTaxLiable}
                        value={form.deChurchTaxMunicipalityPostalCode} onChange={(e) => set("deChurchTaxMunicipalityPostalCode", e.target.value)}
                        placeholder="e.g. 74206"
                      />
                    </Field>
                    <label className="flex items-center gap-2 text-[13px] text-foreground">
                      <input type="checkbox" checked={form.deVocationalTrainee} onChange={(e) => set("deVocationalTrainee", e.target.checked)} />
                      Vocational trainee (Ausbildung/Praktikum/duales Studium)
                    </label>
                  </div>
                </div>

                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Social insurance & PV</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Health insurance status">
                      <select className={selectCls} value={form.deHealthInsuranceStatus} onChange={(e) => set("deHealthInsuranceStatus", e.target.value)}>
                        <option value="">Not recorded</option>
                        <option value="PUBLIC">PUBLIC (GKV)</option>
                        <option value="PRIVATE">PRIVATE (PKV)</option>
                      </select>
                    </Field>
                    <Field label="Health fund code" hint="Must match a published Health Fund Registry entry">
                      <input className={inputCls} value={form.deHealthFundCode} onChange={(e) => set("deHealthFundCode", e.target.value)} />
                    </Field>
                    <Field label="U1 tariff (employer-selected)" hint={form.deHealthFundCode ? "Published tariffs for the selected health fund" : "Select a health fund code to list its published U1 tariffs"}>
                      <select
                        className={selectCls}
                        value={form.deU1TariffId}
                        onChange={(e) => set("deU1TariffId", e.target.value)}
                        disabled={!form.deHealthFundCode}
                      >
                        <option value="">Not recorded</option>
                        {u1Tariffs.map((t) => (
                          <option key={t.id} value={t.tariffIdentifier}>
                            {t.tariffIdentifier} — {t.tariffName || `${t.reimbursementPct}% reimbursement / ${t.levyRatePct}% levy`}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Qualifying children (PV/ZKF)">
                      <input type="number" min="0" className={inputCls} value={form.deChildCount} onChange={(e) => set("deChildCount", e.target.value)} />
                    </Field>
                    <Field label="ZKF override" hint="Only for split-custody half-allowance cases — leave blank otherwise">
                      <input type="number" step="0.5" min="0" className={inputCls} value={form.deZkfOverride} onChange={(e) => set("deZkfOverride", e.target.value)} />
                    </Field>
                    <label className="flex items-center gap-2 text-[13px] text-foreground">
                      <input type="checkbox" checked={form.deChildless} onChange={(e) => set("deChildless", e.target.checked)} />
                      Childless (PV surcharge)
                    </label>
                    <label className="flex items-center gap-2 text-[13px] text-foreground">
                      <input type="checkbox" checked={form.deSaxony} onChange={(e) => set("deSaxony", e.target.checked)} />
                      Saxony PV allocation
                    </label>
                    <label className="flex items-center gap-2 text-[13px] text-foreground">
                      <input type="checkbox" checked={form.dePensionInsuranceExempt} onChange={(e) => set("dePensionInsuranceExempt", e.target.checked)} />
                      Pension insurance exempt
                    </label>
                    <label className="flex items-center gap-2 text-[13px] text-foreground">
                      <input type="checkbox" checked={form.deUnemploymentInsuranceExempt} onChange={(e) => set("deUnemploymentInsuranceExempt", e.target.checked)} />
                      Unemployment insurance exempt
                    </label>
                  </div>
                </div>

                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                    Allowances / add-backs (PAP)
                  </h4>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="JFREIB — annual allowance (€)">
                      <input type="number" step="0.01" min="0" className={inputCls} value={form.deJfreib} onChange={(e) => set("deJfreib", e.target.value)} />
                    </Field>
                    <Field label="LZZFREIB — period allowance (€)">
                      <input type="number" step="0.01" min="0" className={inputCls} value={form.deLzzfreib} onChange={(e) => set("deLzzfreib", e.target.value)} />
                    </Field>
                    <Field label="JHINZU — annual add-back (€)">
                      <input type="number" step="0.01" min="0" className={inputCls} value={form.deJhinzu} onChange={(e) => set("deJhinzu", e.target.value)} />
                    </Field>
                    <Field label="LZZHINZU — period add-back (€)">
                      <input type="number" step="0.01" min="0" className={inputCls} value={form.deLzzhinzu} onChange={(e) => set("deLzzhinzu", e.target.value)} />
                    </Field>
                  </div>
                </div>

                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                    2026 private health/care insurance (ELStAM)
                  </h4>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="PKPV — private premium, monthly (€)">
                      <input type="number" step="0.01" min="0" className={inputCls} value={form.dePkpv} onChange={(e) => set("dePkpv", e.target.value)} />
                    </Field>
                    <Field label="PKPVAGZ — tax-free employer subsidy, monthly (€)">
                      <input type="number" step="0.01" min="0" className={inputCls} value={form.dePkpvagz} onChange={(e) => set("dePkpvagz", e.target.value)} />
                    </Field>
                  </div>
                </div>

                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                    Overtime / Premium Basis
                  </h4>
                  <div className="grid grid-cols-2 gap-3">
                    <Field
                      label="German hourly Grundlohn (€/hour)"
                      hint="Used as the statutory hourly Grundlohn input for future Germany overtime/shift-premium processing. It is entered explicitly and is not derived automatically from salary."
                    >
                      <input
                        type="number" step="0.01" min="0.01" className={inputCls}
                        value={form.deGrundlohnHourly} onChange={(e) => set("deGrundlohnHourly", e.target.value)}
                      />
                    </Field>
                  </div>
                </div>

                <div className="rounded-[14px] border border-border p-4">
                  <h4 className="mb-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">ELStAM provenance</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Source">
                      <select className={selectCls} value={form.deElstamSource} onChange={(e) => set("deElstamSource", e.target.value)}>
                        <option value="">Not recorded</option>
                        <option value="ELSTAM">ELStAM (electronic)</option>
                        <option value="FALLBACK_CERTIFICATE">Fallback certificate</option>
                      </select>
                    </Field>
                    <Field label="Fallback reason" hint={!isFallback ? "Only required for a fallback certificate" : "Required"}>
                      <input
                        className={inputCls} disabled={!isFallback} required={isFallback}
                        value={form.deElstamFallbackReason} onChange={(e) => set("deElstamFallbackReason", e.target.value)}
                        placeholder="e.g. ELStAM retrieval blocked; paper certificate on file"
                      />
                    </Field>
                  </div>
                </div>

                {saveError && (
                  <div className="rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{saveError}</div>
                )}
                {saveSuccess && (
                  <div className="rounded-[12px] bg-primary/10 px-4 py-3 text-[13px] text-primary border border-primary/20">{saveSuccess}</div>
                )}
                {profile?.mainSecondaryConsistencyWarning && (
                  <div className="rounded-[12px] bg-warning/10 px-4 py-3 text-[13px] text-warning border border-warning/20">
                    <span className="font-bold">Review recommended — </span>{profile.mainSecondaryConsistencyWarning}
                  </div>
                )}

                <div className="flex justify-end gap-3 pb-2">
                  <button type="button" onClick={onClose} className="border border-border bg-surface-muted rounded-[12px] px-4 py-2.5 text-[13px] font-semibold text-foreground-muted">
                    Close
                  </button>
                  <button
                    type="submit" disabled={saving}
                    className="bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover disabled:opacity-60"
                  >
                    {saving ? "Saving…" : "Save new version"}
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

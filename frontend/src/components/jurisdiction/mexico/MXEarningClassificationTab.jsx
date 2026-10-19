import { useState } from "react";
import {
  approveMxEarningClassification, archiveMxEarningClassification, createMxEarningClassification, listMxEarningClassifications,
} from "../../../service/superAdminService";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad, yesNo } from "./mxShared";

// Multi-axis earning classification (MX-005): ISR, SBC, INFONAVIT, state
// ISN, PTU and the CFDI node / SAT concept are decided independently — no
// universal "taxable" flag and no axis defaults. A new version is DRAFT and
// never live until a different Super Admin approves it; an approved newer
// version SUPERSEDES the old one, which stays for history (MX-006).
// Canonical rows need their SAT concept code in an approved CFDI catalog
// (S28), so none can go live until that catalog is verified.
const EMPTY = {
  scope: "catalog", earningCode: "", label: "", effectiveFrom: "", isrTreatment: "", isrExemptRuleKey: "",
  sbcTreatment: "", sbcExclusionCondition: "", infonavitIncluded: "", isnDefaultIncluded: "", ptuWageBaseIncluded: "",
  cfdiNodeType: "", cfdiConceptCode: "",
};
const bool = (v) => (v === "" ? undefined : v === "true");

function BoolSelect({ value, onChange, label }) {
  return (
    <Field label={label}>
      <select required className={input} value={value} onChange={onChange}>
        <option value="">— decide —</option><option value="true">Included</option><option value="false">Excluded</option>
      </select>
    </Field>
  );
}

export default function MXEarningClassificationTab({ orgId }) {
  const [rows, loadError, , reload] = useLoad(() => listMxEarningClassifications(orgId), [orgId]);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    const payload = {
      organizationId: form.scope === "org" ? orgId : null, earningCode: form.earningCode, label: form.label,
      effectiveFrom: form.effectiveFrom, isrTreatment: form.isrTreatment, isrExemptRuleKey: form.isrExemptRuleKey || null,
      sbcTreatment: form.sbcTreatment, sbcExclusionCondition: form.sbcExclusionCondition || null,
      infonavitIncluded: bool(form.infonavitIncluded), isnDefaultIncluded: bool(form.isnDefaultIncluded),
      ptuWageBaseIncluded: bool(form.ptuWageBaseIncluded), cfdiNodeType: form.cfdiNodeType,
      cfdiConceptCode: form.cfdiConceptCode || null,
    };
    if (await run(() => createMxEarningClassification(payload), "Draft recorded — a different Super Admin must approve it.")) setForm(null);
  };
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <div className="mb-1 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-foreground">
            Earning classifications — {orgId ? "selected organisation" : "platform catalogue"}
          </h3>
          {!form && <button type="button" className={btnPrimary} onClick={() => setForm(EMPTY)}>New classification</button>}
        </div>
        <p className="mb-3 text-[11px] text-foreground-muted">
          Every axis is independent (MX-005). New versions are DRAFT until a second Super Admin approves them.
          No canonical codes are seeded until the SAT Nómina 1.2 catalog (S28) is verified.
        </p>
        {form && (
          <form onSubmit={save} className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="New classification">
            <Field label="Scope">
              <select className={input} value={form.scope} onChange={set("scope")}>
                <option value="catalog">Platform catalogue</option>
                <option value="org" disabled={!orgId}>Selected organisation</option>
              </select>
            </Field>
            <Field label="Earning code"><input required className={input} value={form.earningCode} onChange={set("earningCode")} /></Field>
            <Field label="Label"><input required className={input} value={form.label} onChange={set("label")} /></Field>
            <Field label="Effective from"><input type="date" required className={input} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
            <Field label="ISR">
              <select required className={input} value={form.isrTreatment} onChange={set("isrTreatment")}>
                <option value="">— decide —</option>{["TAXABLE", "EXEMPT", "PARTIAL"].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
            <Field label="ISR exemption rule"><input className={input} value={form.isrExemptRuleKey} onChange={set("isrExemptRuleKey")} placeholder="required if EXEMPT/PARTIAL" /></Field>
            <Field label="SBC (IMSS base)">
              <select required className={input} value={form.sbcTreatment} onChange={set("sbcTreatment")}>
                <option value="">— decide —</option>{["FIXED", "VARIABLE", "EXCLUDED"].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
            <Field label="SBC exclusion condition"><input className={input} value={form.sbcExclusionCondition} onChange={set("sbcExclusionCondition")} placeholder="required if EXCLUDED (MX-022)" /></Field>
            <BoolSelect label="INFONAVIT base" value={form.infonavitIncluded} onChange={set("infonavitIncluded")} />
            <BoolSelect label="State ISN base (default)" value={form.isnDefaultIncluded} onChange={set("isnDefaultIncluded")} />
            <BoolSelect label="PTU wage base" value={form.ptuWageBaseIncluded} onChange={set("ptuWageBaseIncluded")} />
            <Field label="CFDI node">
              <select required className={input} value={form.cfdiNodeType} onChange={set("cfdiNodeType")}>
                <option value="">— decide —</option>{["PERCEPCION", "DEDUCCION", "OTRO_PAGO", "SEPARACION"].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
            <Field label="SAT concept code"><input className={input} value={form.cfdiConceptCode} onChange={set("cfdiConceptCode")} /></Field>
            <div className="col-span-full flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save draft</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        <Table rows={rows} empty="No classification recorded yet." columns={[
          { key: "earningCode", label: "Code" }, { key: "version", label: "v" }, { key: "label", label: "Label" },
          { key: "isrTreatment", label: "ISR" }, { key: "sbcTreatment", label: "SBC" },
          { key: "infonavitIncluded", label: "INFONAVIT", render: (r) => yesNo(r.infonavitIncluded) },
          { key: "isnDefaultIncluded", label: "ISN", render: (r) => yesNo(r.isnDefaultIncluded) },
          { key: "ptuWageBaseIncluded", label: "PTU", render: (r) => yesNo(r.ptuWageBaseIncluded) },
          { key: "cfdiNodeType", label: "CFDI node" }, { key: "cfdiConceptCode", label: "SAT code" },
          { key: "effectiveFrom", label: "From" }, { key: "effectiveTo", label: "To" }, { key: "status", label: "Status" },
          { key: "actions", label: "", render: (r) => (
            <span className="flex gap-1">
              {r.status === "DRAFT" && (
                <button type="button" className={btn} disabled={busy}
                        onClick={() => run(() => approveMxEarningClassification(r.id), "Approved — now ACTIVE.")}>Approve</button>
              )}
              {(r.status === "DRAFT" || r.status === "ACTIVE") && (
                <button type="button" className={btn} disabled={busy}
                        onClick={() => { const reason = window.prompt("Reason for archiving"); if (reason) run(() => archiveMxEarningClassification(r.id, reason), "Archived."); }}>
                  Archive
                </button>
              )}
            </span>
          ) },
        ]} />
      </div>
    </div>
  );
}

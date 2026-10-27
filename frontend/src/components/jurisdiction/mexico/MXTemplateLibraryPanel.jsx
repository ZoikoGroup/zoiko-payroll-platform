import { useState } from "react";
import { compareMxReportTemplates, getMxTemplateCoverage, previewMxTemplateInSandbox } from "../../../service/superAdminService";
import { Messages, Table, btn, btnPrimary, card, input, useLoad } from "./mxShared";

// Mexico report-template library tools (final mile X3b): every template's
// build kind and field check, a version diff, and a preview of a
// template-engine template against one calculation-sandbox result
// (watermarked, never stored). Read-only: the template lifecycle above is
// unchanged and activation is still the server's gate.
const KIND = { TEMPLATE_ENGINE: "Snapshot fields", DEDICATED: "Dedicated generator", RECEIPT: "CFDI receipt" };

export default function MXTemplateLibraryPanel() {
  const [rows, error] = useLoad(() => getMxTemplateCoverage(), []);
  const [cmp, setCmp] = useState({ from: "", to: "" });
  const [diff, setDiff] = useState(null);
  const [preview, setPreview] = useState(null);
  const [form, setForm] = useState({ templateId: "", payDate: "2026-06-15", dailySalary: "600", zone: "GENERAL", candidates: "" });
  const [actionError, setActionError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const engine = (rows || []).filter((r) => r.kind === "TEMPLATE_ENGINE");

  async function compare() {
    setActionError(null); setDiff(null);
    try { setDiff(await compareMxReportTemplates(cmp.from, cmp.to)); } catch (e) { setActionError(e?.message || "Compare failed."); }
  }

  async function runPreview(e) {
    e.preventDefault();
    setActionError(null); setPreview(null);
    // "D-01=HALF_UP:0.01; D-03=GENERAL" → [{decision, value}] (what-if candidates, X2 rules apply)
    const candidates = form.candidates.split(";").map((p) => p.trim()).filter(Boolean)
      .map((p) => { const [decision, ...rest] = p.split("="); return { decision: decision.trim(), value: rest.join("=").trim() }; });
    try {
      setPreview(await previewMxTemplateInSandbox(form.templateId, {
        payDate: form.payDate, periodStart: `${form.payDate.slice(0, 8)}01`, periodEnd: form.payDate,
        dailySalary: form.dailySalary, zone: form.zone, candidates,
      }));
    } catch (err) {
      setActionError(err?.message || "The preview was refused.");
    }
  }

  return (
    <div className="mt-6 flex flex-col gap-4" data-testid="mx-template-library">
      <div className={card}>
        <h3 className="text-[14px] font-semibold text-foreground">Mexico template library</h3>
        <p className="mt-1 text-[12px] text-foreground-muted">
          How each template is built and whether its fields are catalogued Mexico snapshot paths. Proof on a real committed
          payslip, signed gates and Active content are checked by the server when a template is activated.
        </p>
        <Messages error={error || actionError} />
        <Table rows={rows || []} rowKey={(r) => r.id} empty="No Mexico template is seeded." columns={[
          { key: "templateKey", label: "Template" }, { key: "version", label: "Version" }, { key: "status", label: "Status" },
          { key: "kind", label: "Built by", render: (r) => KIND[r.kind] || r.kind }, { key: "fields", label: "Fields" },
          { key: "gates", label: "Gates", render: (r) => r.gates.join(", ") }, { key: "fieldProof", label: "Field check" },
        ]} />
      </div>

      <div className={card} data-testid="mx-template-compare">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Compare two versions</h3>
        <div className="flex flex-wrap gap-2">
          {["from", "to"].map((k) => (
            <select key={k} aria-label={`Compare ${k}`} className={input} value={cmp[k]} onChange={(e) => setCmp((c) => ({ ...c, [k]: e.target.value }))}>
              <option value="">— {k} —</option>
              {(rows || []).map((r) => <option key={r.id} value={r.id}>{r.templateKey} v{r.version} ({r.status})</option>)}
            </select>
          ))}
          <button type="button" className={btn} disabled={!cmp.from || !cmp.to} onClick={compare}>Compare</button>
        </div>
        {diff && (
          <div className="mt-2 text-[12px] text-foreground" data-testid="mx-template-diff">
            <p>{diff.identical ? "Identical." : `Added ${diff.added.length} · removed ${diff.removed.length} · changed ${diff.changed.length} · metadata ${Object.keys(diff.metadata).length}`}</p>
            {diff.added.length > 0 && <p>Added: {diff.added.join(", ")}</p>}
            {diff.removed.length > 0 && <p>Removed: {diff.removed.join(", ")}</p>}
            {diff.changed.map((c) => <p key={c.field}>Changed {c.field}: {Object.keys(c.changes).join(", ")}</p>)}
            {Object.entries(diff.metadata).map(([k, v]) => <p key={k}>{k}: {v.from} → {v.to}</p>)}
            <p className="text-foreground-muted">Content hashes: {diff.from.contentHash.slice(0, 12)} → {diff.to.contentHash.slice(0, 12)}</p>
          </div>
        )}
      </div>

      <form className={card} onSubmit={runPreview} aria-label="Template sandbox preview" data-testid="mx-template-preview">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Preview a template on a sandbox calculation</h3>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <select aria-label="Template to preview" className={input} value={form.templateId} onChange={set("templateId")} required>
            <option value="">— snapshot-field template —</option>
            {engine.map((r) => <option key={r.id} value={r.id}>{r.templateKey} v{r.version}</option>)}
          </select>
          <input aria-label="Preview pay date" type="date" className={input} value={form.payDate} onChange={set("payDate")} />
          <input aria-label="Preview daily salary" className={input} value={form.dailySalary} onChange={set("dailySalary")} />
          <select aria-label="Preview zone" className={input} value={form.zone} onChange={set("zone")}><option>GENERAL</option><option>ZLFN</option></select>
          <input aria-label="Preview candidates" className={`${input} sm:col-span-2`} placeholder="What-if: D-01=HALF_UP:0.01; D-03=GENERAL" value={form.candidates} onChange={set("candidates")} />
        </div>
        <button type="submit" className={`${btnPrimary} mt-2`}>Preview</button>
        {preview && (
          <div className="mt-3" data-testid="mx-template-preview-result">
            <div className="mb-2 flex flex-wrap gap-2">
              {preview.watermarks.map((w) => <span key={w} className="rounded bg-warning/20 px-2 py-1 text-[11px] font-bold text-warning">{w}</span>)}
            </div>
            {preview.outcome === "BLOCKED"
              ? <p className="text-[12px] text-error">Blocked: {preview.block.code} — {preview.block.message}</p>
              : <Table rows={preview.fields} rowKey={(f) => `${f.component}.${f.field}`} columns={[
                  { key: "component", label: "Component" }, { key: "label", label: "Field" }, { key: "source", label: "Source path" },
                  { key: "value", label: "Value", render: (f) => (f.value ?? (f.sourceKind === "PAYSLIP_ITEM_JSON" ? "— not on this result" : "(run / employee field)")) },
                ]} />}
          </div>
        )}
      </form>
    </div>
  );
}

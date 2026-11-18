import { useState } from "react";
import { compareMxReportTemplates, getMxReadiness, getMxTemplateCoverage, getMxTemplateVersions, previewMxTemplateInSandbox } from "../../../service/superAdminService";
import { Messages, Table, btn, btnPrimary, card, input, useLoad } from "./mxShared";
import { findCoverageRow, findVersionEntry } from "./mxTemplateLookup";
import { approverNote, componentsNotice, gateLines } from "./mxTemplateNotices";

const TONE = { ok: "text-success", warning: "text-warning", info: "text-foreground", muted: "text-foreground-muted" };

// Mexico report-template library tools (final mile X3b): every template's
// build kind and field check, a version diff, and a preview of a
// template-engine template against one calculation-sandbox result
// (watermarked, never stored). Read-only: the shared template lifecycle is
// unchanged and activation is still the server's gate.
//
// Rendered through ReportTemplateLayout's generic extension props (see
// MXReportTemplatesPage): the full library is a page-level "Library" view
// (collapsed by default); the status block, compare and preview are shown for
// the SELECTED template only.
const KIND = { TEMPLATE_ENGINE: "Snapshot fields", DEDICATED: "Dedicated generator", RECEIPT: "CFDI receipt" };

// Page-level "Library" view: every Mexico template with build kind, gates and field check.
export default function MXTemplateLibraryPanel() {
  const [rows, error] = useLoad(() => getMxTemplateCoverage(), []);
  return (
    <div data-testid="mx-template-library">
      <h3 className="text-[14px] font-semibold text-foreground">Mexico template library</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        How each template is built and whether its fields are catalogued Mexico snapshot paths. Proof on a real committed
        payslip, signed gates and Active content are checked by the server when a template is activated.
      </p>
      <Messages error={error} />
      <Table rows={rows || []} rowKey={(r) => r.id} empty="No Mexico template is seeded." columns={[
        { key: "templateKey", label: "Template" }, { key: "version", label: "Version" }, { key: "status", label: "Status" },
        { key: "kind", label: "Built by", render: (r) => KIND[r.kind] || r.kind }, { key: "fields", label: "Fields" },
        { key: "gates", label: "Gates", render: (r) => r.gates.join(", ") }, { key: "fieldProof", label: "Field check" },
      ]} />
    </div>
  );
}

// Overview status block for the selected template: built by, gates, field check
// and the activation gate's answer on platform data. Refetches when the detail
// object changes (status change, approval), so it never shows a stale answer.
export function MXTemplateStatusBlock({ detail }) {
  const [rows, error] = useLoad(() => getMxTemplateCoverage(), [detail]);
  const [groups, vError] = useLoad(() => getMxTemplateVersions(), [detail]);
  // Gate areas and states (G2 IMSS / SUA: OPEN). Optional: without it the
  // block still names the gates.
  const [readiness] = useLoad(() => getMxReadiness(), []);
  // "Built by", gates and field check come from the server's library data for
  // this template_key (never assumed from the report type on the client).
  const row = findCoverageRow(rows, detail);
  const ver = findVersionEntry(groups, detail);
  const loading = rows === null || groups === null;
  const approver = approverNote(detail);
  const gates = gateLines(row?.gates, readiness?.gates);
  return (
    <div className="rounded-lg border border-border-light bg-surface-muted p-3 text-xs" data-testid="mx-template-status">
      <p className="mb-2 font-semibold text-foreground">Mexico template status</p>
      <Messages error={error || vError} />
      {loading && !error && !vError ? <p className="text-foreground-muted">Loading…</p> : !row ? (
        <p className="text-foreground-muted">This template is not in the Mexico library.</p>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div><p className="text-foreground-muted">Built by</p><p className="font-medium text-foreground">{KIND[row.kind] || row.kind}</p></div>
          <div><p className="text-foreground-muted">Gates</p><p className="font-medium text-foreground">{row.gates.length ? row.gates.join(", ") : "—"}</p></div>
          <div><p className="text-foreground-muted">Fields</p><p className="font-medium text-foreground">{row.fields}</p></div>
          <div className="sm:col-span-3"><p className="text-foreground-muted">Field check</p><p className="font-medium text-foreground">{row.fieldProof}</p></div>
          <div className="sm:col-span-3" data-testid="mx-template-approver">
            <p className="text-foreground-muted">Approver</p>
            <p className={`font-medium ${TONE[approver.tone]}`}>{approver.text}</p>
          </div>
          <div className="sm:col-span-3">
            <p className="text-foreground-muted">Activation gate (platform data)</p>
            {!ver ? <p className="text-foreground-muted">—</p> : ver.activationRefusal
              ? <p className="font-medium text-warning">{ver.activationRefusal}</p>
              : <p className="font-medium text-success">
                  {row.kind === "TEMPLATE_ENGINE"
                    ? "would pass on platform data (the payslip field proof still runs at activation)"
                    : "would pass on platform data"}
                </p>}
            {gates.length > 0 && (
              <ul className="mt-1 space-y-0.5" data-testid="mx-template-gate-states">
                {gates.map((g) => (
                  <li key={g.gate} className="text-foreground-secondary">
                    <span className="font-semibold">{g.gate}</span>{g.label ? ` ${g.label}` : ""}:{" "}
                    <span className={g.signed ? "text-success" : "text-warning"}>{g.state || "state not loaded"}</span>
                  </li>
                ))}
              </ul>
            )}
            {gates.some((g) => !g.signed) && (
              <p className="mt-1 text-foreground-muted">
                A gate is signed only by its reviewed evidence (Mexico → Readiness &amp; gates). Until every gate this report rests on
                is signed, activation is refused by design: Mexico stays dormant. Nothing on this page can override it.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Top of the Components tab: what the selected template is built from and, for a
// snapshot-field template with no fields, why and how it gets them.
export function MXTemplateComponentsNotice({ detail }) {
  const [rows, error] = useLoad(() => getMxTemplateCoverage(), [detail]);
  if (error) return <Messages error={error} />;
  if (rows === null) return <p className="text-xs text-foreground-muted">Loading…</p>;
  const notice = componentsNotice(findCoverageRow(rows, detail), detail);
  if (!notice) return null;
  const border = notice.tone === "warning" ? "border-warning/40 bg-warning/10" : "border-border-light bg-surface-muted";
  return (
    <div className={`rounded-lg border p-3 text-xs ${border}`} data-testid="mx-template-components-notice" data-tone={notice.tone}>
      <p className={`font-semibold ${TONE[notice.tone]}`}>{notice.title}</p>
      <p className="mt-1 text-foreground-secondary">{notice.body}</p>
    </div>
  );
}

// Compare two versions — the caller passes the versions to offer (the selected template's).
export function MXTemplateCompare({ options, defaultTo = "" }) {
  const [cmp, setCmp] = useState({ from: "", to: defaultTo ? String(defaultTo) : "" });
  const [diff, setDiff] = useState(null);
  const [actionError, setActionError] = useState(null);

  async function compare() {
    setActionError(null); setDiff(null);
    try { setDiff(await compareMxReportTemplates(cmp.from, cmp.to)); } catch (e) { setActionError(e?.message || "Compare failed."); }
  }

  return (
    <div className={card} data-testid="mx-template-compare">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Compare two versions</h3>
      <Messages error={actionError} />
      {options.length < 2 ? (
        <p className="text-[12px] text-foreground-muted">Only one version exists — make a new version to compare.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {["from", "to"].map((k) => (
            <select key={k} aria-label={`Compare ${k}`} className={input} value={cmp[k]} onChange={(e) => setCmp((c) => ({ ...c, [k]: e.target.value }))}>
              <option value="">— {k} —</option>
              {options.map((r) => <option key={r.id} value={r.id}>{r.templateKey} v{r.version} ({r.status})</option>)}
            </select>
          ))}
          <button type="button" className={btn} disabled={!cmp.from || !cmp.to} onClick={compare}>Compare</button>
        </div>
      )}
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
  );
}

// "Preview" detail tab: the sandbox preview, pre-selected to the current
// template when it is a snapshot-field template; otherwise says why preview
// does not apply (the server refuses it for dedicated generators too).
export function MXTemplatePreviewTab({ detail }) {
  const [rows, error] = useLoad(() => getMxTemplateCoverage(), [detail]);
  if (error) return <Messages error={error} />;
  if (rows === null) return <p className="text-xs text-foreground-muted">Loading…</p>;
  const row = findCoverageRow(rows, detail);
  if (!row || row.kind !== "TEMPLATE_ENGINE") {
    const why = !row ? "This template is not in the Mexico library."
      : row.kind === "RECEIPT" ? "The CFDI receipt is rendered from the stamped CFDI, not from payslip fields — it has no sandbox preview."
      : `${row.templateKey} is built by a dedicated generator from Mexico's service views, not from payslip fields — it has no sandbox preview.`;
    return (
      <div className={card} data-testid="mx-template-preview-na">
        <p className="text-[13px] font-semibold text-foreground">Preview does not apply</p>
        <p className="mt-1 text-[12px] text-foreground-muted">{why} Only snapshot-field templates can be previewed on a sandbox calculation.</p>
      </div>
    );
  }
  return <MXTemplatePreview key={detail.id} engine={rows.filter((r) => r.kind === "TEMPLATE_ENGINE")} templateId={row.id} />;
}

function MXTemplatePreview({ engine, templateId }) {
  const [preview, setPreview] = useState(null);
  const [form, setForm] = useState({ templateId: String(templateId), payDate: "2026-06-15", dailySalary: "600", zone: "GENERAL", candidates: "" });
  const [actionError, setActionError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

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
    <form className={card} onSubmit={runPreview} aria-label="Template sandbox preview" data-testid="mx-template-preview">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Preview a template on a sandbox calculation</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">Synthetic inputs only; the result is watermarked and never stored.</p>
      <Messages error={actionError} />
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
  );
}

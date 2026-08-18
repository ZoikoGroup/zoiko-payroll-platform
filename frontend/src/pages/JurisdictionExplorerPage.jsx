import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Plus, Trash2, Pencil, Check, X,
  FolderTree, Receipt, Users as UsersIcon, ScrollText, Settings2,
} from "lucide-react";
import { useToast } from "../context/ToastContext";
import Modal from "../components/Modal";
import StatusPill from "../components/StatusPill";
import JurisdictionTreeNav from "../components/hierarchy/JurisdictionTreeNav";
import { RateConfigurationPanel, ParameterConfigurationPanel } from "../components/hierarchy/RateConfigPanels";
import * as hs from "../service/hierarchyService";

// New, additive page — consumes the generic jurisdiction/tax hierarchy
// engine (backend/app/modules/payroll/hierarchy/*), a second, parallel
// system to the existing pages/CompliancePage.jsx (JurisdictionPack/
// ContributionRate/TaxSlab). That page is completely untouched; this one
// will be empty until reference data (Country/JurisdictionLevel rows) is
// seeded by a later migration step — the empty states below are the
// expected, honest state today, not a bug.

const STATUS_PILL_MAP = {
  Active: "active", Draft: "pending", Scheduled: "pending",
  Expired: "inactive", Retired: "suspended", Deprecated: "inactive",
};
const STATUS_OPTIONS = ["Draft", "Scheduled", "Active", "Expired", "Retired", "Deprecated"];

const inputClass =
  "w-full rounded-lg border border-border-strong bg-background px-3 py-2 text-sm text-foreground shadow-sm " +
  "transition-colors placeholder:text-foreground-disabled hover:border-primary/50 focus:border-primary " +
  "focus:outline-none focus:ring-2 focus:ring-focus-ring/30";
const labelClass = "mb-1.5 block text-xs font-medium text-foreground-muted";

// ── New Tax Version modal (2-step: identity, then rules land on the Rates tab) ──

function NewTaxVersionModal({ taxId, jurisdictionId, onClose, onCreated }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({ version_label: "1.0", tax_year: "", tax_regime: "", status: "Draft", effective_from: "", effective_to: "" });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.version_label.trim() || !form.effective_from) {
      addToast?.("Version label and Effective From are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const created = await hs.upsertTaxVersion({
        tax_id: taxId, jurisdiction_id: jurisdictionId,
        version_label: form.version_label, tax_year: form.tax_year || null, tax_regime: form.tax_regime || null,
        status: form.status, effective_from: form.effective_from, effective_to: form.effective_to || null,
      });
      addToast?.("Tax version created.", "success");
      onCreated(created);
    } catch (err) {
      addToast?.(err.message || "Failed to create version.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="New Tax Version" onClose={onClose} maxWidth="max-w-md">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Version Label</label><input className={inputClass} value={form.version_label} onChange={set("version_label")} placeholder="1.0" /></div>
        <div><label className={labelClass}>Status</label><select className={inputClass} value={form.status} onChange={set("status")}>{STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}</select></div>
        <div><label className={labelClass}>Tax Year</label><input className={inputClass} value={form.tax_year} onChange={set("tax_year")} placeholder="2026-27" /></div>
        <div><label className={labelClass}>Tax Regime</label><input className={inputClass} value={form.tax_regime} onChange={set("tax_regime")} placeholder="New / Old" /></div>
        <div><label className={labelClass}>Effective From</label><input type="date" className={inputClass} value={form.effective_from} onChange={set("effective_from")} /></div>
        <div><label className={labelClass}>Effective To</label><input type="date" className={inputClass} value={form.effective_to} onChange={set("effective_to")} /></div>
      </div>
      {form.status === "Active" && (
        <p className="mt-3 rounded-lg border border-warning/30 bg-warning-light px-3 py-2 text-xs text-warning">
          Creating this directly as Active will be rejected if another version of this Tax already covers an
          overlapping effective period — retire or expire the conflicting one first.
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
          {saving ? "Creating…" : "Create Version"}
        </button>
      </div>
    </Modal>
  );
}

// ── Right panel: Taxes -> Versions -> selected-version tabs ─────────────

const VERSION_TABS = [
  { key: "overview", label: "Overview", icon: Settings2 },
  { key: "rates", label: "Rates", icon: Receipt },
  { key: "parameters", label: "Parameters", icon: FolderTree },
  { key: "audit", label: "Audit", icon: ScrollText },
];

function TaxVersionPanel({ version, onStatusChanged }) {
  const { addToast } = useToast() || {};
  const [tab, setTab] = useState("overview");
  const [audit, setAudit] = useState([]);
  const [statusBusy, setStatusBusy] = useState(false);

  useEffect(() => {
    if (tab === "audit") hs.getTaxVersionAudit(version.id).then(setAudit).catch(() => {});
  }, [tab, version.id]);

  async function changeStatus(newStatus) {
    setStatusBusy(true);
    try {
      await hs.setTaxVersionStatus(version.id, newStatus);
      addToast?.(`Status set to ${newStatus}.`, "success");
      onStatusChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to change status.", "error");
    } finally {
      setStatusBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 border-b border-border">
        {VERSION_TABS.map((t) => (
          <button
            key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium ${
              tab === t.key ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"
            }`}
          >
            <t.icon size={13} /> {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
            <div><p className="text-foreground-disabled">Version</p><p className="font-medium text-foreground">{version.version_label}</p></div>
            <div><p className="text-foreground-disabled">Tax Year</p><p className="font-medium text-foreground">{version.tax_year || "—"}</p></div>
            <div><p className="text-foreground-disabled">Regime</p><p className="font-medium text-foreground">{version.tax_regime || "—"}</p></div>
            <div><p className="text-foreground-disabled">Effective</p><p className="font-medium text-foreground">{version.effective_from} → {version.effective_to || "open-ended"}</p></div>
          </div>
          <div>
            <label className={labelClass}>Status</label>
            <select className={inputClass + " max-w-xs"} value={version.status} disabled={statusBusy} onChange={(e) => changeStatus(e.target.value)}>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
      )}
      {tab === "rates" && <RateConfigurationPanel taxVersionId={version.id} />}
      {tab === "parameters" && <ParameterConfigurationPanel taxVersionId={version.id} />}
      {tab === "audit" && (
        <div className="space-y-2">
          {audit.length === 0 && <p className="text-xs text-foreground-disabled">No audit history yet.</p>}
          {audit.map((row) => (
            <div key={row.id} className="rounded-lg border border-border-light p-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-foreground">{row.action} — {row.entity_type}</span>
                <span className="text-foreground-disabled">{new Date(row.created_at).toLocaleString()}</span>
              </div>
              {row.reason && <p className="mt-1 text-foreground-secondary">{row.reason}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TaxesAndVersions({ jurisdictionId }) {
  const { addToast } = useToast() || {};
  const [taxes, setTaxes] = useState([]);
  const [selectedTaxId, setSelectedTaxId] = useState(null);
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [showNewTax, setShowNewTax] = useState(false);
  const [newTaxForm, setNewTaxForm] = useState({ tax_code: "", name: "", category: "other_statutory" });
  const [showNewVersion, setShowNewVersion] = useState(false);

  const loadTaxes = useCallback(() => {
    hs.getTaxesForJurisdiction(jurisdictionId).then((rows) => {
      setTaxes(rows);
      setSelectedTaxId((prev) => (rows.some((r) => r.id === prev) ? prev : rows[0]?.id ?? null));
    });
  }, [jurisdictionId]);
  useEffect(() => { loadTaxes(); setSelectedVersion(null); }, [loadTaxes]);

  const loadVersions = useCallback(() => {
    if (!selectedTaxId) { setVersions([]); return; }
    hs.getTaxVersions(selectedTaxId, jurisdictionId).then((rows) => {
      setVersions(rows);
      setSelectedVersion((prev) => rows.find((r) => r.id === prev?.id) || rows[0] || null);
    });
  }, [selectedTaxId, jurisdictionId]);
  useEffect(() => { loadVersions(); }, [loadVersions]);

  async function createTax() {
    if (!newTaxForm.tax_code.trim() || !newTaxForm.name.trim()) {
      addToast?.("Tax code and name are required.", "error");
      return;
    }
    try {
      const jur = await hs.getJurisdictionDetail(jurisdictionId);
      const created = await hs.upsertTax({ ...newTaxForm, country_id: jur.country_id });
      setShowNewTax(false);
      setNewTaxForm({ tax_code: "", name: "", category: "other_statutory" });
      loadTaxes();
      setSelectedTaxId(created.id);
    } catch (err) {
      addToast?.(err.message || "Failed to create tax.", "error");
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs font-semibold text-foreground-muted">Taxes</p>
          <button type="button" onClick={() => setShowNewTax(true)} className="text-foreground-disabled hover:text-primary"><Plus size={14} /></button>
        </div>
        <div className="space-y-0.5">
          {taxes.map((t) => (
            <button
              key={t.id} onClick={() => setSelectedTaxId(t.id)}
              className={`block w-full rounded-md px-2 py-1.5 text-left text-xs ${
                selectedTaxId === t.id ? "bg-primary/10 font-medium text-primary" : "text-foreground-secondary hover:bg-surface-muted"
              }`}
            >
              {t.name} <span className="text-foreground-disabled">({t.tax_code})</span>
            </button>
          ))}
          {taxes.length === 0 && <p className="text-[11px] text-foreground-disabled">No taxes yet at this jurisdiction.</p>}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        {!selectedTaxId ? (
          <p className="py-8 text-center text-xs text-foreground-disabled">Select or create a Tax to see its versions.</p>
        ) : (
          <>
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-semibold text-foreground-muted">Versions</p>
              <button type="button" onClick={() => setShowNewVersion(true)} className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-[11px] text-foreground-secondary hover:border-primary hover:text-primary">
                <Plus size={11} /> New Version
              </button>
            </div>
            <div className="mb-4 flex flex-wrap gap-2">
              {versions.map((v) => (
                <button
                  key={v.id} onClick={() => setSelectedVersion(v)}
                  className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${
                    selectedVersion?.id === v.id ? "border-primary bg-primary/5" : "border-border hover:bg-surface-muted"
                  }`}
                >
                  v{v.version_label}
                  <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
                </button>
              ))}
              {versions.length === 0 && <p className="text-[11px] text-foreground-disabled">No versions yet.</p>}
            </div>
            {selectedVersion && <TaxVersionPanel version={selectedVersion} onStatusChanged={loadVersions} />}
          </>
        )}
      </div>

      {showNewTax && (
        <Modal title="New Tax" onClose={() => setShowNewTax(false)} maxWidth="max-w-sm">
          <div className="space-y-3">
            <div><label className={labelClass}>Tax Code</label><input className={inputClass} value={newTaxForm.tax_code} onChange={(e) => setNewTaxForm((f) => ({ ...f, tax_code: e.target.value.toUpperCase() }))} placeholder="INCOME_TAX" /></div>
            <div><label className={labelClass}>Name</label><input className={inputClass} value={newTaxForm.name} onChange={(e) => setNewTaxForm((f) => ({ ...f, name: e.target.value }))} placeholder="Income Tax" /></div>
            <div>
              <label className={labelClass}>Category</label>
              <select className={inputClass} value={newTaxForm.category} onChange={(e) => setNewTaxForm((f) => ({ ...f, category: e.target.value }))}>
                <option value="income_tax">Income Tax</option>
                <option value="social_contribution">Social Contribution</option>
                <option value="other_statutory">Other Statutory</option>
              </select>
            </div>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={() => setShowNewTax(false)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button type="button" onClick={createTax} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Create Tax</button>
          </div>
        </Modal>
      )}

      {showNewVersion && (
        <NewTaxVersionModal
          taxId={selectedTaxId} jurisdictionId={jurisdictionId}
          onClose={() => setShowNewVersion(false)}
          onCreated={(created) => { setShowNewVersion(false); loadVersions(); setSelectedVersion(created); }}
        />
      )}
    </div>
  );
}

function ApplicabilityTab({ jurisdictionId }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    hs.getJurisdictionApplicability(jurisdictionId).then(setRows).finally(() => setLoading(false));
  }, [jurisdictionId]);

  if (loading) return <p className="py-6 text-center text-xs text-foreground-disabled">Loading…</p>;
  if (rows.length === 0) return <p className="py-6 text-center text-xs text-foreground-disabled">No organizations assigned to this jurisdiction yet.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-xs">
        <thead className="bg-background text-left text-foreground-muted">
          <tr><th className="px-3 py-2">Organization</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Status</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.organization_id} className="border-t border-border-light">
              <td className="px-3 py-2 font-medium text-foreground">{r.organization_name} <span className="font-mono text-foreground-disabled">{r.organization_code}</span></td>
              <td className="px-3 py-2 capitalize text-foreground-secondary">{r.assignment_type}</td>
              <td className="px-3 py-2"><StatusPill status={r.status === "active" ? "active" : "pending"} label={r.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function JurisdictionExplorerPage() {
  const { addToast } = useToast() || {};
  const [searchParams, setSearchParams] = useSearchParams();
  const jurisdictionId = searchParams.get("jurisdiction") ? Number(searchParams.get("jurisdiction")) : null;
  const jurisdictionTab = searchParams.get("tab") || "taxes";

  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  useEffect(() => {
    if (!jurisdictionId) { setDetail(null); return; }
    setLoadingDetail(true);
    hs.getJurisdictionDetail(jurisdictionId).then(setDetail).finally(() => setLoadingDetail(false));
  }, [jurisdictionId]);

  function selectJurisdiction(id) {
    setSearchParams({ jurisdiction: String(id), tab: "taxes" });
  }
  function setTab(tab) {
    setSearchParams({ jurisdiction: String(jurisdictionId), tab });
  }

  async function saveRename() {
    try {
      await hs.upsertJurisdiction({
        id: detail.id, country_id: detail.country_id, level_id: detail.level_id,
        parent_jurisdiction_id: detail.parent_jurisdiction_id, name: renameValue, code: detail.code, is_active: detail.is_active,
      });
      addToast?.("Jurisdiction renamed.", "success");
      setRenaming(false);
      const updated = await hs.getJurisdictionDetail(jurisdictionId);
      setDetail(updated);
    } catch (err) {
      addToast?.(err.message || "Failed to rename.", "error");
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Jurisdiction Explorer</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Browse and configure the generic Country → Jurisdiction Level → Jurisdiction → Tax → Version hierarchy.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <div className="rounded-xl border border-border bg-surface">
          <JurisdictionTreeNav selectedId={jurisdictionId} onSelect={selectJurisdiction} />
        </div>

        <div>
          {!jurisdictionId ? (
            <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-border">
              <p className="text-sm text-foreground-disabled">Select a jurisdiction from the tree to configure it.</p>
            </div>
          ) : loadingDetail || !detail ? (
            <p className="py-8 text-center text-sm text-foreground-disabled">Loading…</p>
          ) : (
            <div className="rounded-xl border border-border bg-surface p-5">
              <div className="mb-4 flex items-start justify-between">
                <div>
                  <p className="mb-1 flex items-center gap-1 text-[11px] text-foreground-disabled">
                    {detail.breadcrumb.map((n, i) => (
                      <span key={n.id}>{i > 0 && " / "}{n.name}</span>
                    ))}
                  </p>
                  {renaming ? (
                    <div className="flex items-center gap-2">
                      <input className={inputClass + " w-64"} value={renameValue} onChange={(e) => setRenameValue(e.target.value)} autoFocus />
                      <button type="button" onClick={saveRename} className="rounded p-1.5 text-primary hover:bg-primary/10"><Check size={16} /></button>
                      <button type="button" onClick={() => setRenaming(false)} className="rounded p-1.5 text-foreground-disabled hover:bg-surface-muted"><X size={16} /></button>
                    </div>
                  ) : (
                    <h2 className="flex items-center gap-2 text-xl font-semibold text-foreground">
                      {detail.name}
                      <button type="button" onClick={() => { setRenaming(true); setRenameValue(detail.name); }} className="text-foreground-disabled hover:text-primary"><Pencil size={14} /></button>
                    </h2>
                  )}
                  <p className="mt-0.5 text-xs text-foreground-muted">{detail.level_code}</p>
                </div>
              </div>

              <div className="mb-4 flex items-center gap-1 border-b border-border">
                <button onClick={() => setTab("taxes")} className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${jurisdictionTab === "taxes" ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"}`}>
                  <Receipt size={14} /> Taxes &amp; Rates
                </button>
                <button onClick={() => setTab("applicability")} className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${jurisdictionTab === "applicability" ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"}`}>
                  <UsersIcon size={14} /> Applicability
                </button>
              </div>

              {jurisdictionTab === "taxes" ? (
                <TaxesAndVersions jurisdictionId={jurisdictionId} />
              ) : (
                <ApplicabilityTab jurisdictionId={jurisdictionId} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

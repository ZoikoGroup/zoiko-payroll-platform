import { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck, Plus, RefreshCcw, History, Users as UsersIcon, GitBranch, Building2, ClipboardList, ArrowRight,
} from "lucide-react";
import Modal from "../components/Modal";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";
import { useToast } from "../context/ToastContext";
import {
  getComplianceJurisdictions, getCompliancePolicies, upsertCompliancePolicy,
  getCompliancePolicyVersions, setCompliancePolicyStatus, getCompliancePolicyOrganizations,
  assignCompliancePolicy, listAllOrganizationsBrief, getComplianceConfigurations,
} from "../service/superAdminService";

const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Retired"];
const STATUS_PILL_MAP = {
  Active: "active", Approved: "approved", Draft: "pending", "In Review": "pending",
  QA: "pending", Deprecated: "inactive", Retired: "suspended",
};

const inputClass =
  "w-full rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#1A1816] px-3 py-2 text-sm text-slate-800 dark:text-[#F0EDE8] focus:outline-none focus:ring-2 focus:ring-orange-500/40";
const labelClass = "block text-xs font-medium text-slate-500 dark:text-[#A69B93] mb-1";

function emptyForm(country) {
  return {
    packId: "", jurisdictionCountry: country || "IN", jurisdictionState: "", version: "1.0", status: "Draft",
    effectiveFrom: "", effectiveTo: "", regulatoryAuthority: "", complianceCategory: "",
    changeSummary: "", complianceOwner: "", engineeringOwner: "", sourceReferences: "", nextReviewDate: "",
  };
}

function PolicyFormModal({ mode, initial, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const locked = mode === "newVersion"; // pack identity can't change across versions

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function handleSave() {
    if (!form.packId.trim() || !form.jurisdictionCountry.trim() || !form.version.trim()) {
      addToast?.("Policy ID, country, and version are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "") payload[k] = null;
      });
      await upsertCompliancePolicy(payload);
      addToast?.(mode === "newVersion" ? "New policy version created." : "Policy created.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save policy.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={mode === "newVersion" ? `New Version — ${form.packId}` : "New Compliance Policy"}
      onClose={onClose}
      maxWidth="max-w-2xl"
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Policy ID</label>
          <input value={form.packId} onChange={set("packId")} disabled={locked} className={`${inputClass} ${locked ? "opacity-60" : ""}`} placeholder="IN-PAYROLL-2026-V1" />
        </div>
        <div>
          <label className={labelClass}>Version</label>
          <input value={form.version} onChange={set("version")} className={inputClass} placeholder="1.0 / 1.1 / 2.0" />
        </div>
        <div>
          <label className={labelClass}>Country</label>
          <input value={form.jurisdictionCountry} onChange={set("jurisdictionCountry")} disabled={locked} className={`${inputClass} ${locked ? "opacity-60" : ""}`} placeholder="IN" />
        </div>
        <div>
          <label className={labelClass}>State / Province (optional)</label>
          <input value={form.jurisdictionState || ""} onChange={set("jurisdictionState")} disabled={locked} className={`${inputClass} ${locked ? "opacity-60" : ""}`} placeholder="Telangana" />
        </div>
        <div>
          <label className={labelClass}>Status</label>
          <select value={form.status} onChange={set("status")} className={inputClass}>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Compliance Category</label>
          <input value={form.complianceCategory || ""} onChange={set("complianceCategory")} className={inputClass} placeholder="Payroll Tax / Statutory Filing…" />
        </div>
        <div>
          <label className={labelClass}>Effective From</label>
          <input type="date" value={form.effectiveFrom || ""} onChange={set("effectiveFrom")} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Effective To</label>
          <input type="date" value={form.effectiveTo || ""} onChange={set("effectiveTo")} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Regulatory Authority</label>
          <input value={form.regulatoryAuthority || ""} onChange={set("regulatoryAuthority")} className={inputClass} placeholder="HMRC / IRS / CBDT…" />
        </div>
        <div>
          <label className={labelClass}>Next Review Date</label>
          <input type="date" value={form.nextReviewDate || ""} onChange={set("nextReviewDate")} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Compliance Owner</label>
          <input value={form.complianceOwner || ""} onChange={set("complianceOwner")} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Engineering Owner</label>
          <input value={form.engineeringOwner || ""} onChange={set("engineeringOwner")} className={inputClass} />
        </div>
        <div className="sm:col-span-2">
          <label className={labelClass}>Change Summary</label>
          <textarea value={form.changeSummary || ""} onChange={set("changeSummary")} rows={2} className={inputClass} placeholder="What changed in this version…" />
        </div>
        <div className="sm:col-span-2">
          <label className={labelClass}>Source References</label>
          <textarea value={form.sourceReferences || ""} onChange={set("sourceReferences")} rows={2} className={inputClass} />
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 dark:border-[#38312D] px-4 py-2 text-sm text-slate-600 dark:text-[#A69B93] hover:bg-slate-50 dark:hover:bg-white/5">
          Cancel
        </button>
        <button type="button" onClick={handleSave} disabled={saving} className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
}

function VersionHistoryModal({ packId, versions, onClose }) {
  return (
    <Modal title={`Version History — ${packId}`} onClose={onClose} maxWidth="max-w-2xl">
      {versions.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-400 dark:text-[#756B64]">No versions found.</p>
      ) : (
        <div className="space-y-3">
          {versions.map((v) => (
            <div key={v.id} className="rounded-lg border border-slate-200 dark:border-[#38312D] p-3.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-[#F0EDE8]">
                  <GitBranch size={14} className="text-slate-400" /> v{v.version}
                </span>
                <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-500 dark:text-[#A69B93]">
                <span>Created: {v.createdAt ? new Date(v.createdAt).toLocaleDateString() : "—"}</span>
                <span>Effective: {v.effectiveFrom || "—"} → {v.effectiveTo || "—"}</span>
              </div>
              {v.changeSummary && (
                <p className="mt-2 text-sm text-slate-600 dark:text-[#D8D2CB]">{v.changeSummary}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

function AssignOrgsModal({ policy, orgs, assignedOrgIds, setAssignedOrgIds, onClose, onSave, saving }) {
  const [search, setSearch] = useState("");
  const filtered = orgs.filter((o) =>
    (o.organization_name || o.organizationName || "").toLowerCase().includes(search.toLowerCase())
  );

  function toggle(id) {
    setAssignedOrgIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <Modal title={`Assign Policy — ${policy.packId} v${policy.version}`} onClose={onClose} maxWidth="max-w-lg">
      <SearchInput value={search} onChange={setSearch} placeholder="Search organizations…" className="mb-3" />
      <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-200 dark:border-[#38312D]">
        {filtered.length === 0 ? (
          <p className="p-4 text-center text-sm text-slate-400 dark:text-[#756B64]">No organizations found.</p>
        ) : (
          filtered.map((o) => (
            <label key={o.id} className="flex items-center gap-3 border-b border-slate-100 dark:border-[#38312D] px-3.5 py-2.5 last:border-b-0 hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer">
              <input type="checkbox" checked={assignedOrgIds.includes(o.id)} onChange={() => toggle(o.id)} className="h-4 w-4 rounded border-slate-300" />
              <span className="flex-1 text-sm text-slate-700 dark:text-[#F0EDE8]">{o.organization_name || o.organizationName}</span>
              <span className="text-xs font-mono text-slate-400 dark:text-[#756B64]">{o.organization_code || o.organizationCode}</span>
            </label>
          ))
        )}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 dark:border-[#38312D] px-4 py-2 text-sm text-slate-600 dark:text-[#A69B93] hover:bg-slate-50 dark:hover:bg-white/5">
          Cancel
        </button>
        <button type="button" onClick={onSave} disabled={saving} className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50">
          {saving ? "Applying…" : `Apply to ${assignedOrgIds.length} organization(s)`}
        </button>
      </div>
    </Modal>
  );
}

export default function CompliancePage() {
  const { addToast } = useToast() || {};
  const [viewMode, setViewMode] = useState("policies"); // "policies" | "orgConfigs"
  const [jurisdictions, setJurisdictions] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [configurations, setConfigurations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const [formState, setFormState] = useState(null); // { mode, initial }
  const [historyState, setHistoryState] = useState(null); // { packId, versions }
  const [assignState, setAssignState] = useState(null); // { policy, orgs, assignedOrgIds, saving }

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [j, p, c] = await Promise.all([
        getComplianceJurisdictions(),
        getCompliancePolicies({
          country: countryFilter || undefined,
          status: statusFilter || undefined,
          search: search || undefined,
        }),
        getComplianceConfigurations({ country: countryFilter || undefined, search: search || undefined }),
      ]);
      setJurisdictions(j);
      setPolicies(p);
      setConfigurations(c);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [countryFilter, statusFilter, search]);

  useEffect(() => { load(); }, [load]);

  async function openHistory(policy) {
    setHistoryState({ packId: policy.packId, versions: [] });
    try {
      const versions = await getCompliancePolicyVersions(policy.packId);
      setHistoryState({ packId: policy.packId, versions });
    } catch (err) {
      addToast?.(err.message || "Failed to load version history.", "error");
      setHistoryState(null);
    }
  }

  async function openAssign(policy) {
    setAssignState({ policy, orgs: [], assignedOrgIds: [], saving: false });
    try {
      const [orgList, applied] = await Promise.all([
        listAllOrganizationsBrief(),
        getCompliancePolicyOrganizations(policy.id),
      ]);
      setAssignState({
        policy,
        orgs: orgList.organizations || [],
        assignedOrgIds: applied.map((o) => o.id),
        saving: false,
      });
    } catch (err) {
      addToast?.(err.message || "Failed to load organizations.", "error");
      setAssignState(null);
    }
  }

  async function handleAssignSave() {
    if (!assignState) return;
    setAssignState((s) => ({ ...s, saving: true }));
    try {
      await assignCompliancePolicy(assignState.policy.id, assignState.assignedOrgIds);
      addToast?.("Policy assignment updated.", "success");
      setAssignState(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to assign policy.", "error");
      setAssignState((s) => ({ ...s, saving: false }));
    }
  }

  async function handleStatusChange(policy, status) {
    try {
      await setCompliancePolicyStatus(policy.id, status);
      addToast?.(`Policy set to ${status}.`, "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to update status.", "error");
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-[#F0EDE8] flex items-center gap-2">
            <ShieldCheck size={22} className="text-orange-500" /> Compliance
          </h1>
          <p className="text-sm text-slate-500 dark:text-[#A69B93] mt-0.5">
            Jurisdiction compliance policies, versioning, and organization assignment.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-slate-300 dark:border-[#38312D] px-3 py-2 text-sm text-slate-600 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
          <button
            onClick={() => setFormState({ mode: "create", initial: emptyForm(countryFilter) })}
            className="flex items-center gap-2 rounded-lg bg-orange-500 px-3.5 py-2 text-sm font-medium text-white hover:bg-orange-600"
          >
            <Plus size={15} /> New Policy
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-5">
        <button
          onClick={() => setViewMode("policies")}
          className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
            viewMode === "policies"
              ? "bg-orange-500 text-white"
              : "bg-white dark:bg-[#221D1A] dark:border dark:border-[#38312D] text-slate-600 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/5"
          }`}
        >
          <ShieldCheck size={15} /> Policies
        </button>
        <button
          onClick={() => setViewMode("orgConfigs")}
          className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
            viewMode === "orgConfigs"
              ? "bg-orange-500 text-white"
              : "bg-white dark:bg-[#221D1A] dark:border dark:border-[#38312D] text-slate-600 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/5"
          }`}
        >
          <ClipboardList size={15} /> Organization Compliance
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={viewMode === "policies" ? "Search policy, authority, category…" : "Search organization, pack…"}
          className="w-64"
        />
        <select
          value={countryFilter}
          onChange={(e) => setCountryFilter(e.target.value)}
          className="rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#221D1A] py-2 px-3 text-sm text-slate-700 dark:text-[#F0EDE8]"
        >
          <option value="">All Jurisdictions</option>
          {jurisdictions.map((j) => <option key={j.code} value={j.code}>{j.name}</option>)}
        </select>
        {viewMode === "policies" && (
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#221D1A] py-2 px-3 text-sm text-slate-700 dark:text-[#F0EDE8]"
          >
            <option value="">All Statuses</option>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {viewMode === "orgConfigs" ? (
        <div className="bg-white dark:bg-[#221D1A] rounded-xl shadow-sm dark:border dark:border-[#38312D] overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-slate-50 dark:bg-[#1A1816] text-left text-xs text-slate-500 dark:text-[#A69B93]">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Jurisdiction</th>
                <th className="px-4 py-3">Current Pack (as configured)</th>
                <th className="px-4 py-3">Active Versioned Policy</th>
                <th className="px-4 py-3">Configured</th>
                <th className="px-4 py-3">Last Updated</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {configurations.map((c) => (
                <tr key={c.organizationId} className="border-t border-slate-100 dark:border-[#38312D]">
                  <td className="px-4 py-3 font-medium text-slate-800 dark:text-[#F0EDE8]">
                    {c.organizationName} <span className="ml-1 font-mono text-xs text-slate-400 dark:text-[#756B64]">{c.organizationCode}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-[#D8D2CB]">
                    {c.jurisdictionCountry || "—"}{c.jurisdictionState ? ` / ${c.jurisdictionState}` : ""}
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-[#A69B93]">{c.compliancePack || "—"}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-[#D8D2CB]">
                    {c.activePolicyId ? `${c.activePolicyId} (v${c.activePolicyVersion})` : "— Not linked to a policy —"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={c.isConfigured ? "active" : "pending"} label={c.isConfigured ? "Configured" : "Not configured"} />
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 dark:text-[#A69B93]">
                    {c.updatedAt ? new Date(c.updatedAt).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      title="Create a versioned policy from this organization's current setup"
                      onClick={() => setFormState({
                        mode: "create",
                        initial: {
                          ...emptyForm(c.jurisdictionCountry),
                          jurisdictionCountry: c.jurisdictionCountry || "IN",
                          jurisdictionState: c.jurisdictionState || "",
                          complianceCategory: c.compliancePack || "",
                        },
                      })}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 dark:border-[#38312D] px-2.5 py-1.5 text-xs font-medium text-slate-600 dark:text-[#A69B93] hover:bg-slate-100 dark:hover:bg-white/10"
                    >
                      Create Policy <ArrowRight size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && configurations.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
              <Building2 size={28} className="text-slate-300 dark:text-[#38312D]" />
              <p className="text-sm text-slate-400 dark:text-[#756B64]">No organization compliance configurations match these filters.</p>
            </div>
          )}
        </div>
      ) : (
      <div className="bg-white dark:bg-[#221D1A] rounded-xl shadow-sm dark:border dark:border-[#38312D] overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-slate-50 dark:bg-[#1A1816] text-left text-xs text-slate-500 dark:text-[#A69B93]">
            <tr>
              <th className="px-4 py-3">Policy</th>
              <th className="px-4 py-3">Jurisdiction</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Version</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Effective</th>
              <th className="px-4 py-3">Last Updated</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.id} className="border-t border-slate-100 dark:border-[#38312D]">
                <td className="px-4 py-3 font-medium text-slate-800 dark:text-[#F0EDE8]">{p.packId}</td>
                <td className="px-4 py-3 text-slate-600 dark:text-[#D8D2CB]">
                  {p.jurisdictionCountry}{p.jurisdictionState ? ` / ${p.jurisdictionState}` : ""}
                </td>
                <td className="px-4 py-3 text-slate-500 dark:text-[#A69B93]">{p.complianceCategory || "—"}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500 dark:text-[#A69B93]">v{p.version}</td>
                <td className="px-4 py-3">
                  <select
                    value={p.status}
                    onChange={(e) => handleStatusChange(p, e.target.value)}
                    className="rounded-md border-0 bg-transparent text-xs font-medium focus:outline-none focus:ring-1 focus:ring-orange-400"
                  >
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500 dark:text-[#A69B93]">
                  {p.effectiveFrom || "—"} → {p.effectiveTo || "—"}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500 dark:text-[#A69B93]">
                  {p.updatedAt ? new Date(p.updatedAt).toLocaleDateString() : new Date(p.createdAt).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button title="Version history" onClick={() => openHistory(p)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-600 dark:hover:text-[#F0EDE8]">
                      <History size={15} />
                    </button>
                    <button title="Assign to organizations" onClick={() => openAssign(p)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-600 dark:hover:text-[#F0EDE8]">
                      <UsersIcon size={15} />
                    </button>
                    <button
                      title="Create new version"
                      onClick={() => setFormState({
                        mode: "newVersion",
                        initial: {
                          ...emptyForm(p.jurisdictionCountry),
                          packId: p.packId, jurisdictionCountry: p.jurisdictionCountry, jurisdictionState: p.jurisdictionState || "",
                          complianceCategory: p.complianceCategory || "", regulatoryAuthority: p.regulatoryAuthority || "",
                          complianceOwner: p.complianceOwner || "", engineeringOwner: p.engineeringOwner || "",
                          version: "", status: "Draft",
                        },
                      })}
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-600 dark:hover:text-[#F0EDE8]"
                    >
                      <GitBranch size={15} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && policies.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Building2 size={28} className="text-slate-300 dark:text-[#38312D]" />
            <p className="text-sm text-slate-400 dark:text-[#756B64]">No compliance policies match these filters.</p>
          </div>
        )}
      </div>
      )}

      {formState && (
        <PolicyFormModal
          mode={formState.mode}
          initial={formState.initial}
          onClose={() => setFormState(null)}
          onSaved={() => { setFormState(null); load(); }}
        />
      )}
      {historyState && (
        <VersionHistoryModal packId={historyState.packId} versions={historyState.versions} onClose={() => setHistoryState(null)} />
      )}
      {assignState && (
        <AssignOrgsModal
          policy={assignState.policy}
          orgs={assignState.orgs}
          assignedOrgIds={assignState.assignedOrgIds}
          setAssignedOrgIds={(updater) => setAssignState((s) => ({ ...s, assignedOrgIds: typeof updater === "function" ? updater(s.assignedOrgIds) : updater }))}
          saving={assignState.saving}
          onClose={() => setAssignState(null)}
          onSave={handleAssignSave}
        />
      )}
    </div>
  );
}

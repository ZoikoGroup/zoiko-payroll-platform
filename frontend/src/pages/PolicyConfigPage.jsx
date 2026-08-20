import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, FileText, Plus, X, Lock, Loader2 } from "lucide-react";
import { useToast } from "../context/ToastContext";
import StatusPill from "../components/StatusPill";
import { upsertCompliancePolicy, getCompliancePolicyVersions } from "../service/superAdminService";
import { COUNTRY_CODE_TO_ROUTE } from "./JurisdictionCompliance";
import { CALCULATION_MODE_LABELS, EMPLOYEE_CATEGORY_LABELS } from "../service/payrollService";
import {
  STATUS_OPTIONS, STATUS_PILL_MAP, inputClass, compactInputClass, emptyForm, slugify,
  CATEGORY_KEYS, CATEGORY_FIELDS, OVERTIME_FIELDS,
  getLockNode, setLockNode, LockableField,
} from "./policyFormShared";

// One field's label row — required marker and/or a lock indicator (for a
// field that's disabled because this is a "New Version", not editable
// because of anything the value itself does) sit next to the label text
// instead of being buried in prose.
function FieldLabel({ children, required, locked }) {
  return (
    <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-foreground-muted">
      {children}
      {required && <span className="text-error">*</span>}
      {locked && <Lock size={11} className="ml-auto text-foreground-disabled" />}
    </label>
  );
}

// Best-effort next-version suggestion (e.g. "1.0" -> "1.1") — a starting
// point for the admin to confirm/adjust, not a guaranteed-unique value.
function _bumpVersion(v) {
  const num = parseFloat(v);
  return isNaN(num) ? `${v}-new` : (num + 0.1).toFixed(1);
}

function FieldError({ message }) {
  if (!message) return null;
  return <p className="mt-1 text-[11px] text-error">{message}</p>;
}

// A section of the page gets exactly one border, one title, one optional
// description — no further nested boxes around its own content. Employee
// Category cards / Allowance rows / LockableFields still get their own
// light border since each is a genuinely distinct configurable item, not
// redundant wrapping.
function Section({ title, description, children }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 sm:p-6">
      <div className="mb-5">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-1 text-xs text-foreground-muted">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function MetaChip({ label, children }) {
  if (!children) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1 text-xs">
      <span className="text-foreground-disabled">{label}</span>
      <span className="font-medium text-foreground">{children}</span>
    </span>
  );
}

// One row of the Allowance Components editor — label + %/flat amount +
// an "allow override" gate for the whole component (not per-field like
// LockableField; a partially-locked allowance isn't a real use case).
function AllowanceComponentRow({ node, onChange, onRemove }) {
  const value = node.value || {};
  const allowOverride = node.allowOverride !== false;
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-border bg-surface p-2.5 sm:grid-cols-[1fr_110px_110px_auto_auto] sm:items-center">
      <input
        value={value.label ?? ""}
        onChange={(e) => onChange({ value: { ...value, label: e.target.value } })}
        placeholder="Transport Allowance"
        className={compactInputClass}
      />
      <input
        type="number"
        min={0}
        value={value.pct ?? ""}
        onChange={(e) => onChange({ value: { ...value, pct: e.target.value === "" ? null : Number(e.target.value), flat_amount: null } })}
        placeholder="% of gross"
        className={compactInputClass}
      />
      <input
        type="number"
        min={0}
        value={value.flat_amount ?? ""}
        onChange={(e) => onChange({ value: { ...value, flat_amount: e.target.value === "" ? null : Number(e.target.value), pct: null } })}
        placeholder="Flat amount"
        className={compactInputClass}
      />
      <label className="flex items-center gap-1 whitespace-nowrap text-[10px] text-foreground-disabled">
        <input
          type="checkbox"
          checked={allowOverride}
          onChange={(e) => onChange({ allowOverride: e.target.checked })}
          className="h-3.5 w-3.5 rounded border-slate-300"
        />
        Allow override
      </label>
      <button type="button" onClick={onRemove} className="rounded-md p-1.5 text-foreground-disabled hover:bg-error/10 hover:text-error" title="Remove">
        <X size={14} />
      </button>
    </div>
  );
}

// Replaces a blocking window.prompt() with an inline reveal — clicking
// "Add" opens a name input right where the button was, Enter/Add commits
// it, Escape/X discards it, and nothing else on the page moves or reloads.
function AddAllowanceComponent({ onAdd }) {
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");

  function submit() {
    if (!label.trim()) return;
    onAdd(label.trim());
    setLabel("");
    setAdding(false);
  }

  if (!adding) {
    return (
      <button
        type="button"
        onClick={() => setAdding(true)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:border-primary hover:bg-surface-muted hover:text-primary"
      >
        <Plus size={13} /> Add Allowance Component
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-surface p-2">
      <input
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") { setAdding(false); setLabel(""); }
        }}
        placeholder="e.g. Transport Allowance"
        className={compactInputClass}
      />
      <button type="button" onClick={submit} className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover">
        Add
      </button>
      <button
        type="button"
        onClick={() => { setAdding(false); setLabel(""); }}
        className="shrink-0 rounded-md p-1.5 text-foreground-disabled hover:bg-surface-muted"
        title="Cancel"
      >
        <X size={14} />
      </button>
    </div>
  );
}

// Full-page Policy configuration — was previously a small modal
// (PolicyFormModal's `!isTax` branch in the old pages/CompliancePage.jsx,
// since retired — its tax-pack CRUD is gone, but policy packs are a
// separate system and this page's own route/logic is unaffected). Policy
// configs have more to review/scroll through (calculation mode, salary
// structure, six employee categories, overtime rule) than a modal
// comfortably fits, so this got its own route instead.
//
// Loadable standalone via URL query params (not router state, which broke
// on a direct load/refresh/bookmark since it only exists in memory from
// whatever page navigated here): `?mode=new` (blank form, optionally
// `&country=IN&state=Maharashtra` to prefill jurisdiction), or
// `?mode=edit&packId=X&version=Y` / `?mode=newVersion&packId=X&version=Y`
// to load a specific existing version via the same
// getCompliancePolicyVersions(packId) call the version-history view
// already uses — no new endpoint needed.
export default function PolicyConfigPage() {
  const { addToast } = useToast() || {};
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const mode = searchParams.get("mode") || "new";
  const packIdParam = searchParams.get("packId");
  const versionParam = searchParams.get("version");

  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(!!packIdParam);
  const [saving, setSaving] = useState(false);
  const [touched, setTouched] = useState({});

  useEffect(() => {
    if (!packIdParam) {
      setForm(emptyForm(searchParams.get("country"), searchParams.get("state"), "policy"));
      return;
    }
    setLoading(true);
    getCompliancePolicyVersions(packIdParam)
      .then((versions) => {
        const match = versionParam ? versions.find((v) => v.version === versionParam) : versions[0];
        if (!match) {
          addToast?.(`Version ${versionParam || ""} of "${packIdParam}" not found.`, "error");
          navigate("/super-admin/compliance", { replace: true });
          return;
        }
        if (mode === "newVersion") {
          // A new version must be a genuinely new row — carrying over the
          // fetched version's `id` would make upsertCompliancePolicy
          // overwrite that OLD version in place instead of creating a new
          // one (the backend keys off `id` when present). Strip it, and
          // suggest (not lock) a bumped version number — unlike the old
          // flow (a human picked "new version" from a version list and
          // this page trusted a pre-computed number), loading straight
          // from a URL means nobody has verified the suggestion, so the
          // Version field stays editable here specifically.
          const { id: _fetchedId, ...rest } = match;
          setForm({ ...rest, version: _bumpVersion(match.version), policyDefaults: match.policyDefaults || {} });
        } else {
          setForm({ ...match, policyDefaults: match.policyDefaults || {} });
        }
      })
      .catch((err) => {
        addToast?.(err.message || "Failed to load policy.", "error");
        navigate("/super-admin/compliance", { replace: true });
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packIdParam, versionParam]);

  if (loading || !form) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 size={20} className="animate-spin text-foreground-disabled" />
      </div>
    );
  }

  // Country/state identify a specific pack version and can't change across
  // versions OR in-place edits — only a genuinely new pack picks new ones.
  // Policy ID itself stays editable in "edit" (the backend looks the row
  // up by its real database id, not by packId/version, so renaming never
  // orphans anything), same rule Tax's own edit mode already uses.
  const locked = mode === "newVersion" || mode === "edit";
  // Version specifically stays editable for "newVersion" (see the
  // _bumpVersion suggestion above) — only truly locked when editing an
  // existing version in place, where the version number must not change.
  const versionLocked = mode === "edit";
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const markTouched = (field) => () => setTouched((t) => ({ ...t, [field]: true }));

  // Same three fields handleSave has always required — this only makes
  // that existing requirement visible before the toast fires, it doesn't
  // add any new rule.
  const errors = {
    packId: form.packId.trim() ? "" : "Policy ID is required.",
    jurisdictionCountry: form.jurisdictionCountry.trim() ? "" : "Country is required.",
    version: form.version.trim() ? "" : "Version is required.",
  };
  const isValid = !errors.packId && !errors.jurisdictionCountry && !errors.version;
  const dateOrderInvalid = form.effectiveFrom && form.effectiveTo && form.effectiveTo < form.effectiveFrom;

  function goBack() {
    // Return to the specific country's Jurisdiction Compliance page, not
    // the bare landing page — this route only ever gets here via a link
    // that already carries `country` (JurisdictionLayout's New/Edit/New
    // Version buttons all include it). Falls back to the landing page
    // only if someone lands on this URL directly with no country param.
    const country = searchParams.get("country");
    const slug = country && COUNTRY_CODE_TO_ROUTE[country];
    navigate(slug ? `/super-admin/compliance/${slug}` : "/super-admin/compliance");
  }

  async function handleSave() {
    setTouched({ packId: true, jurisdictionCountry: true, version: true });
    if (!isValid) {
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
      addToast?.(
        mode === "edit" ? "Policy updated." : mode === "newVersion" ? "New version created." : "Policy created.",
        "success",
      );
      goBack();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  const allowanceEntries = Object.entries(form.policyDefaults?.allowance_components || {});

  return (
    <div>
      <button
        type="button"
        onClick={goBack}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-foreground-secondary hover:text-foreground"
      >
        <ArrowLeft size={15} /> Back to Compliance
      </button>

      <div className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-category-teal/10 px-2.5 py-1 text-xs font-bold text-category-teal">
            <FileText size={12} /> Policy
          </span>
          <h1 className="text-xl font-semibold text-foreground">
            {mode === "edit"
              ? `Edit Policy — ${form.packId}`
              : mode === "newVersion"
              ? `New Version — ${form.packId}`
              : "New Policy"}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MetaChip label="ID">{form.packId || "—"}</MetaChip>
          <MetaChip label="Country">{form.jurisdictionCountry || "—"}</MetaChip>
          {form.jurisdictionState && <MetaChip label="State">{form.jurisdictionState}</MetaChip>}
          <MetaChip label="Version">{form.version || "—"}</MetaChip>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1 text-xs">
            <span className="text-foreground-disabled">Status</span>
            <StatusPill status={STATUS_PILL_MAP[form.status] || "pending"} label={form.status} />
          </span>
        </div>
      </div>

      <div className="space-y-6">
        <Section title="Policy Information" description="Identity and lifecycle for this policy version.">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <div>
              <FieldLabel required>Policy ID</FieldLabel>
              <input
                value={form.packId}
                onChange={set("packId")}
                onBlur={markTouched("packId")}
                className={`${inputClass} ${touched.packId && errors.packId ? "border-error focus:ring-error/30" : ""}`}
                placeholder="IN-POLICY-2026-V1"
              />
              <FieldError message={touched.packId ? errors.packId : ""} />
            </div>
            <div>
              <FieldLabel required locked={versionLocked}>Version</FieldLabel>
              <input
                value={form.version}
                onChange={set("version")}
                onBlur={markTouched("version")}
                disabled={versionLocked}
                className={`${inputClass} ${touched.version && errors.version ? "border-error focus:ring-error/30" : ""}`}
                placeholder="1.0 / 1.1 / 2.0"
              />
              <FieldError message={touched.version ? errors.version : ""} />
            </div>
            <div>
              <FieldLabel required locked={locked}>Country</FieldLabel>
              <input
                value={form.jurisdictionCountry}
                onChange={set("jurisdictionCountry")}
                onBlur={markTouched("jurisdictionCountry")}
                disabled={locked}
                className={`${inputClass} ${touched.jurisdictionCountry && errors.jurisdictionCountry ? "border-error focus:ring-error/30" : ""}`}
                placeholder="IN"
              />
              <FieldError message={touched.jurisdictionCountry ? errors.jurisdictionCountry : ""} />
            </div>
            <div>
              <FieldLabel locked={locked}>State / Province</FieldLabel>
              <input
                value={form.jurisdictionState || ""}
                onChange={set("jurisdictionState")}
                disabled={locked}
                className={inputClass}
                placeholder="Telangana (optional)"
              />
            </div>
            <div>
              <FieldLabel>Status</FieldLabel>
              <select value={form.status} onChange={set("status")} className={inputClass}>
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <FieldLabel>Effective From</FieldLabel>
              <input type="date" value={form.effectiveFrom || ""} onChange={set("effectiveFrom")} className={inputClass} />
            </div>
            <div>
              <FieldLabel>Effective To</FieldLabel>
              <input type="date" value={form.effectiveTo || ""} onChange={set("effectiveTo")} className={inputClass} />
              <FieldError message={dateOrderInvalid ? "Effective To is before Effective From." : ""} />
            </div>
          </div>
        </Section>

        <Section
          title="Calculation Settings"
          description="How this policy's pay is calculated, and the default salary split it starts organizations from."
        >
          <div className="space-y-4">
            <div className="max-w-xs">
              <LockableField
                label="Calculation Mode"
                node={getLockNode(form.policyDefaults, ["calculation_mode"])}
                type="select"
                choices={Object.entries(CALCULATION_MODE_LABELS).map(([value, label]) => ({ value, label }))}
                onChangeValue={(value) => setLockNode(setForm, ["calculation_mode"], { value })}
                onChangeAllow={(allowOverride) => setLockNode(setForm, ["calculation_mode"], { allowOverride })}
              />
            </div>
            <div className="border-t border-border-light pt-4">
              <p className="mb-1 text-xs font-medium text-foreground-secondary">Salary Structure</p>
              <p className="mb-3 text-[11px] text-foreground-disabled">
                Percentage of monthly gross allocated as Basic and HRA for employees without their own explicit
                amounts set — Special Allowance (below) is always whatever's left of gross.
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <LockableField
                  label="Basic % of Gross"
                  node={getLockNode(form.policyDefaults, ["basic_pct"])}
                  type="number"
                  onChangeValue={(value) => setLockNode(setForm, ["basic_pct"], { value })}
                  onChangeAllow={(allowOverride) => setLockNode(setForm, ["basic_pct"], { allowOverride })}
                />
                <LockableField
                  label="HRA % of Gross"
                  node={getLockNode(form.policyDefaults, ["hra_pct"])}
                  type="number"
                  onChangeValue={(value) => setLockNode(setForm, ["hra_pct"], { value })}
                  onChangeAllow={(allowOverride) => setLockNode(setForm, ["hra_pct"], { allowOverride })}
                />
              </div>
            </div>
          </div>
        </Section>

        <Section
          title="Compensation Components"
          description="Special Allowance is always whatever's left of gross after Basic, HRA, and the named components below. Add a component for anything organizations should break out as its own line item — Transport, Medical, or any custom name."
        >
          <div className="space-y-2">
            {allowanceEntries.map(([key, node]) => (
              <AllowanceComponentRow
                key={key}
                node={node || {}}
                onChange={(patch) => setLockNode(setForm, ["allowance_components", key], patch)}
                onRemove={() => setForm((f) => {
                  const next = { ...(f.policyDefaults || {}) };
                  const components = { ...(next.allowance_components || {}) };
                  delete components[key];
                  next.allowance_components = components;
                  return { ...f, policyDefaults: next };
                })}
              />
            ))}
            {allowanceEntries.length === 0 && (
              <p className="rounded-lg border border-dashed border-border-light px-3 py-4 text-center text-xs text-foreground-disabled">
                No named components yet — everything folds into Special Allowance.
              </p>
            )}
            <AddAllowanceComponent
              onAdd={(label) => {
                const key = slugify(label);
                setLockNode(setForm, ["allowance_components", key], {
                  value: { label, pct: null, flat_amount: null },
                  allowOverride: true,
                });
              }}
            />
          </div>
        </Section>

        <Section
          title="Employee Categories"
          description="Default working-hours and leave-eligibility rules per employment type — each can be locked or left overridable independently."
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {CATEGORY_KEYS.map((category) => (
              <div key={category} className="rounded-lg border border-border-light p-3">
                <p className="mb-2.5 text-xs font-semibold text-foreground">{EMPLOYEE_CATEGORY_LABELS[category]}</p>
                <div className="space-y-2">
                  {CATEGORY_FIELDS.map((field) => (
                    <LockableField
                      key={field.key}
                      label={field.label}
                      node={getLockNode(form.policyDefaults, ["employee_categories", category, field.key])}
                      type={field.type}
                      onChangeValue={(value) => setLockNode(setForm, ["employee_categories", category, field.key], { value })}
                      onChangeAllow={(allowOverride) => setLockNode(setForm, ["employee_categories", category, field.key], { allowOverride })}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Additional Policy Configuration" description="Overtime eligibility and approval defaults.">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {OVERTIME_FIELDS.map((field) => (
              <LockableField
                key={field.key}
                label={field.label}
                node={getLockNode(form.policyDefaults, ["overtime_rule", field.key])}
                type={field.type}
                onChangeValue={(value) => setLockNode(setForm, ["overtime_rule", field.key], { value })}
                onChangeAllow={(allowOverride) => setLockNode(setForm, ["overtime_rule", field.key], { allowOverride })}
              />
            ))}
          </div>
        </Section>
      </div>

      <div className="sticky bottom-0 z-10 -mx-4 mt-8 flex items-center justify-between gap-4 border-t border-border bg-surface/95 px-4 py-4 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <p className="text-xs text-foreground-muted">
          {!isValid ? "Fill in the required fields above to save." : " "}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={goBack}
            className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !isValid}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            {saving
              ? "Saving…"
              : mode === "edit"
              ? "Save Changes"
              : mode === "newVersion"
              ? "Save New Version"
              : "Save Policy"}
          </button>
        </div>
      </div>
    </div>
  );
}

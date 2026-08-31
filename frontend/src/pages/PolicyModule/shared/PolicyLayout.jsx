import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, FileText, Loader2 } from "lucide-react";
import { useToast } from "../../../context/ToastContext";
import StatusPill from "../../../components/StatusPill";
import { upsertCompliancePolicy, getCompliancePolicyVersions } from "../../../service/superAdminService";
import { COUNTRY_CODE_TO_ROUTE } from "../../JurisdictionCompliance";
import { CALCULATION_MODE_LABELS, EMPLOYEE_CATEGORY_LABELS } from "../../../service/payrollService";
import {
  STATUS_OPTIONS, STATUS_PILL_MAP, inputClass, emptyForm, slugify,
  CATEGORY_KEYS, DEFAULT_CATEGORY_FIELDS, DEFAULT_OVERTIME_FIELDS, DEFAULT_PAY_TYPE_CHOICES,
  getLockNode, setLockNode,
} from "./policyUtils";
import {
  Section, FieldLabel, FieldError, MetaChip, LockableField,
  AllowanceComponentRow, AddAllowanceComponent,
} from "./SharedPolicyComponents";

// Best-effort next-version suggestion (e.g. "1.0" -> "1.1") — a starting
// point for the admin to confirm/adjust, not a guaranteed-unique value.
function _bumpVersion(v) {
  const num = parseFloat(v);
  return isNaN(num) ? `${v}-new` : (num + 0.1).toFixed(1);
}

// Shared Policy-pack authoring layout for every jurisdiction — the
// per-jurisdiction PolicyModule pages (INPolicyPage.jsx, USPolicyPage.jsx,
// ...) are thin wrappers around this, each passing its own `country`/
// `countryName` and (optionally) its own `categoryFields`/`overtimeFields`/
// `payTypeChoices`/`extraSections` overrides — mirroring how
// JurisdictionLayout.jsx is the one shared shell every Tax compliance page
// wraps with its own config object. No jurisdiction overrides any of the
// field-list props today (no real per-country policy divergence exists in
// the backend yet), so every page renders identically until one genuinely
// needs to diverge — at which point only that one country's file changes.
//
// `country`/`countryName` are fixed per page (chosen by which jurisdiction
// page rendered this, not a query param or free-text field here) — this is
// the one deliberate behavior change from the old single-page
// PolicyConfigPage.jsx: the Country field is now always locked to the
// page's own jurisdiction (never freely retypeable), so a policy authored
// on the India page can never accidentally end up tagged UK. Everything
// else — load/save/validate/lock semantics — is unchanged.
//
// Loadable standalone via URL query params (not router state, which broke
// on a direct load/refresh/bookmark since it only exists in memory from
// whatever page navigated here): `?mode=new` (blank form, optionally
// `&state=Maharashtra` to prefill jurisdiction), or
// `?mode=edit&packId=X&version=Y` / `?mode=newVersion&packId=X&version=Y`
// to load a specific existing version via the same
// getCompliancePolicyVersions(packId) call the version-history view
// already uses — no new endpoint needed.
export default function PolicyLayout({
  country, countryName,
  categoryFields = DEFAULT_CATEGORY_FIELDS,
  overtimeFields = DEFAULT_OVERTIME_FIELDS,
  payTypeChoices = DEFAULT_PAY_TYPE_CHOICES,
  extraSections,
}) {
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
      setForm(emptyForm(country, searchParams.get("state"), "policy"));
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

  // State can't change across versions or in-place edits — only a
  // genuinely new pack picks a new one (same rule Tax's own edit mode
  // uses). Country used to share this same `locked` condition, but is now
  // always locked regardless of mode (see PolicyLayout's own note above).
  const stateLocked = mode === "newVersion" || mode === "edit";
  // Version specifically stays editable for "newVersion" (see the
  // _bumpVersion suggestion above) — only truly locked when editing an
  // existing version in place, where the version number must not change.
  const versionLocked = mode === "edit";
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const markTouched = (field) => () => setTouched((t) => ({ ...t, [field]: true }));

  // Same three fields handleSave has always required — this only makes
  // that existing requirement visible before the toast fires, it doesn't
  // add any new rule. jurisdictionCountry is always valid now since it's
  // pinned to the page's own `country` prop, never freely typed.
  const errors = {
    packId: form.packId.trim() ? "" : "Policy ID is required.",
    jurisdictionCountry: form.jurisdictionCountry.trim() ? "" : "Country is required.",
    version: form.version.trim() ? "" : "Version is required.",
  };
  const isValid = !errors.packId && !errors.jurisdictionCountry && !errors.version;
  const dateOrderInvalid = form.effectiveFrom && form.effectiveTo && form.effectiveTo < form.effectiveFrom;

  // Fixed-destination redirect — NOT "back" navigation. Used by Cancel and
  // by the post-save redirect, both of which need to reliably land on this
  // jurisdiction's Compliance page regardless of how this page was
  // reached (e.g. a bookmarked/reloaded edit URL has no meaningful browser
  // history to return to). Kept separate from the actual "Back" link below
  // on purpose — see that button's own comment.
  function goToCompliance() {
    const slug = COUNTRY_CODE_TO_ROUTE[country];
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
      goToCompliance();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  const allowanceEntries = Object.entries(form.policyDefaults?.allowance_components || {});

  // Special Allowance is never a configured field — it's always whatever
  // remains of gross after Basic %, HRA %, and any named components. This
  // page works in percentages (org-level defaults, not one employee's
  // actual gross), so the live summary shown alongside it is the
  // remaining percentage, not a currency figure — the real ₹/$ amount
  // only exists once an org applies these defaults to a real employee's
  // gross (computed server-side, see _resolve_salary_split_pct).
  const basicPctValue = Number(getLockNode(form.policyDefaults, ["basic_pct"]).value) || 0;
  const hraPctValue = Number(getLockNode(form.policyDefaults, ["hra_pct"]).value) || 0;
  const pctComponentsTotal = allowanceEntries.reduce((sum, [, node]) => {
    const pct = node?.value?.pct;
    return sum + (typeof pct === "number" && !isNaN(pct) ? pct : 0);
  }, 0);
  const hasFlatComponents = allowanceEntries.some(([, node]) => node?.value?.flat_amount != null);
  const remainingPct = Math.max(0, 100 - basicPctValue - hraPctValue - pctComponentsTotal);
  const specialAllowanceSummary = `${remainingPct}% of Gross${hasFlatComponents ? " − flat-amount components above" : ""} (auto)`;

  return (
    <div>
      <button
        type="button"
        onClick={() => navigate(-1)}
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
              ? `Edit ${countryName} Policy — ${form.packId}`
              : mode === "newVersion"
              ? `New Version — ${form.packId} (${countryName})`
              : `New ${countryName} Policy`}
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
                placeholder={`${country}-POLICY-2026-V1`}
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
              <FieldLabel required locked>Country</FieldLabel>
              <input value={form.jurisdictionCountry} disabled className={inputClass} />
            </div>
            <div>
              <FieldLabel locked={stateLocked}>State / Province</FieldLabel>
              <input
                value={form.jurisdictionState || ""}
                onChange={set("jurisdictionState")}
                disabled={stateLocked}
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

        <Section title="Calculation Settings" description="How this policy's pay is calculated.">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <LockableField
              label="Calculation Mode"
              node={getLockNode(form.policyDefaults, ["calculation_mode"])}
              type="select"
              choices={Object.entries(CALCULATION_MODE_LABELS).map(([value, label]) => ({ value, label }))}
              onChangeValue={(value) => setLockNode(setForm, ["calculation_mode"], { value })}
              onChangeAllow={(allowOverride) => setLockNode(setForm, ["calculation_mode"], { allowOverride })}
            />
            <LockableField
              label="Pay Type"
              node={getLockNode(form.policyDefaults, ["pay_type"])}
              type="select"
              choices={payTypeChoices}
              onChangeValue={(value) => setLockNode(setForm, ["pay_type"], { value })}
              onChangeAllow={(allowOverride) => setLockNode(setForm, ["pay_type"], { allowOverride })}
            />
          </div>
        </Section>

        <Section
          title="Salary Structure & Components"
          description="How monthly gross splits into Basic, HRA, and any named components for organizations without their own explicit amounts set. Special Allowance always absorbs whatever's left of gross — it's never configured directly."
        >
          <div className="space-y-5">
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

            <div className="border-t border-border-light pt-4">
              <p className="mb-2 text-xs font-medium text-foreground-secondary">Additional Compensation Components</p>
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
                  <p className="px-0.5 text-xs text-foreground-disabled">
                    No additional components configured. The remaining gross salary will be allocated to Special Allowance.
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
            </div>

            <div className="flex items-center justify-between rounded-lg bg-surface-muted px-3 py-2.5">
              <span className="text-xs font-medium text-foreground-secondary">Special Allowance</span>
              <span className="text-xs font-semibold text-foreground" title="Automatically calculated — never set directly">
                {specialAllowanceSummary}
              </span>
            </div>
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
                  {categoryFields.map((field) => (
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
            {overtimeFields.map((field) => (
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

        {/* Extension point for a jurisdiction-specific section (e.g. a
            future India-only Gratuity/Leave-Encashment policy block) —
            mirrors indiaComplianceConfig's extraTabs on the Tax side.
            No jurisdiction uses this yet. */}
        {typeof extraSections === "function" && extraSections({ form, setForm, addToast })}
      </div>

      <div className="sticky bottom-0 z-10 -mx-4 mt-8 flex items-center justify-between gap-4 border-t border-border bg-surface/95 px-4 py-4 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <p className="text-xs text-foreground-muted">
          {!isValid ? "Fill in the required fields above to save." : " "}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={goToCompliance}
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

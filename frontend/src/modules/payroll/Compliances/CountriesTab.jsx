import { useState } from "react";
import { Link } from "react-router-dom";
import { Globe, Plus, Star, Trash2, RefreshCcw, AlertTriangle, Lock } from "lucide-react";
import { useAuth } from "../../../context/AuthContext";
import { ROLES } from "../../../config/roles";
import { useToast } from "../ToastContext";
import ConfirmDialog from "../../../components/ConfirmDialog";
import Modal from "../../../components/Modal";
import PlanLimitMessage, { isPlanLimitError, PLAN_SELECTION_ROUTE } from "../../../components/PlanLimitMessage";
import { useEntitledCountries } from "../EntitledCountriesContext";
import { usePayrollSetup } from "../PayrollSetupContext";
import {
  addEntitledCountry,
  removeEntitledCountry,
  setPrimaryCountry,
  replacePrimaryCountry,
} from "../../../service/jurisdictionService";

const PLAN_LABEL = { CORE: "Core", PROFESSIONAL: "Professional", BUSINESS: "Business", ENTERPRISE: "Enterprise" };

// "DE" -> 🇩🇪 via regional-indicator symbols ("UK" is spelled GB in Unicode).
function flagFor(code) {
  const iso = String(code || "").toUpperCase() === "UK" ? "GB" : String(code || "").toUpperCase();
  if (!/^[A-Z]{2}$/.test(iso)) return "";
  return String.fromCodePoint(...[...iso].map((ch) => 0x1f1e6 + ch.charCodeAt(0) - 65));
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

function StatusPill({ status }) {
  const map = {
    ACTIVE: "bg-primary/10 text-primary",
    OVER_LIMIT: "bg-warning/10 text-warning",
  };
  const labels = { ACTIVE: "Active", OVER_LIMIT: "Over plan limit" };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ${map[status] || "bg-surface-muted text-foreground-muted"}`}>
      {labels[status] || status}
    </span>
  );
}

// Compliance > Countries: the countries this organization may add employees
// in, capped by its plan (Core 1, Professional 3, Business 10, Enterprise
// negotiated). The primary country is the registration country and the
// default for new employees. One-country plans swap ("Change country")
// instead of adding.
export default function CountriesTab() {
  const { hasRole } = useAuth();
  const { addToast } = useToast();
  const { refresh: refreshPayrollSetup } = usePayrollSetup();
  const { countries, limit, used, remaining, planCode, canAdd, addable, catalog, enforcementMode, loaded, loading, error, refresh } =
    useEntitledCountries();
  const canEdit = hasRole([ROLES.ADMIN, ROLES.SUPER_ADMIN]);
  const isSingleCountryPlan = limit === 1;

  const [picker, setPicker] = useState(false);
  const [pickedCode, setPickedCode] = useState("");
  // { kind: "remove" | "primary" | "replace", country: {code, name} }
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  const planLabel = planCode ? PLAN_LABEL[planCode] || planCode : null;
  const primary = countries.find((c) => c.isPrimary) || null;
  const overLimitCount = countries.filter((c) => c.status === "OVER_LIMIT").length;
  const countSummary = limit == null
    ? `${used} ${used === 1 ? "country" : "countries"} · unlimited`
    : `${used} of ${limit} ${limit === 1 ? "country" : "countries"}`;
  // The picker lists the full, fixed set of payroll countries; ones that
  // can't be added yet stay visible (disabled) with the reason.
  const pickerCountries = catalog.length ? catalog : addable.map((c) => ({ ...c, available: true }));
  const pendingCount = pickerCountries.filter((c) => c.setupPending).length;
  const pickedCountry = pickerCountries.find((c) => c.code === pickedCode);

  function openPicker() {
    setActionError(null);
    setPickedCode(addable[0]?.code || "");
    setPicker(true);
  }

  // Every mutation is followed by a refetch of the shared entitlement list
  // (employee form / bulk import read it too); a primary change can also
  // move the org's default jurisdiction, so PayrollSetup is refreshed then.
  async function run(action, successMessage, { primaryChanged = false } = {}) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      addToast?.(successMessage, "success");
      setPicker(false);
      setConfirm(null);
    } catch (err) {
      setActionError({ message: err.message || "Something went wrong. Please try again.", trace: err.trace || null });
      setConfirm(null);
    } finally {
      setBusy(false);
      await refresh();
      if (primaryChanged) refreshPayrollSetup();
    }
  }

  function handlePickerSubmit(e) {
    e.preventDefault();
    const country = addable.find((c) => c.code === pickedCode);
    if (!country) return;
    if (isSingleCountryPlan) {
      // Swapping the only country is consequential — confirm first.
      setPicker(false);
      setConfirm({ kind: "replace", country });
      return;
    }
    run(() => addEntitledCountry(country.code), `${country.name} added.`);
  }

  function handleConfirm() {
    const { kind, country } = confirm;
    if (kind === "remove") run(() => removeEntitledCountry(country.code), `${country.name} removed.`);
    if (kind === "primary") run(() => setPrimaryCountry(country.code), `${country.name} is now your primary country.`, { primaryChanged: true });
    if (kind === "replace") run(() => replacePrimaryCountry(country.code), `Your country is now ${country.name}.`, { primaryChanged: true });
  }

  const confirmCopy = confirm && {
    remove: {
      title: `Remove ${confirm.country.name}?`,
      message: `New employees can no longer be added in ${confirm.country.name}, and it stops counting toward your plan's country limit. This is only possible once no employees use ${confirm.country.name}.`,
      label: "Remove country",
    },
    primary: {
      title: `Make ${confirm.country.name} your primary country?`,
      message: `${confirm.country.name} becomes the default country for new employees and for the bulk-import template${primary ? `, replacing ${primary.name}` : ""}. ${primary ? `${primary.name} stays on your list and its employees are unaffected.` : ""}`,
      label: "Set as primary",
    },
    replace: {
      title: `Change your country to ${confirm.country.name}?`,
      message: `Your plan includes one country, so ${primary ? primary.name : "your current country"} will be replaced by ${confirm.country.name}. New employees will be added in ${confirm.country.name}. This is only possible once no employees remain in ${primary ? primary.name : "the current country"}.`,
      label: "Change country",
    },
  }[confirm.kind];

  if (!loaded) {
    return (
      <div className="bg-surface border border-border rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
        {loading ? (
          <p className="text-[13px] text-foreground-muted">Loading countries…</p>
        ) : (
          <>
            <p className="text-[13px] text-error">{error?.message || "Countries could not be loaded."}</p>
            <button
              onClick={refresh}
              className="mt-3 inline-flex items-center gap-1.5 rounded-[10px] border border-border px-4 py-2 text-[12px] font-bold text-foreground hover:border-primary hover:text-primary transition-colors"
            >
              <RefreshCcw size={13} /> Retry
            </button>
          </>
        )}
      </div>
    );
  }

  const addLabel = isSingleCountryPlan ? "Change country" : "Add country";
  const addDisabled = !canEdit || busy || (isSingleCountryPlan ? addable.length === 0 : !canAdd);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-[15px] font-bold text-foreground">Countries</h3>
          <p className="text-[12px] text-foreground-muted mt-0.5">
            The countries your organization can add employees and run payroll in.
          </p>
          <p className="mt-2 text-[13px] font-bold text-foreground">
            {countSummary}
            {planLabel && <span className="ml-2 font-medium text-foreground-muted">· {planLabel} plan</span>}
            {!isSingleCountryPlan && remaining > 0 && (
              <span className="ml-2 font-medium text-primary">
                · you can add {remaining} more {remaining === 1 ? "country" : "countries"}
              </span>
            )}
          </p>
          {primary && (
            <p className="mt-1 text-[12px] text-foreground-muted">
              Default country: <span className="font-semibold text-foreground">{primary.name}</span> — set from your
              registration; new employees default to it.
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <button
            onClick={openPicker}
            disabled={addDisabled}
            className="flex items-center gap-2 rounded-[12px] bg-primary px-4 py-2 text-[13px] font-bold text-white hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSingleCountryPlan ? <RefreshCcw size={14} /> : <Plus size={14} />}
            {addLabel}
          </button>
          {!isSingleCountryPlan && !canAdd && (
            <p className="max-w-xs text-right text-[11px] text-foreground-muted">
              <Lock size={11} className="inline -mt-0.5 mr-1" />
              Your {planLabel ? `${planLabel} ` : ""}plan includes {limit} {limit === 1 ? "country" : "countries"} and all are in use.{" "}
              <Link to={PLAN_SELECTION_ROUTE} className="font-bold text-primary hover:text-primary-hover hover:underline">
                Upgrade to add more
              </Link>
            </p>
          )}
        </div>
      </div>

      {enforcementMode === "warn" && (
        <div className="bg-info/5 border border-info/15 rounded-[14px] px-4 py-3 text-[13px] text-foreground-muted">
          Country limits are currently shown as warnings only — they will be enforced soon.
        </div>
      )}

      {overLimitCount > 0 && (
        <div className="bg-warning/5 border border-warning/15 rounded-[14px] px-4 py-3 text-[13px] text-foreground-muted flex items-start gap-2">
          <AlertTriangle size={14} className="text-warning mt-0.5 shrink-0" />
          <span>
            {overLimitCount === 1 ? "One country is" : `${overLimitCount} countries are`} over your plan&apos;s country limit.
            Existing employees there are kept, but <strong>new employees and payroll in {overLimitCount === 1 ? "that country" : "those countries"} are paused</strong> until
            you <Link to={PLAN_SELECTION_ROUTE} className="font-bold text-primary hover:text-primary-hover hover:underline">upgrade your plan</Link> or
            remove another country.
          </span>
        </div>
      )}

      {actionError && (isPlanLimitError(actionError) ? (
        <PlanLimitMessage message={actionError.message} trace={actionError.trace} />
      ) : (
        <div className="rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">
          {actionError.message}
        </div>
      ))}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {countries.map((c) => {
          const overLimit = c.status === "OVER_LIMIT";
          return (
            <div
              key={c.code}
              className={`bg-surface border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex flex-col gap-4 ${overLimit ? "border-warning/40" : "border-border"}`}
            >
              <div className="flex items-center gap-3">
                <span
                  className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-surface-muted text-[20px] leading-none text-foreground"
                  title={c.code}
                >
                  {flagFor(c.code) || <Globe size={16} />}
                </span>
                <p className="text-[15px] font-bold text-foreground flex-1 min-w-0 truncate">{c.name}</p>
                {c.isPrimary && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-info/10 px-2.5 py-1 text-[11px] font-bold text-info">
                    <Star size={11} /> Default
                  </span>
                )}
              </div>
              <dl className="space-y-1.5 text-[12px]">
                <div className="flex items-center justify-between">
                  <dt className="text-foreground-muted">Status</dt>
                  <dd><StatusPill status={c.status} /></dd>
                </div>
                <div className="flex items-center justify-between">
                  <dt className="text-foreground-muted">Employees</dt>
                  <dd className="font-semibold text-foreground">{c.employeeCount ?? 0}</dd>
                </div>
                <div className="flex items-center justify-between">
                  <dt className="text-foreground-muted">Active since</dt>
                  <dd className="font-semibold text-foreground">{formatDate(c.activatedAt)}</dd>
                </div>
              </dl>
              {c.setupNote && !overLimit && (
                <p className="text-[11px] text-warning">
                  Statutory set-up pending — payroll in {c.name} uses the default rates until Zoiko completes it.
                </p>
              )}
              {overLimit && (
                <p className="text-[11px] text-warning">
                  Over your plan&apos;s limit — new employees and payroll in {c.name} are paused until you upgrade.
                </p>
              )}
              {!c.isPrimary && !isSingleCountryPlan && (
                <div className="flex gap-2">
                  {!overLimit && (
                    <button
                      onClick={() => { setActionError(null); setConfirm({ kind: "primary", country: c }); }}
                      disabled={!canEdit || busy}
                      className="flex flex-1 items-center justify-center gap-1.5 rounded-[10px] border border-border px-3 py-2 text-[12px] font-bold text-foreground hover:border-primary hover:text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Star size={13} /> Set primary
                    </button>
                  )}
                  <button
                    onClick={() => { setActionError(null); setConfirm({ kind: "remove", country: c }); }}
                    disabled={!canEdit || busy}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-[10px] border border-border px-3 py-2 text-[12px] font-bold text-foreground hover:border-error hover:text-error transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Trash2 size={13} /> Remove
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {countries.length === 0 && (
        <div className="bg-surface border border-border rounded-[18px] p-12 shadow-[0_1px_3px_rgba(0,0,0,0.04)] text-center">
          <Globe size={24} className="mx-auto mb-3 text-foreground-muted" />
          <p className="text-[13px] text-foreground-muted">No countries yet. Add one to start adding employees.</p>
        </div>
      )}

      {picker && (
        <Modal title={addLabel} onClose={() => setPicker(false)}>
          <form onSubmit={handlePickerSubmit} className="space-y-4">
            {isSingleCountryPlan && (
              <p className="text-[13px] text-foreground-muted">
                Your plan includes one country. Choosing a new one replaces {primary ? primary.name : "your current country"}.
              </p>
            )}
            {pickerCountries.length === 0 ? (
              <p className="text-[13px] text-foreground-muted">Your organization already has every country Zoiko supports.</p>
            ) : (
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Country</span>
                <select
                  value={pickedCode}
                  onChange={(e) => setPickedCode(e.target.value)}
                  className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                >
                  {pickerCountries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}{c.setupPending ? " — set-up pending" : ""}
                    </option>
                  ))}
                </select>
                {pickedCountry?.setupPending && (
                  <span className="mt-1.5 block text-[11px] text-warning">
                    Zoiko is still completing {pickedCountry.name}&apos;s statutory set-up. You can add it and its
                    employees now; their payroll uses the default {pickedCountry.name} rates until set-up is complete.
                  </span>
                )}
                {!pickedCountry?.setupPending && pendingCount > 0 && (
                  <span className="mt-1.5 block text-[11px] text-foreground-muted">
                    Countries marked &quot;set-up pending&quot; can be added now; their payroll uses default rates until
                    Zoiko completes their statutory set-up.
                  </span>
                )}
              </label>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setPicker(false)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-foreground-secondary bg-surface-muted hover:bg-border-light"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!pickedCode || busy}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50"
              >
                {busy ? "Working…" : isSingleCountryPlan ? "Continue" : "Add country"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {confirm && (
        <ConfirmDialog
          title={confirmCopy.title}
          message={confirmCopy.message}
          confirmLabel={confirmCopy.label}
          onConfirm={handleConfirm}
          onClose={() => setConfirm(null)}
          busy={busy}
        />
      )}
    </div>
  );
}

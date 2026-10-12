import { useEffect, useState, useCallback } from "react";
import { Copy, GitCompare, Rocket, Archive, ShieldCheck } from "lucide-react";
import Modal from "../../../../components/Modal";
import ConfirmDialog from "../../../../components/ConfirmDialog";
import { useToast } from "../../../../context/ToastContext";
import {
  getCompliancePolicyVersions, upsertCompliancePolicy, setCompliancePolicyStatus,
  approveCompliancePolicy, getPackVersionDiff,
} from "../../../../service/superAdminService";
import { STATUS_PILL_MAP } from "../../../../components/jurisdiction/constants";
import StatusPill from "../../../../components/StatusPill";
import useActivePackForScope from "./useActivePackForScope";
import ScopePicker from "./ScopePicker";

// Versions, promoted to its own top-level nav item — same pack-scoped
// behavior as JurisdictionLayout's own Versions tab (getCompliancePolicyVersions
// by packId), just with its own Federal/state scope picker instead of
// requiring a prior Federal/State-District pack selection.
//
// Real Tax Year/Release Manager actions (gap-closure Plan Phase 4,
// 2026-09-14) — previously this was a pure read view ("editing a version
// still happens in Federal/State-District"). Clone/Compare/Publish/Retire
// are now real actions here, reusing existing endpoints (upsertCompliancePolicy's
// own "new pack_id+version -> creates a new row and auto-clones the prior
// version's rates" behavior IS the clone; set_jurisdiction_pack_status IS
// publish/retire) plus one new endpoint (compare) — nothing about the
// underlying data model changed, only what this page lets you DO with it.
export default function USVersionsSection({ initialScope = "" }) {
  const { addToast } = useToast() || {};
  const [scope, setScope] = useState(initialScope);
  const { pack, loading: packLoading } = useActivePackForScope(scope);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [cloneFrom, setCloneFrom] = useState(null);
  const [compareFrom, setCompareFrom] = useState(null);
  const [retiring, setRetiring] = useState(null);

  const load = useCallback(async () => {
    if (!pack) { setVersions([]); return; }
    setLoading(true);
    try {
      setVersions((await getCompliancePolicyVersions(pack.packId)) || []);
    } finally {
      setLoading(false);
    }
  }, [pack]);

  useEffect(() => { load(); }, [load]);

  async function handleApprove(id) {
    setBusyId(id);
    try {
      await approveCompliancePolicy(id);
      addToast?.("Approved.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to approve.", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function handlePublish(id) {
    setBusyId(id);
    try {
      await setCompliancePolicyStatus(id, "Active");
      addToast?.("Published — now Active.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to publish.", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRetire(id) {
    setBusyId(id);
    try {
      await setCompliancePolicyStatus(id, "Retired");
      addToast?.("Retired.", "success");
      setRetiring(null);
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to retire.", "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <ScopePicker scope={scope} onChange={setScope} />
      {packLoading || loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : !pack ? (
        <p className="rounded-xl border border-dashed border-border bg-surface-muted py-8 text-center text-xs text-foreground-disabled">
          No {scope || "Federal"} tax pack configured yet.
        </p>
      ) : (
        <div className="rounded-xl border border-border bg-surface p-5">
          <p className="mb-3 text-xs text-foreground-muted">
            Pack: <span className="font-semibold text-foreground">{pack.packId}</span>
          </p>
          <div className="space-y-2">
            {versions.map((v) => (
              <div
                key={v.id}
                className={`flex w-full flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs ${
                  v.id === pack.id ? "border-primary bg-primary/5" : "border-border-light"
                }`}
              >
                <span className="font-medium text-foreground">v{v.version}</span>
                <span className="flex items-center gap-2 text-foreground-muted">
                  {v.effectiveFrom} → {v.effectiveTo || "open"}
                  <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setCloneFrom(v)}
                    className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-foreground-secondary hover:bg-surface-muted"
                  >
                    <Copy size={12} /> Clone
                  </button>
                  {versions.length > 1 && (
                    <button
                      onClick={() => setCompareFrom(v)}
                      className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-foreground-secondary hover:bg-surface-muted"
                    >
                      <GitCompare size={12} /> Compare
                    </button>
                  )}
                  {v.status === "Draft" && (
                    <button
                      disabled={busyId === v.id}
                      onClick={() => handleApprove(v.id)}
                      className="flex items-center gap-1 rounded-md bg-warning-light px-2 py-1 font-medium text-warning hover:opacity-80 disabled:opacity-50"
                    >
                      <ShieldCheck size={12} /> Approve
                    </button>
                  )}
                  {(v.status === "Approved" || v.status === "Draft") && (
                    <button
                      disabled={busyId === v.id}
                      onClick={() => handlePublish(v.id)}
                      className="flex items-center gap-1 rounded-md bg-primary px-2 py-1 font-medium text-white hover:bg-primary-hover disabled:opacity-50"
                    >
                      <Rocket size={12} /> Publish
                    </button>
                  )}
                  {v.status === "Active" && (
                    <button
                      disabled={busyId === v.id}
                      onClick={() => setRetiring(v)}
                      className="flex items-center gap-1 rounded-md border border-border px-2 py-1 font-medium text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
                    >
                      <Archive size={12} /> Retire
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {cloneFrom && (
        <CloneVersionModal
          source={cloneFrom}
          onClose={() => setCloneFrom(null)}
          onCloned={() => { setCloneFrom(null); load(); }}
        />
      )}
      {compareFrom && (
        <CompareVersionsModal
          versions={versions}
          initialFrom={compareFrom}
          onClose={() => setCompareFrom(null)}
        />
      )}
      {retiring && (
        <ConfirmDialog
          title="Retire Version"
          message={`Retire v${retiring.version}? It will stop resolving for any new calculation.`}
          onConfirm={() => handleRetire(retiring.id)}
          onClose={() => setRetiring(null)}
        />
      )}
    </div>
  );
}

function CloneVersionModal({ source, onClose, onCloned }) {
  const { addToast } = useToast() || {};
  const [version, setVersion] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!version.trim()) { addToast?.("A new version label is required.", "error"); return; }
    if (version.trim() === source.version) { addToast?.("Enter a version different from the one you're cloning.", "error"); return; }
    setSaving(true);
    try {
      // Deliberately no `id` (creates a NEW row) and a fresh status/dates —
      // upsert_jurisdiction_pack's own "new (packId, version) with a prior
      // version already existing" path auto-clones every canonical
      // ContributionRate/TaxSlab row from the prior version onto this one.
      await upsertCompliancePolicy({
        packId: source.packId, jurisdictionCountry: source.jurisdictionCountry,
        jurisdictionState: source.jurisdictionState, jurisdictionLocality: source.jurisdictionLocality,
        packType: source.packType, version: version.trim(), status: "Draft",
        complianceOwner: source.complianceOwner, engineeringOwner: source.engineeringOwner,
        sourceReferences: source.sourceReferences, regulatoryAuthority: source.regulatoryAuthority,
        complianceCategory: source.complianceCategory,
        changeSummary: `Cloned from v${source.version}`,
        taxYear: source.taxYear, taxRegime: source.taxRegime, defaultTaxRegime: source.defaultTaxRegime,
        currency: source.currency,
      });
      addToast?.(`v${version.trim()} created — every rate/slab from v${source.version} was cloned forward.`, "success");
      onCloned();
    } catch (err) {
      addToast?.(err.message || "Clone failed.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Clone v${source.version} as a New Version`} onClose={onClose} maxWidth="max-w-md">
      <p className="mb-3 text-xs text-foreground-muted">
        Creates a new Draft version with every rate and bracket from v{source.version} already copied over —
        no need to retype anything. Effective dates and approval are NOT carried over; set them fresh.
      </p>
      <label className="mb-1.5 block text-xs font-medium text-foreground-muted">New Version Label</label>
      <input
        className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
        value={version} onChange={(e) => setVersion(e.target.value)} placeholder="e.g. 1.1"
      />
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Cloning…" : "Clone"}</button>
      </div>
    </Modal>
  );
}

function CompareVersionsModal({ versions, initialFrom, onClose }) {
  const [fromId, setFromId] = useState(initialFrom.id);
  const [toId, setToId] = useState((versions.find((v) => v.id !== initialFrom.id) || {}).id || "");
  const [diff, setDiff] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!fromId || !toId || fromId === toId) { setDiff(null); return; }
    setLoading(true);
    setError(null);
    getPackVersionDiff(fromId, toId).then(setDiff).catch((err) => setError(err.message || "Failed to load diff.")).finally(() => setLoading(false));
  }, [fromId, toId]);

  function versionLabel(id) {
    const v = versions.find((x) => x.id === Number(id));
    return v ? `v${v.version} (${v.status})` : "";
  }

  return (
    <Modal title="Compare Versions" onClose={onClose} maxWidth="max-w-2xl">
      <div className="mb-4 grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-foreground-muted">From</label>
          <select className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" value={fromId} onChange={(e) => setFromId(Number(e.target.value))}>
            {versions.map((v) => <option key={v.id} value={v.id}>v{v.version} ({v.status})</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-foreground-muted">To</label>
          <select className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm" value={toId} onChange={(e) => setToId(Number(e.target.value))}>
            {versions.map((v) => <option key={v.id} value={v.id}>v{v.version} ({v.status})</option>)}
          </select>
        </div>
      </div>

      {fromId === toId ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Choose two different versions to compare.</p>
      ) : loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : error ? (
        <p className="text-xs text-error">{error}</p>
      ) : diff ? (
        <div className="max-h-96 space-y-4 overflow-y-auto text-xs">
          <p className="text-foreground-muted">
            Comparing {versionLabel(fromId)} → {versionLabel(toId)}
          </p>
          <DiffTable title="Contribution Rates" data={diff.contributionRates} />
          <DiffTable title="Tax Slabs / Brackets" data={diff.taxSlabs} />
        </div>
      ) : null}
    </Modal>
  );
}

function DiffTable({ title, data }) {
  if (!data) return null;
  const isEmpty = data.added.length === 0 && data.removed.length === 0 && data.changed.length === 0;
  return (
    <div>
      <p className="mb-1.5 font-semibold text-foreground">{title}</p>
      {isEmpty ? (
        <p className="text-foreground-disabled">No differences.</p>
      ) : (
        <div className="space-y-1.5">
          {data.added.map((a, i) => (
            <div key={`added-${i}`} className="rounded-md bg-success/10 p-2 text-success">+ Added: <span className="font-mono">{a.key.join(" / ")}</span></div>
          ))}
          {data.removed.map((r, i) => (
            <div key={`removed-${i}`} className="rounded-md bg-error/10 p-2 text-error">− Removed: <span className="font-mono">{r.key.join(" / ")}</span></div>
          ))}
          {data.changed.map((c, i) => (
            <div key={`changed-${i}`} className="rounded-md bg-surface-muted p-2">
              <p className="font-mono font-medium text-foreground">{c.key.join(" / ")}</p>
              {Object.entries(c.changes).map(([field, v]) => (
                <p key={field} className="text-foreground-muted">
                  {field}: <span className="font-mono">{v.before ?? "—"}</span> → <span className="font-mono">{v.after ?? "—"}</span>
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

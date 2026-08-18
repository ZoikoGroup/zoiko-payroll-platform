import { useState, useEffect, useCallback } from "react";
import { Receipt, FolderTree } from "lucide-react";
import StatusPill from "../StatusPill";
import JurisdictionTreeNav from "./JurisdictionTreeNav";
import { RateConfigurationPanel, ParameterConfigurationPanel } from "./RateConfigPanels";
import * as hs from "../../service/hierarchyService";

// Statutory Rates' view onto the new jurisdiction/tax hierarchy engine.
// Reuses the exact same tree-nav and Rate/Parameter panels as the Super
// Admin Jurisdiction Explorer (components/hierarchy/*) — imported, not
// forked. Unlike the Explorer, this view exposes numeric values only:
// no creating a new Tax, no creating a new TaxVersion, no status
// transitions, no Overview/Applicability/Audit tabs. Selecting an existing
// Tax + Version is just a way to reach the Rates/Parameters editors —
// governance (creating/retiring versions) stays the Explorer's job.

const STATUS_PILL_MAP = {
  Active: "active", Draft: "pending", Scheduled: "pending",
  Expired: "inactive", Retired: "suspended", Deprecated: "inactive",
};

function TaxVersionSelector({ jurisdictionId }) {
  const [taxes, setTaxes] = useState([]);
  const [selectedTaxId, setSelectedTaxId] = useState(null);
  const [versions, setVersions] = useState([]);
  const [selectedVersionId, setSelectedVersionId] = useState(null);
  const [loadingTaxes, setLoadingTaxes] = useState(true);
  const [loadingVersions, setLoadingVersions] = useState(false);

  const loadTaxes = useCallback(() => {
    setLoadingTaxes(true);
    hs.getTaxesForJurisdiction(jurisdictionId)
      .then((rows) => {
        setTaxes(rows);
        setSelectedTaxId(rows[0]?.id ?? null);
      })
      .finally(() => setLoadingTaxes(false));
  }, [jurisdictionId]);

  useEffect(() => { loadTaxes(); }, [loadTaxes]);

  const loadVersions = useCallback(() => {
    if (!selectedTaxId) { setVersions([]); setSelectedVersionId(null); return; }
    setLoadingVersions(true);
    hs.getTaxVersions(selectedTaxId, jurisdictionId)
      .then((rows) => {
        setVersions(rows);
        const active = rows.find((r) => r.status === "Active");
        setSelectedVersionId((active || rows[0])?.id ?? null);
      })
      .finally(() => setLoadingVersions(false));
  }, [selectedTaxId, jurisdictionId]);

  useEffect(() => { loadVersions(); }, [loadVersions]);

  const selectedVersion = versions.find((v) => v.id === selectedVersionId) || null;

  if (loadingTaxes) return <p className="py-6 text-center text-xs text-foreground-disabled">Loading taxes…</p>;
  if (taxes.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border-light px-3 py-6 text-center text-xs text-foreground-disabled">
        No taxes configured for this jurisdiction yet. Taxes and versions are created in the Super Admin
        Jurisdiction Explorer — this page only edits the numeric rates/parameters within them.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[220px]">
          <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Tax</label>
          <select
            value={selectedTaxId ?? ""}
            onChange={(e) => setSelectedTaxId(Number(e.target.value))}
            className="w-full rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
          >
            {taxes.map((t) => (
              <option key={t.id} value={t.id}>{t.name} ({t.tax_code})</option>
            ))}
          </select>
        </div>
        <div className="min-w-[220px]">
          <label className="mb-1.5 block text-xs font-medium text-foreground-muted">Version</label>
          {loadingVersions ? (
            <p className="py-2 text-xs text-foreground-disabled">Loading…</p>
          ) : versions.length > 0 ? (
            <select
              value={selectedVersionId ?? ""}
              onChange={(e) => setSelectedVersionId(Number(e.target.value))}
              className="w-full rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
            >
              {versions.map((v) => (
                <option key={v.id} value={v.id}>v{v.version_label} ({v.status})</option>
              ))}
            </select>
          ) : (
            <p className="py-2 text-xs text-foreground-disabled">No versions yet.</p>
          )}
        </div>
        {selectedVersion && (
          <StatusPill status={STATUS_PILL_MAP[selectedVersion.status] || "pending"} label={selectedVersion.status} />
        )}
      </div>

      {selectedVersion && (
        <div className="rounded-xl border border-border bg-surface p-4 space-y-6">
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground-muted">
              <Receipt size={13} /> Contribution Rates / Slabs
            </p>
            <RateConfigurationPanel taxVersionId={selectedVersion.id} allowRuleDeletion={false} />
          </div>
          <div className="border-t border-border pt-4">
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground-muted">
              <FolderTree size={13} /> Parameters
            </p>
            <ParameterConfigurationPanel taxVersionId={selectedVersion.id} />
          </div>
        </div>
      )}
    </div>
  );
}

export default function StatutoryRatesHierarchyPanel() {
  const [jurisdictionId, setJurisdictionId] = useState(null);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
      <div className="rounded-xl border border-border bg-surface">
        <JurisdictionTreeNav selectedId={jurisdictionId} onSelect={setJurisdictionId} />
      </div>
      <div>
        {!jurisdictionId ? (
          <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-border">
            <p className="text-sm text-foreground-disabled">Select a jurisdiction from the tree to view/edit its rates.</p>
          </div>
        ) : (
          <TaxVersionSelector jurisdictionId={jurisdictionId} />
        )}
      </div>
    </div>
  );
}

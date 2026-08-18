import { useState, useEffect } from "react";
import { ChevronRight, ChevronDown, FolderTree } from "lucide-react";
import * as hs from "../../service/hierarchyService";

// Lazy-loaded jurisdiction tree — shared by the Super Admin Jurisdiction
// Explorer (pages/JurisdictionExplorerPage.jsx) and Statutory Rates
// (pages/StatutoryRatesPage.jsx). Each node loads its own children on first
// expand and keeps them cached in local state (no re-fetch on collapse/
// re-expand); the tree is never fetched in one shot.

function TreeChildren({ parentId, countryId, level, selectedId, onSelect }) {
  const [children, setChildren] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hs.getJurisdictionChildren({ parentId, countryId })
      .then((rows) => { if (!cancelled) setChildren(rows); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [parentId, countryId]);

  if (loading) {
    return <p style={{ paddingLeft: level * 16 + 28 }} className="py-1 text-[11px] text-foreground-disabled">Loading…</p>;
  }
  if (!children || children.length === 0) {
    return <p style={{ paddingLeft: level * 16 + 28 }} className="py-1 text-[11px] text-foreground-disabled">No sub-jurisdictions</p>;
  }
  return children.map((node) => (
    <JurisdictionTreeItem key={node.id} node={node} level={level} selectedId={selectedId} onSelect={onSelect} />
  ));
}

function JurisdictionTreeItem({ node, level, selectedId, onSelect }) {
  const [expanded, setExpanded] = useState(false);
  const isSelected = node.id === selectedId;

  return (
    <div>
      <div
        className={`flex items-center gap-1 rounded-md py-1.5 pr-2 text-sm cursor-pointer ${
          isSelected ? "bg-primary/10 text-primary font-medium" : "text-foreground-secondary hover:bg-surface-muted"
        }`}
        style={{ paddingLeft: level * 16 + 8 }}
      >
        {node.has_children ? (
          <button type="button" onClick={() => setExpanded((e) => !e)} className="shrink-0 text-foreground-disabled">
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : (
          <span className="inline-block w-[13px]" />
        )}
        <span onClick={() => onSelect(node.id)} className="flex-1 truncate">{node.name}</span>
        {node.active_tax_version_count > 0 && (
          <span className="rounded-full bg-success-light px-1.5 text-[10px] font-medium text-success">
            {node.active_tax_version_count}
          </span>
        )}
      </div>
      {expanded && <TreeChildren parentId={node.id} level={level + 1} selectedId={selectedId} onSelect={onSelect} />}
    </div>
  );
}

function CountryGroup({ country, selectedId, onSelect }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mb-1">
      <div
        className="flex items-center gap-1.5 rounded-md py-1.5 px-2 text-xs font-semibold uppercase tracking-wide text-foreground-muted cursor-pointer hover:bg-surface-muted"
        onClick={() => setExpanded((e) => !e)}
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="flex h-4 w-6 items-center justify-center rounded bg-slate-900 dark:bg-black text-[9px] font-bold text-white">
          {country.code}
        </span>
        {country.name}
      </div>
      {expanded && <TreeChildren parentId={null} countryId={country.id} level={1} selectedId={selectedId} onSelect={onSelect} />}
    </div>
  );
}

export default function JurisdictionTreeNav({ selectedId, onSelect }) {
  const [countries, setCountries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    hs.getCountries().then(setCountries).finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="p-4 text-center text-xs text-foreground-disabled">Loading…</p>;
  if (countries.length === 0) {
    return (
      <div className="p-4 text-center">
        <FolderTree size={22} className="mx-auto mb-2 text-border-strong" />
        <p className="text-xs text-foreground-disabled">
          No countries configured yet. Reference data (Country/Jurisdiction Level rows) is seeded by the
          hierarchy migration — nothing to browse here until that runs.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-0.5 p-2">
      {countries.map((c) => (
        <CountryGroup key={c.id} country={c} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

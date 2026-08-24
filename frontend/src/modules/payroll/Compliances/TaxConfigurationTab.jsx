import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { fetchContributionRates, fetchTaxSlabs } from "../../../service/payrollService";
import { SlabsTable, withholdingTerm } from "./TaxSlabTable";
import { RatesTable } from "./ContributionRatesTable";

// Organization Compliance > Tax Configuration — UI/UX ONLY.
// -----------------------------------------------------------------------
// This replaces the old flat, single "Tax Slabs" table with jurisdiction-
// aware navigation (Central/State, Federal/Provincial, National/Regional,
// ...) built entirely on top of the SAME two fetches ContributionRatesTable
// and TaxSlabTable already make (fetchContributionRates/fetchTaxSlabs) —
// no new endpoint, no changed response shape, no calculation logic here.
//
// The underlying API doesn't (and isn't being asked to) expose a row's
// rule_type or jurisdiction_state, so every split below is either:
//   (a) a client-side content filter over rows already being fetched today
//       (e.g. a real income-tax bracket's rate_label always contains "%";
//       a flat/PT-style bracket's does not — visible directly in the
//       existing screenshots), or
//   (b) a label-substring match against the existing display label
//       (e.g. a ContributionRate row literally labeled "Professional Tax"
//       or "Church Tax"), or
//   (c) an honest "not separately broken out" placeholder where the
//       current data model genuinely has no second dataset to show,
//       rather than inventing or duplicating numbers.
// None of this changes what the two source fetches return.

function isPercentageBracket(row) {
  return typeof row.rate === "string" && row.rate.includes("%");
}

function labelIncludes(row, needle) {
  return (row.label || "").toLowerCase().includes(needle);
}

// One config per supported country: level2 groups, each with level3 items.
// `matches(state)` decides whether this leaf reflects the org's OWN
// configured jurisdiction (companyDetails.jurisdictionState) — when it
// doesn't, we say so plainly instead of showing borrowed/invented data.
const COUNTRY_TAX_CONFIG = {
  IN: {
    groups: [
      {
        key: "central", label: "Central Taxes",
        items: [
          {
            key: "income-tax", label: "Income Tax / TDS", source: "slabs",
            matches: () => true,
            filter: (rows) => rows.filter(isPercentageBracket),
          },
        ],
      },
      {
        key: "state", label: "State Taxes", stateAware: true,
        items: [
          {
            key: "pt", label: "Professional Tax", source: "mixed", shareShape: "single",
            matches: (state) => Boolean(state),
            // Professional Tax has no employer share in any Indian state,
            // and once real salary brackets exist for a state (Telangana),
            // the flat ContributionRate row is a less-precise duplicate of
            // the same obligation — show ONLY the brackets in that case
            // rather than stacking a redundant summary row above them.
            filter: (slabs, rates) => {
              const slabRows = slabs.filter((r) => !isPercentageBracket(r));
              const rateRows = slabRows.length > 0 ? [] : rates.filter((r) => labelIncludes(r, "professional tax"));
              return { slabRows, rateRows };
            },
            noStatePlaceholder: "Set an organization state under Company Details to see state-level Professional Tax.",
          },
        ],
      },
    ],
  },
  UK: {
    groups: [
      {
        key: "national", label: "National Income Tax",
        items: [
          {
            // Same isPercentageBracket filter India's Income Tax/TDS item
            // already uses, for the same reason: the API doesn't expose a
            // row's rule_type, but a real PAYE bracket's label always has
            // a "%" ("Basic Rate 20%") while an NI Category band's never
            // does ("NI Category A band 1") — without this, every NI band
            // seeded for this org shows up here as if it were income tax.
            key: "paye", label: "PAYE Income Tax", source: "slabs", matches: () => true,
            filter: (rows) => rows.filter(isPercentageBracket),
          },
        ],
      },
      {
        key: "regional", label: "Regional Income Tax", stateAware: true,
        items: ["England", "Scotland", "Wales", "Northern Ireland"].map((region) => ({
          key: region.toLowerCase().replace(/\s+/g, "-"), label: region, source: "slabs",
          matches: (state) => (state || "").toLowerCase() === region.toLowerCase(),
          filter: (rows) => rows.filter(isPercentageBracket),
        })),
      },
    ],
  },
  US: {
    groups: [
      {
        key: "federal", label: "Federal Taxes",
        items: [
          { key: "federal-income-tax", label: "Federal Income Tax", source: "slabs", matches: () => true, filter: (rows) => rows },
        ],
      },
      {
        key: "state", label: "State Taxes",
        items: [
          {
            key: "state-income-tax", label: "State Income Tax", source: "slabs",
            matches: () => false,
            filter: (rows) => rows,
            noStatePlaceholder: "State income tax isn't broken out separately from Federal Income Tax in the current data — see Federal Taxes.",
          },
        ],
      },
      {
        key: "local", label: "Local Taxes",
        items: [
          { key: "city-tax", label: "City Tax", source: "slabs", matches: () => false, filter: (rows) => rows, noStatePlaceholder: "City tax isn't configured for this organization yet." },
          { key: "county-tax", label: "County Tax", source: "slabs", matches: () => false, filter: (rows) => rows, noStatePlaceholder: "County tax isn't configured for this organization yet." },
          { key: "local-payroll-tax", label: "Local Payroll Tax", source: "slabs", matches: () => false, filter: (rows) => rows, noStatePlaceholder: "Local payroll tax isn't configured for this organization yet." },
        ],
      },
    ],
  },
  CA: {
    groups: [
      {
        key: "federal", label: "Federal Tax",
        items: [
          { key: "federal-income-tax", label: "Federal Income Tax", source: "slabs", matches: () => true, filter: (rows) => rows },
        ],
      },
      {
        key: "provincial", label: "Provincial / Territorial Tax", stateAware: true,
        items: [
          {
            key: "provincial-income-tax", label: "Provincial / Territorial Income Tax", source: "slabs",
            matches: () => false,
            filter: (rows) => rows,
            noStatePlaceholder: "Provincial/territorial tax isn't broken out separately from Federal Income Tax in the current data — see Federal Tax.",
          },
        ],
      },
    ],
  },
  DE: {
    groups: [
      {
        key: "federal-income-tax", label: "Federal Income Tax",
        items: [
          { key: "lohnsteuer", label: "Lohnsteuer", source: "slabs", matches: () => true, filter: (rows) => rows },
        ],
      },
      {
        key: "surcharges", label: "Surcharges",
        items: [
          {
            key: "solidarity-surcharge", label: "Solidarity Surcharge", source: "slabs",
            matches: () => true,
            filter: (rows) => rows.filter((r) => labelIncludes({ label: r.tax }, "surcharge") || labelIncludes({ label: r.tax }, "soli")),
            noStatePlaceholder: "Solidarity Surcharge isn't configured for this organization yet.",
          },
        ],
      },
      {
        key: "special", label: "Special Taxes",
        items: [
          {
            key: "church-tax", label: "Church Tax", source: "rates", shareShape: "single",
            matches: () => true,
            filter: (rates) => rates.filter((r) => labelIncludes(r, "church")),
            noStatePlaceholder: "Church Tax isn't configured for this organization yet.",
          },
        ],
      },
    ],
  },
  AU: {
    groups: [
      {
        key: "federal", label: "Federal Taxes",
        items: [
          { key: "payg", label: "PAYG Withholding", source: "slabs", matches: () => true, filter: (rows) => rows },
          { key: "income-tax", label: "Income Tax", source: "slabs", matches: () => true, filter: (rows) => rows },
          {
            key: "medicare-levy", label: "Medicare Levy", source: "rates", shareShape: "single",
            matches: () => true,
            filter: (rates) => rates.filter((r) => labelIncludes(r, "medicare")),
            noStatePlaceholder: "Medicare Levy isn't configured for this organization yet.",
          },
        ],
      },
      {
        key: "state", label: "State / Territory Taxes", stateAware: true,
        items: [
          {
            key: "payroll-tax", label: "State / Territory Payroll Tax", source: "slabs",
            matches: () => false, filter: (rows) => rows,
            noStatePlaceholder: "State/territory payroll tax isn't configured for this organization yet.",
          },
        ],
      },
    ],
  },
};

function Level2Tabs({ groups, active, onChange }) {
  return (
    <div className="flex gap-1 bg-surface-muted rounded-[14px] p-1 w-fit flex-wrap">
      {groups.map((g) => (
        <button
          key={g.key}
          type="button"
          onClick={() => onChange(g.key)}
          className={`px-4 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
            active === g.key ? "bg-surface text-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-foreground-muted hover:text-foreground"
          }`}
        >
          {g.label}
        </button>
      ))}
    </div>
  );
}

function Level3Tabs({ items, active, onChange }) {
  if (items.length <= 1) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          onClick={() => onChange(it.key)}
          className={`rounded-full px-3.5 py-1.5 text-[12px] font-bold transition-all duration-200 border ${
            active === it.key
              ? "bg-primary text-white border-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
              : "bg-surface text-foreground-muted border-border hover:text-foreground"
          }`}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

// For a stateAware group (e.g. UK's "Regional Income Tax", with a fixed
// England/Scotland/Wales/Northern Ireland item list), an organization is
// only ever actually registered in ONE state — showing all 4 as equal
// tabs implied the other 3 were equally relevant, when clicking any of
// them just produces the "not this organization's jurisdiction"
// placeholder. Narrows to whichever item(s) genuinely match the org's
// own jurisdictionState; falls back to the full list when nothing
// matches (state not set yet, or a state this config doesn't know about)
// so the tab row — and the placeholder telling the org to set a state —
// stays reachable instead of disappearing entirely.
function getVisibleItems(group, jurisdictionState) {
  if (!group.stateAware) return group.items;
  const matching = group.items.filter((it) => it.matches(jurisdictionState));
  return matching.length > 0 ? matching : group.items;
}

export default function TaxConfigurationTab({ documents = [], country, jurisdictionState }) {
  const [slabRows, setSlabRows] = useState([]);
  const [rateRows, setRateRows] = useState([]);
  const [loadState, setLoadState] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    Promise.all([fetchTaxSlabs(country), fetchContributionRates(country)])
      .then(([slabs, rates]) => {
        if (cancelled) return;
        setSlabRows(Array.isArray(slabs) ? slabs : []);
        setRateRows(Array.isArray(rates) ? rates : []);
        setLoadState("ready");
      })
      .catch(() => { if (!cancelled) setLoadState("error"); });
    return () => { cancelled = true; };
  }, [country]);

  const config = COUNTRY_TAX_CONFIG[country] || COUNTRY_TAX_CONFIG.US;
  const [activeGroupKey, setActiveGroupKey] = useState(config.groups[0].key);
  const activeGroup = config.groups.find((g) => g.key === activeGroupKey) || config.groups[0];
  const visibleItems = getVisibleItems(activeGroup, jurisdictionState);
  const [activeItemKey, setActiveItemKey] = useState(visibleItems[0].key);
  const activeItem = visibleItems.find((it) => it.key === activeItemKey) || visibleItems[0];

  function changeGroup(key) {
    setActiveGroupKey(key);
    const group = config.groups.find((g) => g.key === key);
    setActiveItemKey(getVisibleItems(group, jurisdictionState)[0].key);
  }

  const extractedRows = [];
  documents.forEach((doc) => {
    if (doc.extracted?.taxSlabs?.length > 0) extractedRows.push(...doc.extracted.taxSlabs);
  });

  const itemMatches = activeItem.matches(jurisdictionState);
  const term = withholdingTerm(country);

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-[15px] font-bold text-foreground mb-1">Tax Configuration</h3>
        <p className="text-[13px] text-foreground-muted mb-3">Configure organization statutory tax settings.</p>
        <Level2Tabs groups={config.groups} active={activeGroupKey} onChange={changeGroup} />
      </div>

      {activeGroup.stateAware && (
        <p className="text-[12px] text-foreground-muted">
          State: <span className="font-bold text-foreground">{jurisdictionState || "Not set — see Company Details"}</span>
        </p>
      )}

      <Level3Tabs items={visibleItems} active={activeItemKey} onChange={setActiveItemKey} />

      <div>
        <div className="flex items-center gap-2 mb-2">
          <h4 className="text-[14px] font-bold text-foreground">Active {activeItem.label} Slabs</h4>
          {loadState === "ready" && (
            <span className="flex items-center gap-1 text-[11px] font-bold text-primary">
              <CheckCircle2 size={12} /> Live from payroll engine
            </span>
          )}
        </div>

        {loadState === "loading" && (
          <div className="bg-surface border border-border rounded-[18px] p-6 flex items-center gap-2 text-[13px] text-foreground-muted shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Loader2 size={14} className="animate-spin" /> Loading active tax configuration...
          </div>
        )}

        {loadState === "error" && (
          <div className="bg-error/5 border border-error/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-error shrink-0 mt-0.5" />
            <p className="text-[13px] text-error">
              Couldn't load the org's active tax configuration. This is the table {term} is actually calculated
              against — try refreshing before relying on the extracted-document values below.
            </p>
          </div>
        )}

        {loadState === "ready" && !itemMatches && (
          <div className="bg-info/5 border border-info/20 rounded-[18px] p-4 flex items-start gap-3">
            <AlertCircle size={16} className="text-info shrink-0 mt-0.5" />
            <p className="text-[13px] text-info">
              {activeItem.noStatePlaceholder || "This isn't the organization's configured jurisdiction — no data applies here."}
            </p>
          </div>
        )}

        {loadState === "ready" && itemMatches && activeItem.source === "slabs" && (() => {
          const rows = activeItem.filter(slabRows);
          return rows.length === 0 ? (
            <p className="rounded-[18px] border border-dashed border-border-light bg-surface px-4 py-8 text-center text-[13px] text-foreground-disabled">
              No {activeItem.label.toLowerCase()} slabs configured for this jurisdiction yet.
            </p>
          ) : (
            <SlabsTable rows={rows} caption={`Currently applied when calculating ${activeItem.label} in this jurisdiction.`} />
          );
        })()}

        {loadState === "ready" && itemMatches && activeItem.source === "rates" && (() => {
          const rows = activeItem.filter(rateRows);
          return rows.length === 0 ? (
            <p className="rounded-[18px] border border-dashed border-border-light bg-surface px-4 py-8 text-center text-[13px] text-foreground-disabled">
              No {activeItem.label.toLowerCase()} rate configured for this jurisdiction yet.
            </p>
          ) : (
            <RatesTable rows={rows} caption={`Currently applied to every payslip in this jurisdiction.`} singleColumn={activeItem.shareShape === "single"} />
          );
        })()}

        {loadState === "ready" && itemMatches && activeItem.source === "mixed" && (() => {
          const { slabRows: filteredSlabs, rateRows: filteredRates } = activeItem.filter(slabRows, rateRows);
          if (filteredSlabs.length === 0 && filteredRates.length === 0) {
            return (
              <p className="rounded-[18px] border border-dashed border-border-light bg-surface px-4 py-8 text-center text-[13px] text-foreground-disabled">
                No {activeItem.label.toLowerCase()} configured for this jurisdiction yet.
              </p>
            );
          }
          return (
            <div className="space-y-4">
              {filteredRates.length > 0 && <RatesTable rows={filteredRates} caption={`Currently applied to every payslip in this jurisdiction.`} singleColumn={activeItem.shareShape === "single"} />}
              {filteredSlabs.length > 0 && <SlabsTable rows={filteredSlabs} caption={`Currently applied when calculating ${activeItem.label} in this jurisdiction.`} />}
            </div>
          );
        })()}
      </div>

      <div>
        <h3 className="text-[15px] font-bold text-foreground mb-2">Extracted From Documents</h3>
        {extractedRows.length === 0 ? (
          <div className="bg-surface border border-border rounded-[18px] p-4 flex items-start gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <AlertCircle size={16} className="text-foreground-muted shrink-0 mt-0.5" />
            <p className="text-[13px] text-foreground-muted">
              No tax slabs extracted yet. Upload a compliance document to see slabs here.
            </p>
          </div>
        ) : (
          <SlabsTable
            rows={extractedRows}
            caption="Reference only — nothing here is applied to payroll until you promote a row on the Documents tab."
          />
        )}
      </div>
    </div>
  );
}

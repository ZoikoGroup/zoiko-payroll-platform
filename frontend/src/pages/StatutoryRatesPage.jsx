import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Globe2, ChevronRight } from "lucide-react";
import { getComplianceJurisdictions } from "../service/superAdminService";
import { COUNTRY_CODE_TO_ROUTE } from "./JurisdictionStatutory";
import CountryFlag from "../components/jurisdiction/CountryFlag";

// Super Admin > Statutory Rates — Jurisdiction Statutory Rates entry point
// -----------------------------------------------------------------------
// Same split as Compliance's own CompliancePage.jsx (see that file's
// history): the actual rate-viewing/quick-edit UI now lives in
// components/jurisdiction/StatutoryRatesLayout.jsx, reused by six
// per-country pages under pages/JurisdictionStatutory/. This file is just
// the landing/router layer — pick a country, go to its dedicated page.
// The country list stays real and backend-driven (getComplianceJurisdictions,
// the same call every one of those pages already makes for its own state
// picker) — nothing here is a hardcoded jurisdiction list.
export default function StatutoryRatesPage() {
  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getComplianceJurisdictions()
      .then(setJurisdictions)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Statutory Rates</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Select a jurisdiction to view and quick-edit its statutory contribution rates. Creating tax packs or changing their status happens in Compliance.
        </p>
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {jurisdictions.map((j) => {
            const slug = COUNTRY_CODE_TO_ROUTE[j.code];
            if (!slug) return null; // a jurisdiction with no dedicated page yet — shouldn't happen for the six supported countries, but fails safe rather than a broken link
            return (
              <Link
                key={j.code}
                to={`/super-admin/statutory-rates/${slug}`}
                className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface p-5 hover:border-primary/40 hover:bg-primary/5 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <CountryFlag code={j.code} className="h-full w-full" fallback={<Globe2 size={18} className="text-primary" />} />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-foreground">{j.name}</p>
                    <p className="text-xs text-foreground-muted">
                      {j.states?.length ? `${j.states.length} jurisdiction${j.states.length === 1 ? "" : "s"} configured` : "Country-level only"}
                    </p>
                  </div>
                </div>
                <ChevronRight size={16} className="text-foreground-disabled" />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Globe2, ChevronRight, Eye } from "lucide-react";
import { getComplianceJurisdictions } from "../service/superAdminService";
import { COUNTRY_CODE_TO_ROUTE } from "./JurisdictionCompliance";
import CountryFlag from "../components/jurisdiction/CountryFlag";

// Super Admin > Compliance — Jurisdiction Compliance entry point
// -----------------------------------------------------------------
// This used to be a single ~1300-line file managing every country's tax/
// policy packs directly. That pack-management UI now lives in
// components/jurisdiction/JurisdictionLayout.jsx, reused by six per-country
// pages under pages/JurisdictionCompliance/ (INCompliancePage.jsx, etc.).
// This file is now just the landing/router layer: pick a country, go to
// its dedicated page. The country list itself stays real and
// backend-driven (getComplianceJurisdictions — same call every one of
// those pages already makes for its own state picker) — nothing here is a
// hardcoded jurisdiction list.
export default function CompliancePage() {
  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getComplianceJurisdictions()
      .then(setJurisdictions)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Compliance</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Select a jurisdiction to manage its tax and policy packs — versions, canonical rates/slabs, organization assignment, and audit history.
          </p>
        </div>
        <Link
          to="/super-admin/compliance/engine-defaults"
          className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:border-primary/40 hover:text-primary transition-colors"
        >
          <Eye size={14} /> View Engine Fallback Defaults
        </Link>
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
                to={`/super-admin/compliance/${slug}`}
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

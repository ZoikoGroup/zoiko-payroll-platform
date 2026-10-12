import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Globe2, ChevronRight, Clock } from "lucide-react";
import { getCaribbeanJurisdictions } from "../service/superAdminService";
import { COUNTRY_CODE_TO_ROUTE } from "./JurisdictionCompliance";
import CountryFlag from "../components/jurisdiction/CountryFlag";

// Super Admin > Compliance > Caribbean — the full region master
// (Independent Countries / British Overseas Territories / Dutch
// Caribbean / French Caribbean / United States Territories), including
// every "Coming Soon" jurisdiction. This is a DISPLAY-ONLY grouping on
// top of the same backend-driven list app.core.caribbean_regions
// maintains — it never gates anything itself; the 7 ACTIVE cards route
// through the exact same COUNTRY_CODE_TO_ROUTE mechanism the ordinary
// Compliance landing page (CompliancePage.jsx) already uses. Coming Soon
// entries render a disabled card with no link — there is no page for
// them to link to.
const CLASSIFICATION_ORDER = [
  "INDEPENDENT_COUNTRY",
  "BRITISH_OVERSEAS_TERRITORY",
  "DUTCH_CARIBBEAN",
  "FRENCH_CARIBBEAN",
  "UNITED_STATES_TERRITORY",
];

const CLASSIFICATION_LABELS = {
  INDEPENDENT_COUNTRY: "Independent Countries",
  BRITISH_OVERSEAS_TERRITORY: "British Overseas Territories",
  DUTCH_CARIBBEAN: "Dutch Caribbean",
  FRENCH_CARIBBEAN: "French Caribbean",
  UNITED_STATES_TERRITORY: "United States Territories",
};

export default function CaribbeanCompliancePage() {
  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCaribbeanJurisdictions()
      .then(setJurisdictions)
      .finally(() => setLoading(false));
  }, []);

  const byClassification = CLASSIFICATION_ORDER.map((classification) => ({
    classification,
    label: CLASSIFICATION_LABELS[classification],
    rows: jurisdictions.filter((j) => j.classification === classification),
  })).filter((group) => group.rows.length > 0);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Caribbean</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Every Caribbean jurisdiction, grouped by classification. Active jurisdictions link to their full tax/policy
          pack configuration; the rest are shown as Coming Soon and cannot be selected for payroll.
        </p>
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : (
        byClassification.map((group) => (
          <div key={group.classification} className="mb-8">
            <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-foreground-muted">{group.label}</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {group.rows.map((j) => {
                const slug = COUNTRY_CODE_TO_ROUTE[j.code];
                const isActive = j.status === "ACTIVE" && !!slug;

                const card = (
                  <div
                    className={`flex items-center justify-between gap-3 rounded-xl border p-5 transition-colors ${
                      isActive
                        ? "border-border bg-surface hover:border-primary/40 hover:bg-primary/5"
                        : "border-border/50 bg-surface-muted opacity-70"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                        <CountryFlag code={j.code} className="h-full w-full" fallback={<Globe2 size={18} className="text-primary" />} />
                      </div>
                      <div>
                        <p className="text-sm font-bold text-foreground">{j.name}</p>
                        {isActive ? (
                          <p className="text-xs text-foreground-muted">Active</p>
                        ) : (
                          <p className="flex items-center gap-1 text-xs font-semibold text-amber-600">
                            <Clock size={12} /> Coming Soon
                          </p>
                        )}
                      </div>
                    </div>
                    {isActive && <ChevronRight size={16} className="text-foreground-disabled" />}
                  </div>
                );

                return isActive ? (
                  <Link key={j.code} to={`/super-admin/compliance/${slug}`}>
                    {card}
                  </Link>
                ) : (
                  <div key={j.code} aria-disabled="true">
                    {card}
                  </div>
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

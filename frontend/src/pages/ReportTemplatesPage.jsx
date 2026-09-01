import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Globe2, ChevronRight } from "lucide-react";
import { getComplianceJurisdictions } from "../service/superAdminService";
import { COUNTRY_CODE_TO_ROUTE } from "./ReportTemplates";
import CountryFlag from "../components/jurisdiction/CountryFlag";

// Super Admin > Report Templates — entry point.
// Same split as Compliance/Statutory Rates' own landing pages: pick a
// jurisdiction, go to its dedicated authoring page. Country list stays
// real and backend-driven; a jurisdiction with no dedicated page yet
// (everything but India in Phase 1) is shown but not clickable, rather
// than silently omitted or linking to a broken route.
export default function ReportTemplatesPage() {
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
        <h1 className="text-2xl font-bold text-foreground">Report Templates</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Select a jurisdiction to author and publish its statutory report templates. Organizations generate actual reports from whichever version is Active.
        </p>
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {jurisdictions.map((j) => {
            const slug = COUNTRY_CODE_TO_ROUTE[j.code];
            return (
              <Link
                key={j.code}
                to={slug ? `/super-admin/report-templates/${slug}` : "#"}
                onClick={(e) => { if (!slug) e.preventDefault(); }}
                className={`flex items-center justify-between gap-3 rounded-xl border border-border bg-surface p-5 transition-colors ${
                  slug ? "hover:border-primary/40 hover:bg-primary/5" : "opacity-50 cursor-not-allowed"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <CountryFlag code={j.code} className="h-full w-full" fallback={<Globe2 size={18} className="text-primary" />} />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-foreground">{j.name}</p>
                    <p className="text-xs text-foreground-muted">{slug ? "Manage report templates" : "Coming soon"}</p>
                  </div>
                </div>
                {slug && <ChevronRight size={16} className="text-foreground-disabled" />}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

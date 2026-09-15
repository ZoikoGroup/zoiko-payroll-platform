import { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import {
  listAllOrganizationsBrief,
  getIndiaSalaryTdsDeclarationsForOrg, getIndiaSalaryTdsClaimsForOrg, getIndiaFormsForOrg,
} from "../../../service/superAdminService";

// India Salary TDS / Forms (ZP-TAX-IN-2026-27-001 §6.1-§6.3, gap-closure
// Phase F, 2026-09-11) — an org-wide status view over Forms 122
// (declarations), 124 (claims), and 123/130/138 (generated reports).
// Reuses the EXISTING per-org list logic (list_salary_tds_declarations/
// list_salary_tds_claims/get_generated_reports, all built in an earlier
// phase) via three thin Super-Admin cross-org wrapper endpoints added
// alongside this tab (a Super Admin token has no organization_id of its
// own, unlike the org-facing versions of these same endpoints) — no new
// service-layer business logic.
const FORM_LABELS = { FORM_123: "Form 123 (Perquisite Statement)", FORM_130: "Form 130 (TDS Certificate)", FORM_138: "Form 138 (Quarterly TDS Statement)" };

export default function INSalaryTdsFormsTab() {
  const [orgs, setOrgs] = useState([]);
  const [organizationId, setOrganizationId] = useState("");
  const [declarations, setDeclarations] = useState([]);
  const [claims, setClaims] = useState([]);
  const [forms, setForms] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listAllOrganizationsBrief().then((data) => {
      const list = Array.isArray(data) ? data : data?.items || [];
      setOrgs(list);
      if (list.length > 0) setOrganizationId(String(list[0].id));
    });
  }, []);

  useEffect(() => {
    if (!organizationId) return;
    setLoading(true);
    Promise.all([
      getIndiaSalaryTdsDeclarationsForOrg(organizationId),
      getIndiaSalaryTdsClaimsForOrg(organizationId),
      getIndiaFormsForOrg(organizationId),
    ])
      .then(([d, c, f]) => {
        setDeclarations(Array.isArray(d) ? d : []);
        setClaims(Array.isArray(c) ? c : []);
        setForms((Array.isArray(f) ? f : []).filter((r) => FORM_LABELS[r.reportType]));
      })
      .finally(() => setLoading(false));
  }, [organizationId]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-xs text-foreground-muted">Form 122/124 declarations &amp; claims, and generated Form 123/130/138 reports, for one organization at a time.</p>
        <select
          value={organizationId} onChange={(e) => setOrganizationId(e.target.value)}
          className="rounded-lg border border-border bg-surface px-3 py-2 text-xs font-semibold text-foreground"
        >
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.organizationName || o.name || `Org #${o.id}`}</option>)}
        </select>
      </div>

      {loading ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : (
        <>
          <Section title="Form 122 — Salary TDS Declarations" empty="No declarations for this organization yet.">
            {declarations.map((d) => (
              <Row key={d.id} left={`Employee #${d.employeeId} · ${d.taxYear}`} right={d.status} />
            ))}
          </Section>

          <Section title="Form 124 — Chapter VIII Claims" empty="No claims for this organization yet.">
            {claims.map((c) => (
              <Row key={c.id} left={`Employee #${c.employeeId} · ${c.taxYear} · ${c.claimType}`} right={c.status} />
            ))}
          </Section>

          <Section title="Form 123 / 130 / 138 — Generated Reports" empty="No generated reports for this organization yet.">
            {forms.map((f) => (
              <Row key={f.id} left={`${FORM_LABELS[f.reportType] || f.reportType} · ${f.generatedAt ? new Date(f.generatedAt).toLocaleDateString() : "—"}`} right={f.status} />
            ))}
          </Section>
        </>
      )}
    </div>
  );
}

function Section({ title, empty, children }) {
  const hasRows = Array.isArray(children) ? children.some(Boolean) && children.length > 0 : Boolean(children);
  return (
    <div className="rounded-xl border border-border">
      <div className="border-b border-border-light px-4 py-3 flex items-center gap-1.5">
        <FileText size={14} className="text-foreground-disabled" />
        <p className="text-sm font-bold text-foreground">{title}</p>
      </div>
      <div className="divide-y divide-border-light">
        {hasRows ? children : <p className="px-4 py-6 text-center text-xs text-foreground-disabled">{empty}</p>}
      </div>
    </div>
  );
}

function Row({ left, right }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 text-xs">
      <span className="text-foreground-secondary">{left}</span>
      <span className="rounded-full bg-surface-muted px-2 py-0.5 font-semibold text-foreground-muted">{right}</span>
    </div>
  );
}

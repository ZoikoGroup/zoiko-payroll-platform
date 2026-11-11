import { useEffect, useState } from "react";
import { Building2, Loader2, UserRound } from "lucide-react";

import { apiFetch } from "../../api/client";
import Drawer from "../Drawer";
import StatusPill from "../StatusPill";

// Organization details drawer — read-only account, registration, and security
// detail for one organization (GET /api/organizations/{id}).

export function formatDateTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

function utcText(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : `${date.toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

function Row({ label, value, time }) {
  const shown = time ? formatDateTime(value) : value;
  return (
    <div className="grid grid-cols-[150px_1fr] gap-3 py-1.5 text-sm">
      <dt className="text-foreground-muted">{label}</dt>
      <dd className="break-words text-foreground-secondary">
        {shown === null || shown === undefined || shown === "" ? (
          <span className="text-foreground-disabled">—</span>
        ) : (
          <>
            {String(shown)}
            {time && <span className="block text-xs text-foreground-muted">{utcText(value)}</span>}
          </>
        )}
      </dd>
    </div>
  );
}

function Section({ icon: Icon, title, children }) {
  return (
    <section className="mb-5">
      <h4 className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-foreground-muted">
        <Icon size={14} /> {title}
      </h4>
      <dl className="divide-y divide-border-light">{children}</dl>
    </section>
  );
}

const yesNo = (v) => (v ? "Yes" : "No");

const WORKSPACE_BADGE = {
  PRODUCTION: "active",
  EVALUATION: "pending",
};

export default function OrganizationDetailDrawer({ organizationId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setData(null);
    setError("");
    apiFetch(`/api/organizations/${organizationId}`)
      .then((d) => alive && setData(d))
      .catch((err) => alive && setError(err.message));
    return () => { alive = false; };
  }, [organizationId]);

  const org = data;

  return (
    <Drawer
      title={org ? org.organization_name : "Organization details"}
      subtitle={org ? `${org.organization_code} · ${org.workspace_type || "PRODUCTION"}` : undefined}
      badge={org ? <StatusPill status={org.is_active ? "active" : "inactive"} /> : null}
      onClose={onClose}
      width="max-w-2xl"
    >
      {error && <p className="rounded-lg bg-error-light px-3 py-2 text-sm text-error">{error}</p>}
      {!error && !data && (
        <div className="flex items-center gap-2 py-10 text-sm text-foreground-muted">
          <Loader2 size={16} className="animate-spin" /> Loading organization details…
        </div>
      )}

      {org && (
        <>
          <Section icon={UserRound} title="Account">
            <Row label="Name" value={org.organization_name} />
            <Row label="Code" value={org.organization_code} />
            <Row label="Company type" value={org.company_type || "—"} />
            <Row label="Industry" value={org.industry || "—"} />
            <Row label="Workspace type" value={org.workspace_type || "PRODUCTION"} />
            <Row label="Organization active" value={yesNo(org.is_active)} />
            <Row label="Charge enabled" value={yesNo(org.charge_enabled)} />
            <Row label="Billing classification" value={org.billing_classification || "NON_CHARGEABLE"} />
            <Row label="Commercial route" value={org.commercial_route || "—"} />
            <Row label="Terms accepted" value={org.terms_accepted_at ? formatDateTime(org.terms_accepted_at) : "—"} time />
            <Row label="Created" value={org.created_at} time />
            <Row label="Last updated" value={org.updated_at} time />
          </Section>

          <Section icon={Building2} title="Organization">
            <Row label="Address" value={org.address || "—"} />
            <Row label="City" value={org.city || "—"} />
            <Row label="State" value={org.state || "—"} />
            <Row label="Country" value={org.country || "—"} />
            <Row label="Email" value={org.email || "—"} />
            <Row label="Phone" value={org.phone || "—"} />
            <Row label="Tax number" value={org.tax_no || "—"} />
            <Row label="Registration number" value={org.registration_number || "—"} />
            {org.tax_identifiers && Object.entries(org.tax_identifiers).length > 0 && (
              <>
                <dt className="text-foreground-muted">Tax identifiers</dt>
                <dd className="break-words text-foreground-secondary">
                  {Object.entries(org.tax_identifiers)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(", ")}
                </dd>
              </>
            )}
            <Row label="Currency" value={org.currency || "USD"} />
          </Section>
        </>
      )}
    </Drawer>
  );
}

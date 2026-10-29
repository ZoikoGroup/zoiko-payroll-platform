import { useEffect, useState } from "react";
import { Building2, Loader2, ShieldCheck, UserRound } from "lucide-react";

import { apiFetch } from "../../api/client";
import Drawer from "../Drawer";
import StatusPill from "../StatusPill";

// Platform Users — read-only account, registration and security detail for
// one user (GET /api/super-admin/users/{id}). Every view is recorded as a
// PRIVILEGED_READ security event server-side.

const CREATED_VIA = {
  REGISTRATION: "Self-registration (Production)",
  TRIAL_SIGNUP: "Trial sign-up (Evaluation)",
  INVITED: "Invited by an organization admin",
  ADDED_BY_ADMIN: "Added by an administrator",
  SUPPORT_ACCESS: "Temporary support access",
  PLATFORM_ACCOUNT: "Platform account",
};

// API datetimes are UTC with "Z": show the viewer's local time with its zone
// and the exact UTC time underneath.
export function formatDateTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
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
        {shown === null || shown === undefined || shown === "" ? <span className="text-foreground-disabled">—</span> : (
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

export default function UserDetailDrawer({ userId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setData(null);
    setError("");
    apiFetch(`/api/super-admin/users/${userId}`)
      .then((d) => alive && setData(d))
      .catch((err) => alive && setError(err.message));
    return () => { alive = false; };
  }, [userId]);

  const account = data?.account;
  const org = data?.organization;
  const security = data?.security;

  return (
    <Drawer
      title={account ? `${account.first_name} ${account.last_name}` : "User details"}
      subtitle={account ? `${account.email} · ${account.role}` : undefined}
      badge={account ? <StatusPill status={account.is_active ? "active" : "inactive"} /> : null}
      onClose={onClose}
      width="max-w-xl"
    >
      {error && <p className="rounded-lg bg-error-light px-3 py-2 text-sm text-error">{error}</p>}
      {!error && !data && (
        <div className="flex items-center gap-2 py-10 text-sm text-foreground-muted">
          <Loader2 size={16} className="animate-spin" /> Loading user details…
        </div>
      )}

      {account && (
        <Section icon={UserRound} title="Account">
          <Row label="Full name" value={`${account.first_name} ${account.last_name}`} />
          <Row label="Email" value={account.email} />
          <Row label="Phone" value={account.phone} />
          <Row label="Role" value={account.role} />
          <Row label="Email verified" value={yesNo(account.is_verified)} />
          <Row label="Created via" value={`${CREATED_VIA[account.created_via] || account.created_via} (inferred)`} />
          <Row label="Created" value={account.created_at} time />
          <Row label="Last updated" value={account.updated_at} time />
          {account.invitation_sent_at && <Row label="Invitation sent" value={account.invitation_sent_at} time />}
          {account.invitation_sent_at && (
            <Row label="Invitation accepted" value={account.invitation_accepted_at} time />
          )}
          {account.is_temporary && <Row label="Access expires" value={account.access_expires_at} time />}
        </Section>
      )}

      {data && (
        <Section icon={Building2} title="Organization (as registered)">
          {!org ? (
            <Row label="Organization" value="Not linked to an organization (platform account)" />
          ) : (
            <>
              <Row label="Name" value={org.name} />
              <Row label="Code" value={org.code} />
              <Row label="Industry" value={org.industry} />
              <Row label="Company type" value={org.company_type} />
              <Row label="Address" value={org.address} />
              <Row label="City" value={org.city} />
              <Row label="State" value={org.state} />
              <Row label="Country" value={org.country} />
              <Row label="Email" value={org.email} />
              <Row label="Phone" value={org.phone} />
              <Row label="Tax number" value={org.tax_no} />
              <Row label="Registration number" value={org.registration_number} />
              {org.tax_identifiers.map((t) => <Row key={t.key} label={t.label} value={t.value} />)}
              <Row label="Workspace" value={org.workspace_type === "EVALUATION" ? "Trial (Evaluation)" : org.workspace_type} />
              <Row label="Plan" value={org.plan ? [org.plan.name || org.plan.code, org.plan.status].filter(Boolean).join(" · ") : null} />
              <Row label="Billing status" value={org.billing_onboarding_status} />
              <Row label="Currency" value={org.currency} />
              <Row label="Data region" value={org.data_region} />
              <Row label="Organization active" value={yesNo(org.is_active)} />
              <Row label="Terms accepted" value={org.terms_accepted_at} time />
              <Row label="Organization created" value={org.created_at} time />
              {org.created_by_email && <Row label="Created by" value={org.created_by_email} />}
            </>
          )}
        </Section>
      )}

      {security && (
        <Section icon={ShieldCheck} title="Security activity">
          <Row label="MFA" value={security.mfa_confirmed_at ? "Enrolled" : security.mfa_required ? "Required — not enrolled" : "Not enrolled"} />
          {security.mfa_confirmed_at && <Row label="MFA enrolled" value={security.mfa_confirmed_at} time />}
          <Row label="Last login" value={security.last_login_at} time />
          <Row label="Last login IP" value={security.last_login_ip} />
          <Row label="Last login device" value={security.last_login_user_agent} />
          <Row label="Failed logins (30 days)" value={String(security.failed_logins_30d)} />
          <Row label="Last failed login" value={security.last_failed_login_at} time />
          <Row label="Last password reset" value={security.last_password_reset_at} time />
        </Section>
      )}
    </Drawer>
  );
}

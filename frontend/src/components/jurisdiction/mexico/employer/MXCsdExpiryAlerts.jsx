import { getMxCsdExpiryAlerts } from "../../../../service/superAdminService";
import { card, Messages, Table, useLoad } from "../mxShared";

// CSD expiry alerts (final mile X5, gap C3): every ACTIVE CSD reference, in any
// organisation, that is expired, has no certificate, or expires within the
// warning window on `on`. Public certificate metadata only — never the secret
// reference or the employer's RFC. Read-only: the organisation rotates its own CSD.
const TONE = { EXPIRED: "text-error", MISSING: "text-error", EXPIRING: "text-warning" };

export default function MXCsdExpiryAlerts({ on }) {
  const [data, error] = useLoad(() => getMxCsdExpiryAlerts(on), [on]);
  return (
    <div className={card} data-testid="mx-csd-expiry">
      <h3 className="text-[14px] font-semibold text-foreground">CSD expiry alerts — all organisations</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        On {data?.on || on}: expired, missing, or expiring within {data?.warningDays ?? "—"} days. A CSD that is not in
        force blocks CFDI signing for its employer.
      </p>
      <Messages error={error} />
      <Table rows={data?.alerts || []} rowKey={(a) => a.credentialId} empty="No CSD is expired or expiring." columns={[
        { key: "level", label: "Alert", render: (a) => <span className={`font-semibold ${TONE[a.level] || ""}`}>{a.level}</span> },
        { key: "organization", label: "Organisation", render: (a) => a.organization || `#${a.organizationId}` },
        { key: "employerProfileId", label: "Employer", render: (a) => `#${a.employerProfileId}` },
        { key: "certificateSerial", label: "Certificate", render: (a) => a.certificateSerial || "—" },
        { key: "fingerprint", label: "Fingerprint", render: (a) => a.fingerprint || "—" },
        { key: "note", label: "Detail" },
      ]} />
    </div>
  );
}

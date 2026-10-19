import { Link } from "react-router-dom";

// Shown wherever the Super Admin plane used to display worker-level data or a
// tenant's own payroll workflow (ZP-PRIV B.3). The server is the control —
// these screens no longer call the retired endpoints at all; this panel only
// explains why and where to go instead.
//
//   variant="support"  worker-level data: needs a JIT Support Access grant
//   variant="tenant"   a tenant-run setting / statutory action (decision 3)
export default function WorkerDataLocked({
  variant = "support",
  title,
  organizationCode,
  children,
}) {
  const isTenant = variant === "tenant";
  const heading =
    title ||
    (isTenant
      ? "Managed by the organization"
      : "Worker-level data requires Support Access");
  const body = isTenant
    ? "This setting or statutory action belongs to the organization and is now run from its own workspace. Zoiko staff see its status only."
    : "Zoiko staff have no standing access to employees, salaries, bank details, tax IDs or payslips. Request time-limited, read-only access that the organization approves.";
  const link = organizationCode
    ? `/super-admin/support-access?organization=${encodeURIComponent(organizationCode)}`
    : "/super-admin/support-access";

  return (
    <div
      role="status"
      className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200"
    >
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="mt-0.5 text-lg">
          {isTenant ? "🏢" : "🔒"}
        </span>
        <div className="space-y-2">
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">{heading}</h3>
          <p className="leading-relaxed">{body}</p>
          {children}
          {!isTenant && (
            <Link
              to={link}
              className="inline-flex items-center rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              Go to Support Access
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

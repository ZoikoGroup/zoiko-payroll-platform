// Generalized from the STATUS_STYLES map in modules/organization-admin/OrganizationPage.jsx
// so every Super Admin table/page shares one status-pill implementation instead of
// hand-rolling green/red spans per page.
const STATUS_STYLES = {
  active: { bg: "rgba(23,138,80,0.11)", color: "#178A50", border: "rgba(23,138,80,0.22)" },
  approved: { bg: "rgba(110,90,230,0.10)", color: "#4B3BB0", border: "rgba(110,90,230,0.22)" },
  pending: { bg: "rgba(217,121,30,0.12)", color: "#B8600F", border: "rgba(217,121,30,0.25)" },
  on_hold: { bg: "rgba(217,121,30,0.12)", color: "#B8600F", border: "rgba(217,121,30,0.25)" },
  suspended: { bg: "rgba(214,48,76,0.10)", color: "#D6304C", border: "rgba(214,48,76,0.25)" },
  rejected: { bg: "rgba(214,48,76,0.10)", color: "#D6304C", border: "rgba(214,48,76,0.25)" },
  deactivated: { bg: "rgba(28,24,40,0.07)", color: "#635C72", border: "rgba(28,24,40,0.16)" },
  inactive: { bg: "rgba(28,24,40,0.07)", color: "#635C72", border: "rgba(28,24,40,0.16)" },
};

export default function StatusPill({ status, label }) {
  if (!status) return <span className="text-slate-400">—</span>;
  const s = STATUS_STYLES[status] || STATUS_STYLES.deactivated;
  const text = label || status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium"
      style={{ background: s.bg, color: s.color, borderColor: s.border }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
      {text}
    </span>
  );
}

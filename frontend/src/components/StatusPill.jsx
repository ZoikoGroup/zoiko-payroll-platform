// Generalized from the STATUS_STYLES map in modules/organization-admin/OrganizationPage.jsx
// so every Super Admin table/page shares one status-pill implementation instead of
// hand-rolling green/red spans per page. Colors reference the centralized design
// tokens (frontend/src/index.css) via CSS custom properties so pills stay correct
// in both light and dark theme automatically.
const STATUS_STYLES = {
  active: { bg: "var(--color-success-light)", color: "var(--color-success)", border: "color-mix(in srgb, var(--color-success) 35%, transparent)" },
  approved: { bg: "var(--color-category-teal-light)", color: "var(--color-category-teal)", border: "color-mix(in srgb, var(--color-category-teal) 35%, transparent)" },
  pending: { bg: "var(--color-warning-light)", color: "var(--color-warning)", border: "color-mix(in srgb, var(--color-warning) 35%, transparent)" },
  on_hold: { bg: "var(--color-warning-light)", color: "var(--color-warning)", border: "color-mix(in srgb, var(--color-warning) 35%, transparent)" },
  suspended: { bg: "var(--color-error-light)", color: "var(--color-error)", border: "color-mix(in srgb, var(--color-error) 35%, transparent)" },
  rejected: { bg: "var(--color-error-light)", color: "var(--color-error)", border: "color-mix(in srgb, var(--color-error) 35%, transparent)" },
  deactivated: { bg: "var(--color-surface-muted)", color: "var(--color-foreground-muted)", border: "var(--color-border)" },
  inactive: { bg: "var(--color-surface-muted)", color: "var(--color-foreground-muted)", border: "var(--color-border)" },
};

export default function StatusPill({ status, label }) {
  if (!status) return <span className="text-foreground-disabled">—</span>;
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

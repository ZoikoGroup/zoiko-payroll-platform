export default function Field({ label, value }) {
  return (
    <div>
      <p className="text-foreground-muted mb-1">{label}</p>
      <p className="font-medium text-foreground">{value || "—"}</p>
    </div>
  );
}

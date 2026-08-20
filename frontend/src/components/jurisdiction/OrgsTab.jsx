import { Plus } from "lucide-react";

export default function OrgsTab({ orgs, onAssign }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Organizations currently assigned this pack version.</p>
        <button onClick={onAssign} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Assign Organizations
        </button>
      </div>
      {orgs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No organizations assigned yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {orgs.map((o) => (
            <li key={o.id} className="flex items-center justify-between rounded-lg border border-border-light px-3 py-2 text-xs">
              <span className="font-medium text-foreground">{o.organizationName} <span className="font-mono text-foreground-disabled">{o.organizationCode}</span></span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

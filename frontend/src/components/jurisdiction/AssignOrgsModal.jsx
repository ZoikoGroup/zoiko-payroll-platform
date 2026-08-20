import Modal from "../Modal";

export default function AssignOrgsModal({ eligibleOrgs, assignedIds, selected, setSelected, onClose, onSave }) {
  function toggle(id) {
    setSelected((prev) => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
  }
  const unassigned = eligibleOrgs.filter((o) => !assignedIds.has(o.id));
  return (
    <Modal title="Assign Organizations" onClose={onClose} maxWidth="max-w-md">
      {unassigned.length === 0 ? (
        <p className="py-6 text-center text-xs text-foreground-disabled">No eligible organizations to assign (all matching orgs are already assigned, or none match this jurisdiction).</p>
      ) : (
        <div className="max-h-80 space-y-1.5 overflow-y-auto">
          {unassigned.map((o) => (
            <label key={o.id} className="flex items-center gap-2 rounded-lg border border-border-light px-3 py-2 text-xs hover:bg-surface-muted">
              <input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} />
              <span className="font-medium text-foreground">{o.organizationName}</span>
              <span className="font-mono text-foreground-disabled">{o.organizationCode}</span>
            </label>
          ))}
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={onSave} disabled={selected.size === 0} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">Assign</button>
      </div>
    </Modal>
  );
}

import { FileUp, Plus } from "lucide-react";

// Plain-language empty state for a Belgian band / formula / table key with no
// rows yet: what is missing, the two ways to fill it, and that nothing counts
// until a second Super Admin signs it. No value is suggested.
export default function BEEmptyRows({ title, pack, editable, onAdd, onImport }) {
  return (
    <div className="rounded-lg border border-dashed border-border-light px-4 py-6 text-center text-xs" data-testid="be-empty-rows">
      <p className="font-semibold text-foreground">No rows loaded yet{title ? ` for ${title}` : ""}.</p>
      {editable ? (
        <p className="mx-auto mt-1 max-w-xl text-foreground-secondary">
          Add rows, or import them from the official source file. Every row needs its source reference, and it only
          counts once a second Super Admin has signed it.
        </p>
      ) : (
        <p className="mx-auto mt-1 max-w-xl text-foreground-secondary">
          This pack is {pack?.status || "locked"}: rows cannot be added to it. Create a new version to add them.
        </p>
      )}
      {editable && (onAdd || onImport) && (
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          {onAdd && (
            <button type="button" onClick={onAdd} data-testid="be-empty-add"
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
              <Plus size={13} /> Add row
            </button>
          )}
          {onImport && (
            <button type="button" onClick={onImport} data-testid="be-empty-import"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
              <FileUp size={13} /> Import from file
            </button>
          )}
        </div>
      )}
    </div>
  );
}

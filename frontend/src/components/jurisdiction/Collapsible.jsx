import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

// A card whose body opens on demand. The body mounts only while open, so a
// section that loads its own data does so only when someone looks at it.
// `badge` sits next to the title, `summary` is one line under it.
export default function Collapsible({ title, badge, summary, defaultOpen = false, testId, children }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <div className="rounded-xl border border-border bg-surface" data-testid={testId}>
      <button
        type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={bodyId}
        className="flex w-full items-start gap-3 rounded-xl px-4 py-3 text-left hover:bg-surface-muted"
      >
        <ChevronDown size={16} aria-hidden="true"
          className={`mt-0.5 shrink-0 text-foreground-muted transition-transform ${open ? "" : "-rotate-90"}`} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[14px] font-semibold text-foreground">{title}</span>
            {badge}
          </span>
          {summary ? <span className="mt-0.5 block text-[12px] text-foreground-secondary">{summary}</span> : null}
        </span>
      </button>
      {open && <div id={bodyId} className="border-t border-border px-4 py-3">{children}</div>}
    </div>
  );
}

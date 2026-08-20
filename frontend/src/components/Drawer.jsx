import { X } from "lucide-react";

// Slide-in panel from the right — same backdrop/theming convention as
// Modal.jsx (bg-surface/text-foreground tokens, so both work in light and
// dark automatically), just anchored to the right edge instead of centered.
// Callers own their own content/footer, same contract as Modal.
export default function Drawer({ title, subtitle, badge, onClose, children, footer, width = "max-w-md" }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className={`h-full w-full ${width} bg-surface shadow-2xl flex flex-col`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-foreground">{title}</h3>
              {badge}
            </div>
            {subtitle && <p className="mt-0.5 text-xs text-foreground-muted">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-foreground-muted hover:bg-surface-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-border px-5 py-3 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

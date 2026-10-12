import { useId } from "react";
import { X } from "lucide-react";

// Extracted from the backdrop+card markup duplicated across OrganizationsPage's
// create/edit form and StatutoryRateModal — a plain positioning/backdrop shell,
// not a form component. Callers own their own <form> and footer buttons.
// Dialog semantics (role/aria-modal/labelled by the title) are attributes
// only — no behaviour change; Escape-to-close and focus trapping would change
// every caller's behaviour and are deliberately not added here.
export default function Modal({ title, children, onClose, maxWidth = "max-w-lg" }) {
  const titleId = useId();
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`bg-surface rounded-xl shadow-lg w-full ${maxWidth} max-h-[90vh] overflow-y-auto p-6`}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 id={titleId} className="text-lg font-semibold text-foreground">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-foreground-muted hover:bg-surface-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

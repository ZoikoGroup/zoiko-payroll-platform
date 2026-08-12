import { X } from "lucide-react";

// Extracted from the backdrop+card markup duplicated across OrganizationsPage's
// create/edit form and StatutoryRateModal — a plain positioning/backdrop shell,
// not a form component. Callers own their own <form> and footer buttons.
export default function Modal({ title, children, onClose, maxWidth = "max-w-lg" }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className={`bg-white dark:bg-[#221D1A] rounded-xl shadow-lg w-full ${maxWidth} max-h-[90vh] overflow-y-auto p-6`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-[#F0EDE8]">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-slate-400 dark:text-[#9E9690] hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-600 dark:hover:text-[#F0EDE8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-500"
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

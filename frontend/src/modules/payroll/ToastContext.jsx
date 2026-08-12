// Relocated to src/context/ToastContext.jsx so it can be shared outside the
// payroll module (e.g. the Super Admin console). Re-exported here so the
// many existing payroll files importing from this path keep working.
export { ToastProvider, useToast } from "../../context/ToastContext";

import { Link } from "react-router-dom";
import { ArrowLeft, FileText } from "lucide-react";
import WorkerDataLocked from "../components/WorkerDataLocked";

// Super Admin > Compliance > RTI & Forms.
//
// ZP-PRIV: this page used to list every UK FPS/EPS/P45/P60, India Form
// 130/138/123 and Hong Kong BIR56A/IR56 form across all organizations. Those
// are per-employee filings, so the cross-org endpoint is retired (worker-level
// data needs a live, organization-approved Support Access grant). The page no
// longer calls it; organizations generate and track their forms from their own
// Reports screen.
export default function RtiFormsPage() {
  return (
    <div>
      <Link to="/super-admin/compliance" className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
        <ArrowLeft size={14} /> Back to Compliance
      </Link>
      <div className="mb-6 flex items-center gap-2">
        <FileText size={20} className="text-primary" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">RTI & Statutory Forms</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            UK RTI submissions, India TDS forms and Hong Kong employer returns are generated per employee by each organization.
          </p>
        </div>
      </div>
      <WorkerDataLocked variant="support" title="Statutory forms are worker-level data">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Each organization generates, submits and tracks its FPS/EPS/P45/P60, Form 130/138/123 and BIR56A/IR56 forms
          from its own Reports screen.
        </p>
      </WorkerDataLocked>
    </div>
  );
}

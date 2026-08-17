import { Download } from "lucide-react";
import { downloadPayslip } from "../../../service/payrollService";

export default function PayslipDownloadButton({ payslip, className = "", iconOnly = false }) {
  if (iconOnly) {
    return (
      <button
        onClick={() => downloadPayslip(payslip)}
        title="Download payslip"
        className={`rounded-[10px] p-1.5 text-foreground-muted hover:text-primary hover:bg-primary/10 transition-colors ${className}`}
      >
        <Download size={14} />
      </button>
    );
  }
  return (
    <button
      onClick={() => downloadPayslip(payslip)}
      className={`flex items-center gap-1.5 rounded-[12px] px-3 py-1.5 text-[12px] font-semibold border border-border bg-surface-muted text-primary transition-all duration-200 hover:border-primary hover:shadow-[0_2px_8px_rgba(25,197,138,0.15)] ${className}`}
    >
      <Download size={12} /> Download
    </button>
  );
}

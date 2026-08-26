import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { formatCurrency } from "../../../utils/currency";
import { getPayrollLabels, getIdentityField, getIncomeTaxLines } from "../../../utils/jurisdictionLabels";

const printStyles = `
@media print {
  @page { size: A4; margin: 0; }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .ps-backdrop { display: none !important; }
  .ps-outer { position: fixed !important; inset: 0 !important; display: flex !important; align-items: stretch !important; justify-content: center !important; padding: 0 !important; z-index: 9999 !important; }
  .ps-inner { width: 210mm !important; height: 297mm !important; max-height: none !important; max-width: none !important; border-radius: 0 !important; box-shadow: none !important; display: flex !important; flex-direction: column !important; overflow: hidden !important; }
  .ps-close-btn { display: none !important; }
  .ps-main { flex: 1 !important; display: flex !important; flex-direction: column !important; }
  .ps-body { flex: 1 !important; }
  .ps-footer { margin-top: auto !important; }
  .ps-no-print { display: none !important; }
}
`;

const amountToWords = (n) => {
  if (n == null || isNaN(n)) return "Zero";
  const a = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen","Sixteen","Seventeen","Eighteen","Nineteen"];
  const b = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"];
  const num = Math.round(n * 100) / 100;
  const whole = Math.floor(num);
  const dec = Math.round((num - whole) * 100);
  const convert = (m) => {
    if (m < 20) return a[m];
    if (m < 100) return b[Math.floor(m / 10)] + (m % 10 ? " " + a[m % 10] : "");
    if (m < 1000) return a[Math.floor(m / 100)] + " Hundred" + (m % 100 ? " " + convert(m % 100) : "");
    if (m < 100000) return convert(Math.floor(m / 1000)) + " Thousand" + (m % 1000 ? " " + convert(m % 1000) : "");
    if (m < 10000000) return convert(Math.floor(m / 100000)) + " Lakh" + (m % 100000 ? " " + convert(m % 100000) : "");
    return convert(Math.floor(m / 10000000)) + " Crore" + (m % 10000000 ? " " + convert(m % 10000000) : "");
  };
  let words = whole === 0 ? "Zero" : convert(whole);
  if (dec > 0) words += " and " + convert(dec) + " Paise";
  return words;
};

export default function PayslipStub({ payslip, onClose, currencyCode = "INR", company = null }) {
  useEffect(() => {
    if (!payslip) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [payslip]);

  if (!payslip) return null;

  const companyName = company?.name?.trim() || "Company name not set";
  const companyAddress = company?.address?.trim() || "Address not set — add it in Compliance › Company Details";

  const fmt = (n) => formatCurrency(n || 0, currencyCode);
  const labels = getPayrollLabels(payslip.country);
  const identity = getIdentityField(payslip);

  const earningsRows = [
    { label: "Basic Pay", amount: payslip.basicPay },
    { label: "HRA", amount: payslip.hra },
    ...(payslip.allowanceItems || []).map((a) => ({ label: a.label, amount: a.amount })),
    { label: "Special Allowance", amount: payslip.specialAllowance },
    { label: "Overtime", amount: payslip.overtime || 0 },
    { label: "Additional Compensation", amount: payslip.additionalCompensation || 0 },
  ].filter((r) => Number(r.amount) > 0);

  const deductionRows = [
    ...getIncomeTaxLines(payslip).map(([label, amount]) => ({ label, amount })),
    { label: labels.pf, amount: payslip.pf },
    { label: labels.esi, amount: payslip.esi },
    { label: "Professional Tax", amount: payslip.professionalTax },
    { label: labels.socialSecurity, amount: payslip.socialSecurity || 0 },
    { label: labels.medicare, amount: payslip.medicare || 0 },
    { label: "NI Employee", amount: payslip.niEmployee || 0 },
    { label: "Workplace Pension", amount: payslip.employeePension || 0 },
    { label: "Student Loan Deduction", amount: payslip.studyLoanDeduction || 0 },
  ].filter((r) => Number(r.amount) > 0);

  // Employer-side contributions (PF/ESI/Social Security/Medicare/Pension/NI)
  // are deliberately NOT shown here — this is the employee's own payslip,
  // and none of these are amounts deducted from the employee's pay. They
  // remain visible to admins on the Run Detail / Payroll Register views.
  const allDeductionRows = deductionRows;

  const computedEarnings = earningsRows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  const computedDeductions = allDeductionRows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  const totalEarnings = (Number(payslip.totalEarnings) || 0) || computedEarnings;
  const totalDeductions = (Number(payslip.totalDeductions) || 0) || computedDeductions;
  const netPay = payslip.netPay != null ? Number(payslip.netPay) : totalEarnings - totalDeductions;
  const netInWords = amountToWords(netPay);

  const employeeFields = [
    ["Employee", payslip.employee],
    ["Employee ID", payslip.employeeId],
    ["Payslip No.", payslip.payslipNumber || null],
    ["Department", payslip.department],
    ["Pay Date", payslip.payDate],
    ["Bank Name", payslip.bankName || null],
    ["Bank Account", payslip.bankAccount],
    [identity.label, identity.value],
    ["Payable Days", payslip.payableDays != null && payslip.totalWorkingDays != null
      ? `${payslip.payableDays} / ${payslip.totalWorkingDays}` : null],
  ].filter(([, val]) => val !== null);

  const half = Math.ceil(employeeFields.length / 2);
  const leftFields = employeeFields.slice(0, half);
  const rightFields = employeeFields.slice(half);

  return createPortal(
    <>
      <style>{printStyles}</style>
      <div className="ps-backdrop fixed inset-0 z-[9998] bg-background/40 backdrop-blur-sm" onClick={onClose} />
      <div className="ps-outer fixed inset-0 z-[9999] flex items-center justify-center p-4">
        <div className="ps-inner relative bg-surface rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] w-full max-w-4xl max-h-[90vh] overflow-auto">
          {/* HEADER */}
          <div className="bg-brand-navy-deep px-8 py-5 text-white flex items-center justify-between rounded-t-[18px]">
            <div>
              <p className="text-2xl font-extrabold tracking-tight">{companyName}</p>
              <p className="text-[13px] opacity-80 mt-1">{companyAddress}</p>
            </div>
            <button onClick={onClose} className="ps-close-btn rounded-[10px] p-1.5 bg-white/15 hover:bg-white/25 transition-all duration-200">
              <X size={16} />
            </button>
          </div>

          {/* MAIN CONTENT */}
          <div className="ps-main px-7 py-6">
            {/* PAYSLIP TITLE */}
            <div className="text-center mb-6">
              <p className="text-lg font-extrabold text-foreground tracking-wide">PAYSLIP</p>
              <p className="text-[13px] font-semibold text-foreground-muted mt-1">Salary Month : {payslip.period}</p>
            </div>

            {/* EMPLOYEE DETAILS */}
            <p className="text-[14px] font-bold text-foreground mb-3">Employee Details</p>
            <div className="border border-border rounded-[8px] overflow-hidden mb-6">
              {[leftFields, rightFields].map((side, si) => (
                <div key={si} className={si === 0 ? "border-b border-border" : ""}>
                  {side.map(([label, val], i) => (
                    <div key={label} className={`flex border-b border-border last:border-b-0 ${i % 2 === 0 ? 'bg-surface-muted' : 'bg-surface'}`}>
                      <span className="w-1/4 px-4 py-3 text-[12px] font-bold text-foreground-muted uppercase tracking-wider border-r border-border">{label}</span>
                      <span className="w-3/4 px-4 py-3 text-[13px] font-medium text-foreground">{val || "\u2014"}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            {/* PRORATION WARNING */}
            {payslip.payableDays != null && payslip.totalWorkingDays != null &&
              payslip.payableDays < payslip.totalWorkingDays && (
              <div className="rounded-[8px] bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40 px-4 py-2.5 flex items-start gap-2 mb-6">
                <span className="text-amber-500 text-[13px] mt-0.5">⚠</span>
                <p className="text-[12px] text-amber-700 dark:text-amber-400">
                  Prorated for <strong>{payslip.payableDays} of {payslip.totalWorkingDays}</strong> payable working days
                  this period ({Math.round((payslip.payableDays / payslip.totalWorkingDays) * 100)}% of full pay) —
                  basic, HRA, and special allowance below are already scaled down for recorded absence/unpaid leave.
                </p>
              </div>
            )}

            {/* EARNINGS & DEDUCTIONS */}
            <div className="ps-body grid grid-cols-2 gap-6 mb-5">
              {/* EARNINGS TABLE */}
              <div>
                <p className="text-[14px] font-bold text-foreground mb-3">Earnings</p>
                <div className="border border-border rounded-[8px] overflow-hidden">
                  <div className="bg-brand-navy-deep px-4 py-3 text-white text-[12px] font-bold uppercase tracking-wider flex justify-between">
                    <span>Component</span>
                    <span>Amount</span>
                  </div>
                  {earningsRows.map((r, i) => (
                    <div key={r.label} className={`flex justify-between px-4 py-3 border-b border-border last:border-b-0 text-[13px] ${i % 2 === 1 ? 'bg-surface-muted' : 'bg-surface'}`}>
                      <span className="text-foreground-muted">{r.label}</span>
                      <span className="font-semibold text-foreground">{fmt(r.amount)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between px-4 py-3 bg-brand-navy-deep text-white text-[13px] font-bold">
                    <span>Total Earnings</span>
                    <span>{fmt(totalEarnings)}</span>
                  </div>
                </div>
              </div>

              {/* DEDUCTIONS TABLE */}
              <div>
                <p className="text-[14px] font-bold text-foreground mb-3">Deductions</p>
                <div className="border border-border rounded-[8px] overflow-hidden">
                  <div className="bg-brand-navy-deep px-4 py-3 text-white text-[12px] font-bold uppercase tracking-wider flex justify-between">
                    <span>Component</span>
                    <span>Amount</span>
                  </div>
                  {allDeductionRows.map((r, i) => (
                    <div key={r.label} className={`flex justify-between px-4 py-3 border-b border-border last:border-b-0 text-[13px] ${i % 2 === 1 ? 'bg-surface-muted' : 'bg-surface'}`}>
                      <span className="text-foreground-muted">{r.label}</span>
                      <span className="font-semibold text-foreground">{fmt(r.amount)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between px-4 py-3 bg-brand-navy-deep text-white text-[13px] font-bold">
                    <span>Total Deductions</span>
                    <span>{fmt(totalDeductions)}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* SALARY SUMMARY */}
            <div className="flex justify-end mb-5">
              <div className="w-[50%] border border-border rounded-[8px] overflow-hidden">
                <div className="flex justify-between px-4 py-3 border-b border-border text-[13px] bg-surface">
                  <span className="font-bold text-foreground-muted">Gross Salary</span>
                  <span className="font-semibold text-foreground">{fmt(totalEarnings)}</span>
                </div>
                <div className="flex justify-between px-4 py-3 border-b border-border text-[13px] bg-surface-muted">
                  <span className="font-bold text-foreground-muted">Total Deductions</span>
                  <span className="font-semibold text-foreground">{fmt(totalDeductions)}</span>
                </div>
                <div className="flex justify-between px-4 py-3.5 bg-success-light dark:bg-primary/10 text-[14px] font-bold text-success border-t-2 border-success">
                  <span>NET PAY</span>
                  <span>{fmt(netPay)}</span>
                </div>
              </div>
            </div>

            {/* NET SALARY IN WORDS */}
            <div className="mb-5">
              <p className="text-[13px] font-bold text-foreground mb-2">Net Salary in Words</p>
              <p className="text-[13px] text-foreground-muted">{netInWords} Only.</p>
            </div>

            {/* PAYMENT DETAILS */}
            <div className="border border-border rounded-[8px] overflow-hidden mb-6">
              <div className="grid grid-cols-2 border-b border-border">
                <div className="px-4 py-3 text-[12px] font-bold text-foreground-muted uppercase tracking-wider border-r border-border">Payment Mode</div>
                <div className="px-4 py-3 text-[12px] font-bold text-foreground-muted uppercase tracking-wider">Salary Credit Date</div>
              </div>
              <div className="grid grid-cols-2">
                <div className="px-4 py-3 text-[13px] font-medium text-foreground border-r border-border">Bank Transfer (NEFT)</div>
                <div className="px-4 py-3 text-[13px] font-medium text-foreground">{payslip.payDate || "\u2014"}</div>
              </div>
            </div>

            {/* FOOTER */}
            <div className="ps-footer border-t border-border pt-4 text-center">
              <p className="text-[11px] text-foreground-muted">This is a computer-generated payslip and does not require a signature.</p>
            </div>
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}
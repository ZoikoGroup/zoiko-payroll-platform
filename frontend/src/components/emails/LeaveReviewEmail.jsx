import React from 'react';
import { AlertCircle, Shield, Info } from 'lucide-react';

/**
 * ELC-016 — Leave Request Rejected
 * Trigger:  employee.leave_request.rejected
 * Class:    P1 (action / decision required)
 * Audience: Employee (requester only)
 *
 * Compliant with Zoiko Payroll Email Communications System v2.0.0.
 * No leave dates, reasons, balances, or absence detail may appear in
 * the rendered output. All specifics live behind the secure CTA link.
 *
 * The copy intentionally uses "was not approved" rather than "denied
 * and closed" to preserve resubmission pathways where permitted (§10
 * rule 6 of the ECS v2.0.0 implementation prompt).
 */
export default function LeaveReviewEmail({
  recipientFirstName = "Alex",
  organizationName = "Acme Corp",
  decidedAtLocal = "Aug 22, 2026 at 2:15 PM EST",
  referenceId = "LV-4492-REV",
  approvedSupportAndLegalFooter = "© 2026 Zoiko Payroll Inc. • 100 Corporate Blvd, Suite 400 • Privacy Policy • Terms of Service"
}) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans flex items-center justify-center p-4 antialiased">
      {/* Hidden Preheader for Email Clients */}
      <div className="hidden max-h-0 overflow-hidden text-transparent opacity-0 select-none">
        Review the decision and available next steps securely.
      </div>

      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-xl shadow-2xl overflow-hidden">

        {/* Header Branding */}
        <div className="px-8 pt-8 pb-6 border-b border-slate-800/80 bg-slate-900/50 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white shadow-md shadow-indigo-600/30">
              Z
            </div>
            <span className="font-semibold text-lg tracking-tight text-white">
              Zoiko<span className="text-indigo-400 font-normal">Payroll</span>
            </span>
          </div>
          <span className="text-xs font-mono px-2.5 py-1 rounded-full bg-amber-950/80 text-amber-400 border border-amber-800/50 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400"></span>
            Action Required
          </span>
        </div>

        {/* Body Content */}
        <div className="px-8 py-6 space-y-6">
          <div className="space-y-2">
            <h1 className="text-xl font-semibold text-white tracking-tight">
              Action required: your Zoiko Payroll leave request needs review
            </h1>
            <p className="text-sm text-slate-300 leading-relaxed">
              Hello <span className="font-medium text-white">{recipientFirstName}</span>,
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">
              Your leave request for <span className="font-medium text-white">{organizationName}</span> was not approved. The decision was recorded at{" "}
              <span className="font-medium text-indigo-300">{decidedAtLocal}</span>.
            </p>
            <p className="text-sm text-slate-300 leading-relaxed pt-1">
              The secure workspace contains the reason, the decision owner, and any options available to you, including resubmission where permitted. No leave dates, reasons, or absence details are included in this email.
            </p>
          </div>

          {/* Primary Action Button — single CTA per ECS v2.0.0 §10 */}
          <div className="pt-1 pb-1">
            <a
              href="#review-leave-request-decision"
              className="w-full inline-flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white font-medium text-sm py-3 px-4 rounded-lg transition-all duration-150 shadow-lg shadow-indigo-600/20 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900"
            >
              <AlertCircle className="w-4 h-4" />
              Review leave request decision
            </a>
          </div>

          {/* Secondary Guidance */}
          <div className="p-3.5 bg-slate-950/50 rounded-lg border border-slate-800/80 flex gap-3 text-xs text-slate-400">
            <Info className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
            <p className="leading-relaxed">
              <strong className="text-slate-300 font-medium">Secondary guidance:</strong> If you have questions about this decision, use your organization's designated support route rather than replying to this email.
            </p>
          </div>

          {/* Reference Block */}
          <div className="flex items-center justify-between py-2.5 px-3.5 bg-slate-950/60 rounded-lg border border-slate-800/60 text-xs">
            <span className="text-slate-400 font-medium">Reference Code</span>
            <span className="font-mono text-slate-300 bg-slate-800/80 px-2 py-0.5 rounded text-[11px]">
              {referenceId}
            </span>
          </div>

          {/* Mandatory Security Notice — verbatim per ECS v2.0.0 §10 */}
          <div className="p-4 bg-indigo-950/20 rounded-lg border border-indigo-900/30 flex gap-3">
            <Shield className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
            <p className="text-xs text-slate-400 leading-relaxed">
              <strong className="text-slate-300 font-semibold block mb-0.5">Security Advisory</strong>
              Zoiko Payroll will never ask you to send your password, multifactor authentication code, bank details, tax identifiers, or payroll files by email.
            </p>
          </div>
        </div>

        {/* Legal Footer */}
        <div className="px-8 py-5 bg-slate-950/80 border-t border-slate-800/80 text-center text-xs text-slate-500 space-y-2">
          <p className="leading-relaxed">
            {approvedSupportAndLegalFooter}
          </p>
        </div>

      </div>
    </div>
  );
}

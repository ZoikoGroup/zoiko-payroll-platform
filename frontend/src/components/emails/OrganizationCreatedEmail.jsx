import React from 'react';
import { Building2, Shield, Info, Rocket } from 'lucide-react';

/**
 * COM-001 — Organization Account Created
 * Family:   Subscription, Billing and Commercial Account
 * Trigger:  commercial.organization_created
 * Class:    P1
 * Audience: Primary administrator only
 *
 * Compliant with Zoiko Payroll Email Communications System v2.0.0.
 * States plainly that production payroll remains BLOCKED until required readiness
 * controls (admin setup, security config, role assignment) are complete.
 * Does not include billing values, jurisdiction details, or employee data.
 */
export default function OrganizationCreatedEmail({
  recipientFirstName = "Alex",
  organizationName = "Acme Corp",
  referenceId = "ORG-1029-INIT",
  approvedSupportAndLegalFooter = "© 2026 Zoiko Payroll Inc. • 100 Corporate Blvd, Suite 400 • Privacy Policy • Terms of Service"
}) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans flex items-center justify-center p-4 antialiased">
      {/* Hidden Preheader for Email Clients */}
      <div className="hidden max-h-0 overflow-hidden text-transparent opacity-0 select-none">
        Complete administrative and security setup.
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
          <span className="text-xs font-mono px-2.5 py-1 rounded-full bg-indigo-950/80 text-indigo-400 border border-indigo-800/50 flex items-center gap-1.5">
            <Building2 className="w-3.5 h-3.5 text-indigo-400" />
            Setup Required
          </span>
        </div>

        {/* Body Content */}
        <div className="px-8 py-6 space-y-6">
          <div className="space-y-2">
            <h1 className="text-xl font-semibold text-white tracking-tight">
              Your Zoiko Payroll organization has been created
            </h1>
            <p className="text-sm text-slate-300 leading-relaxed">
              Hello <span className="font-medium text-white">{recipientFirstName}</span>,
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">
              The Zoiko Payroll organization for <span className="font-medium text-white">{organizationName}</span> is ready for initial configuration.
            </p>
            <p className="text-sm text-slate-300 leading-relaxed pt-1">
              Production payroll remains blocked until required readiness controls — including administrator setup, security configuration and role assignment — are complete. No payroll or employee data has been loaded as part of this step.
            </p>
          </div>

          {/* Primary Action Button — single CTA per ECS v2.0.0 */}
          <div className="pt-1 pb-1">
            <a
              href="#begin-organization-setup"
              className="w-full inline-flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white font-medium text-sm py-3 px-4 rounded-lg transition-all duration-150 shadow-lg shadow-indigo-600/20 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900"
            >
              <Rocket className="w-4 h-4" />
              Begin organization setup
            </a>
          </div>

          {/* Secondary Guidance Box */}
          <div className="p-3.5 bg-slate-950/50 rounded-lg border border-slate-800/80 flex gap-3 text-xs text-slate-400">
            <Info className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
            <p className="leading-relaxed">
              <strong className="text-slate-300 font-medium">Secondary guidance:</strong> Complete security settings (multifactor authentication, recovery options) before inviting additional administrators or users.
            </p>
          </div>

          {/* Reference Block */}
          <div className="flex items-center justify-between py-2.5 px-3.5 bg-slate-950/60 rounded-lg border border-slate-800/60 text-xs">
            <span className="text-slate-400 font-medium">Reference Code</span>
            <span className="font-mono text-slate-300 bg-slate-800/80 px-2 py-0.5 rounded text-[11px]">
              {referenceId}
            </span>
          </div>

          {/* Mandatory Security Notice — verbatim per ECS v2.0.0 */}
          <div className="p-4 bg-indigo-950/20 rounded-lg border border-indigo-900/30 flex gap-3">
            <Shield className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
            <p className="text-xs text-slate-400 leading-relaxed">
              <strong className="text-slate-300 font-semibold block mb-0.5">Security Advisory</strong>
              Zoiko Payroll will never ask you to send your password, multifactor authentication code, bank details, tax identifiers or payroll files by email.
            </p>
          </div>
        </div>

        {/* Approved Support and Legal Footer */}
        <div className="px-8 py-5 bg-slate-950/80 border-t border-slate-800/80 text-center text-xs text-slate-500 space-y-2">
          <p className="leading-relaxed">
            {approvedSupportAndLegalFooter}
          </p>
        </div>

      </div>
    </div>
  );
}

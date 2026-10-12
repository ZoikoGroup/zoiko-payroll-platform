import React from "react";
import { AlertTriangle, FileText, CheckCircle2, ShieldAlert, BookOpen } from "lucide-react";

export default function GermanyDeuvTab() {
  const messageTypes = [
    { code: "10", type: "ANMELDUNG", desc: "Start of employment (Beginn der Beschäftigung)" },
    { code: "30", type: "ABMELDUNG", desc: "End of employment (Ende der Beschäftigung)" },
    { code: "50", type: "JAHRESMELDUNG", desc: "Annual earnings notification (Jahresmeldung zur Sozialversicherung)" },
    { code: "51", type: "UNTERBRECHUNG", desc: "Interruption of employment without remuneration" },
    { code: "36", type: "BEENDIGUNG", desc: "End of insurable employment status" },
    { code: "82", type: "STORNIERUNG", desc: "Cancellation of previously submitted notification" },
  ];

  return (
    <div className="space-y-6">
      {/* Header & Status Banner */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-500" />
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">
                DEÜV Social Insurance Reporting Boundary (§28a SGB IV)
              </h2>
              <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs font-bold text-amber-600 dark:text-amber-400">
                SPECIFICATION_REQUIRED
              </span>
            </div>
            <p className="text-xs text-foreground-muted">
              DEÜV (Datenübermittlungs-Verordnung) governs statutory electronic reporting to health funds and social
              insurance carriers. The internal transmitter boundary is implemented and fail-closed. Transmission is
              blocked pending the official Datensatz and XML schema from GKV-Spitzenverband.
            </p>
          </div>
        </div>
      </div>

      {/* Statutory Notification Types Overview */}
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-foreground-muted flex items-center gap-2">
          <FileText size={14} /> Statutory Notification Types (Meldungsarten)
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border text-foreground-muted">
                <th className="pb-2 font-medium">Grund (Code)</th>
                <th className="pb-2 font-medium">Message Type</th>
                <th className="pb-2 font-medium">Description</th>
                <th className="pb-2 font-medium">Boundary Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {messageTypes.map((m) => (
                <tr key={m.code} className="hover:bg-surface-muted/50">
                  <td className="py-2.5 font-mono font-bold text-foreground">{m.code}</td>
                  <td className="py-2.5 font-mono text-primary font-semibold">{m.type}</td>
                  <td className="py-2.5 text-foreground-muted">{m.desc}</td>
                  <td className="py-2.5">
                    <span className="inline-flex items-center gap-1 rounded bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-foreground-muted">
                      <ShieldAlert size={12} className="text-amber-500" /> Fail-Closed (Spec Required)
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Operational Requirements & Action Items */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-surface p-4 space-y-3">
          <h4 className="text-xs font-bold uppercase tracking-wider text-foreground flex items-center gap-2">
            <BookOpen size={14} className="text-primary" /> Technical Architecture
          </h4>
          <ul className="space-y-2 text-xs text-foreground-muted">
            <li className="flex items-start gap-2">
              <CheckCircle2 size={14} className="mt-0.5 text-emerald-500 shrink-0" />
              <span>
                <strong>Transmitter Boundary:</strong> <code className="text-foreground">engine/germany_deuv.py</code>{" "}
                provides the <code className="text-foreground">DeuvTransmitter</code> interface and{" "}
                <code className="text-foreground">UnavailableDeuvTransmitter</code> fail-closed implementation.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 size={14} className="mt-0.5 text-emerald-500 shrink-0" />
              <span>
                <strong>Zero Mock Fallbacks:</strong> The system enforces fail-closed behavior rather than generating
                synthetic transmission acknowledgements or mock tickets.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 size={14} className="mt-0.5 text-emerald-500 shrink-0" />
              <span>
                <strong>Multi-Tenant Isolation:</strong> Request validation strictly binds submission contracts to
                individual tenant organizations (<code className="text-foreground">organization_id</code>).
              </span>
            </li>
          </ul>
        </div>

        <div className="rounded-lg border border-border bg-surface p-4 space-y-3">
          <h4 className="text-xs font-bold uppercase tracking-wider text-foreground flex items-center gap-2">
            <AlertTriangle size={14} className="text-amber-500" /> Production Prerequisites
          </h4>
          <ol className="list-decimal list-inside space-y-2 text-xs text-foreground-muted">
            <li>
              <strong>GKV-Spitzenverband Specification:</strong> Obtain the official current Datensatz schema document.
            </li>
            <li>
              <strong>Employer Betriebsnummer:</strong> Employer registration number issued by the Bundesagentur für
              Arbeit.
            </li>
            <li>
              <strong>Clearinghouse Channel:</strong> ITSG / sv.net communication server certificate and transmission
              authorization.
            </li>
          </ol>
        </div>
      </div>
    </div>
  );
}

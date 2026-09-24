import { useEffect, useState } from "react";
import {
  Building2, Users, Layers, Percent, Send, ShieldCheck,
  FileCheck2, AlertTriangle,
} from "lucide-react";
import {
  getFranceReadiness, getFranceEmployerProfile,
  listFranceEstablishmentRatePacks, listFrancePASRates, listFranceDsnSubmissions,
} from "../../../../service/superAdminService";
import { describeLoadError } from "../../../../service/errorClassification";
import {
  countLabel, dueDateClassLabel, readinessLabel, readinessChip,
  latestEffectif, DSN_STATUS_CHIP,
} from "./franceOverviewSummaries";

// Super Admin -> Compliance -> France landing overview. Everything below is
// organization-scoped (the authority data model of ZP-FR-ENG-001 — SIREN
// identity, URSSAF rate packs, DGFiP PAS rates and governed effectif are
// all per-employer), so an organization picker drives the whole workspace.
export default function FROverviewDashboard({ organizationId, organizations, onOrganizationChange }) {
  // orgId records which organization `data` was loaded for. The effect runs
  // after render, so when organizationId changes (null -> first org, or a
  // picker switch) there is one render where state still belongs to the
  // previous org; treat that as loading rather than reading stale/null data.
  const [state, setState] = useState({ orgId: null, loading: true, data: null, error: null });

  useEffect(() => {
    if (!organizationId) {
      setState({ orgId: null, loading: false, data: null, error: null });
      return;
    }
    let cancelled = false;
    setState({ orgId: organizationId, loading: true, data: null, error: null });
    Promise.all([
      getFranceReadiness({ organizationId }),
      getFranceEmployerProfile({ organizationId }),
      listFranceEstablishmentRatePacks({ organizationId }),
      listFrancePASRates({ organizationId }),
      listFranceDsnSubmissions({ organizationId }),
    ])
      .then(([readiness, profile, packs, pasRates, dsnSubmissions]) => {
        if (cancelled) return;
        setState({
          orgId: organizationId,
          loading: false,
          error: null,
          data: {
            readiness: readiness || {},
            profile: profile || null,
            packs: Array.isArray(packs) ? packs : [],
            pasRates: Array.isArray(pasRates) ? pasRates : [],
            dsnSubmissions: Array.isArray(dsnSubmissions) ? dsnSubmissions : [],
          },
        });
      })
      .catch((err) => {
        if (!cancelled) setState({ orgId: organizationId, loading: false, error: describeLoadError(err) || "Failed to load France overview.", data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  if (!organizationId) {
    return <p className="py-10 text-sm text-foreground-muted">Select an organization to view its France readiness.</p>;
  }

  if (state.loading || state.orgId !== organizationId || (!state.error && !state.data)) {
    return <p className="py-10 text-sm text-foreground-disabled">Loading France overview…</p>;
  }

  if (state.error) {
    return (
      <p className="py-10 text-sm text-foreground-muted">
        <AlertTriangle size={14} className="inline mr-1" />
        {state.error}
      </p>
    );
  }

  const { readiness, profile, packs, pasRates, dsnSubmissions } = state.data;
  const effectif = latestEffectif(profile?.effectifState);
  const activePack = packs.filter((p) => !p.effectiveTo);
  const activePas = pasRates.filter((p) => p.status === "ACTIVE");
  const openDsn = dsnSubmissions.find((d) => !["SETTLED", "BUSINESS_REJECTED"].includes(d.status));

  const tiles = [
    {
      key: "readiness",
      label: "Launch readiness",
      icon: ShieldCheck,
      detail: readinessLabel(readiness.readinessStatus),
      sub: readiness.ready ? "All FR-031 pre-submit checks pass" : `${countLabel("check", "checks")(readiness.missing?.length || 0)} blocked`,
      tone: readiness.ready ? "text-green-600" : "text-warning",
    },
    {
      key: "employer",
      label: "Employer profile",
      icon: Building2,
      detail: profile ? profile.siren : "Not configured",
      sub: profile ? `Filing due ${dueDateClassLabel(profile.filingDueDateClass)}` : "SIREN identity missing",
      tone: profile ? "text-foreground" : "text-warning",
    },
    {
      key: "effectif",
      label: "Governed effectif",
      icon: Users,
      detail: effectif ? `${effectif.value} (${effectif.year})` : "No record",
      sub: effectif ? `Source: ${effectif.source}` : "≥11 / ≥50 thresholds ungoverned",
      tone: effectif ? "text-foreground" : "text-warning",
    },
    {
      key: "rate-packs",
      label: "Establishment rate packs",
      icon: Layers,
      detail: `${packs.length} period${packs.length === 1 ? "" : "s"}`,
      sub: activePack.length ? `${activePack[0].siret} effective` : "No effective SIRET pack",
      tone: activePack.length ? "text-foreground" : "text-warning",
    },
    {
      key: "pas",
      label: "PAS rates",
      icon: Percent,
      detail: `${pasRates.length} rate${pasRates.length === 1 ? "" : "s"}`,
      sub: `${activePas.length} active (DGFiP CRM)`,
      tone: "text-foreground",
    },
    {
      key: "dsn",
      label: "DSN submissions",
      icon: Send,
      detail: `${dsnSubmissions.length} submission${dsnSubmissions.length === 1 ? "" : "s"}`,
      sub: openDsn ? `Open: ${openDsn.status}` : "No open submission",
      tone: openDsn && openDsn.status !== "VALIDATED" ? "text-warning" : "text-foreground",
    },
  ];

  return (
    <div>
      <div className="mb-3 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck size={16} className="text-primary" />
          <h2 className="text-sm font-bold text-foreground">France readiness overview</h2>
        </div>
        {readiness.ready ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-[11px] font-bold text-green-700">
            <FileCheck2 size={12} /> READY
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-bold text-amber-700">
            <AlertTriangle size={12} /> NOT READY
          </span>
        )}
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-muted p-3">
        <label className="text-xs font-semibold text-foreground-muted">Organization</label>
        <select
          value={organizationId ?? ""}
          onChange={(e) => onOrganizationChange(Number(e.target.value))}
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-semibold"
        >
          {!organizations.length && <option value="">No organizations</option>}
          {organizations.map((org) => (
            <option key={org.id} value={org.id}>
              {org.organizationName || org.name || `Org #${org.id}`}
            </option>
          ))}
        </select>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${readinessChip(readiness.readinessStatus)}`}>
          {readinessLabel(readiness.readinessStatus)}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {tiles.map((t) => (
          <div key={t.key} className="rounded-xl border border-border bg-surface p-4">
            <div className="flex items-center gap-2 text-foreground-muted">
              <t.icon size={15} />
              <p className="text-xs font-semibold">{t.label}</p>
            </div>
            <p className={`mt-2 text-lg font-bold ${t.tone}`}>{t.detail}</p>
            <p className="mt-0.5 text-xs text-foreground-disabled">{t.sub}</p>
          </div>
        ))}
      </div>

      {readiness.missing?.length ? (
        <div className="mt-5 rounded-lg border border-border bg-surface p-4">
          <p className="text-xs font-bold text-foreground mb-2">Readiness gaps (FR-031 pre-submit dry-run)</p>
          <ul className="space-y-1 text-xs text-foreground-muted list-disc list-inside">
            {readiness.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {dsnSubmissions.length ? (
        <div className="mt-5 rounded-lg border border-border bg-surface p-4">
          <p className="text-xs font-bold text-foreground mb-2">Latest DSN submissions</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">Period</th>
                <th className="py-1 pr-3 font-semibold">Due</th>
                <th className="py-1 pr-3 font-semibold">Release</th>
                <th className="py-1 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {dsnSubmissions.slice(0, 5).map((d) => (
                <tr key={d.id} className="border-t border-border">
                  <td className="py-1.5 pr-3">{d.periodStart} → {d.periodEnd}</td>
                  <td className="py-1.5 pr-3">{d.dueDate}</td>
                  <td className="py-1.5 pr-3">{d.releaseRef}</td>
                  <td className="py-1.5">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${DSN_STATUS_CHIP[d.status] || "bg-surface-muted text-foreground-muted"}`}>
                      {d.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
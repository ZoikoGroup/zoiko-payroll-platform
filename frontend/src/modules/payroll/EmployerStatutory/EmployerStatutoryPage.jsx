import { useState } from "react";
import { Landmark, Lock } from "lucide-react";
import { useAuth } from "../../../context/AuthContext";
import { ROLES } from "../../../config/roles";
import { getCountryNameFromCode, normalizeCountryCode } from "../../../utils/currency";
import { getComplianceData, getOrganizationDetail, storedOrganizationId } from "./employerStatutoryApi";
import { useIsMobile, useLoad } from "./hooks";
import { LoadingState, MobileWriteNotice } from "./ui";
import FranceTab from "./FranceTab";
import GermanyAccidentTab from "./GermanyAccidentTab";
import SaudiGosiTab from "./SaudiGosiTab";
import NetherlandsPremiumsTab from "./NetherlandsPremiumsTab";
import NetherlandsExpatSection from "./NetherlandsExpatSection";
import NetherlandsCatalogSection from "./NetherlandsCatalogSection";
import SwitzerlandPreviewTab from "./SwitzerlandPreviewTab";
import EmployerTaxProfilesTab from "./EmployerTaxProfilesTab";
import CollectiveAgreementsTab from "./CollectiveAgreementsTab";
import FilingRecordsTab from "./FilingRecordsTab";

// Employer statutory configuration, run by the organization itself (these
// functions moved out of Super Admin — ZP-PRIV decision 3). Every backend
// route takes the organization from the login token.
const ALLOWED_ROLES = new Set([ROLES.ORG_ADMIN, ROLES.PAYROLL_ADMIN]);

// Netherlands: premium decisions, 30% facility decisions and the
// organization's earning-classification / pension-scheme overrides.
function NetherlandsTab(props) {
  return (
    <div className="space-y-6">
      <NetherlandsPremiumsTab {...props} />
      <NetherlandsExpatSection {...props} />
      <NetherlandsCatalogSection {...props} />
    </div>
  );
}

// countries: which org jurisdictions show the tab (null = always shown).
const TABS = [
  { key: "fr", label: "France", countryLabel: "FR", countries: ["FR"], render: (p) => <FranceTab {...p} /> },
  { key: "de", label: "Germany accident insurance", countryLabel: "DE", countries: ["DE"], render: (p) => <GermanyAccidentTab {...p} /> },
  { key: "sa", label: "Saudi GOSI", countryLabel: "SA", countries: ["SA"], render: (p) => <SaudiGosiTab {...p} /> },
  { key: "nl", label: "Netherlands", countryLabel: "NL", countries: ["NL"], render: (p) => <NetherlandsTab {...p} /> },
  { key: "ch", label: "Switzerland preview", countryLabel: "CH", countries: ["CH"], render: (p) => <SwitzerlandPreviewTab {...p} /> },
  { key: "us", label: "Employer tax profiles", countryLabel: "US", countries: ["US", "CA", "AU"],
    render: (p) => <EmployerTaxProfilesTab {...p} country={["CA", "AU"].includes(p.country) ? p.country : "US"} /> },
  { key: "cba", label: "Collective agreements", countries: null, render: (p) => <CollectiveAgreementsTab {...p} /> },
  { key: "filings", label: "Filing records", countries: null, render: (p) => <FilingRecordsTab {...p} /> },
];

// The org's jurisdiction, resolved the same way the backend does
// (_resolve_org_country): the Compliance page's jurisdiction country first,
// then the organization's registered country. Either call may fail (e.g. a
// 403) — that just means "unknown", never an error screen.
async function loadOrgContext() {
  const [compliance, detail] = await Promise.all([
    getComplianceData().catch(() => null),
    getOrganizationDetail().catch(() => null),
  ]);
  const company = compliance?.company || null;
  const raw = company?.jurisdictionCountry || company?.jurisdiction_country || detail?.country || "";
  const country = normalizeCountryCode(raw) || (typeof raw === "string" && /^[A-Za-z]{2}$/.test(raw.trim()) ? raw.trim().toUpperCase() : "");
  return {
    country: country === "UK" ? "GB" : country,
    organizationId: detail?.id ?? storedOrganizationId(),
    organizationName: detail?.name || company?.name || "",
  };
}

export default function EmployerStatutoryPage() {
  const { role } = useAuth();
  const isMobile = useIsMobile();
  const { data: ctx, initialLoading } = useLoad(loadOrgContext);
  const [active, setActive] = useState(null);

  if (!ALLOWED_ROLES.has(role)) {
    return (
      <div className="p-6 lg:p-8">
        <div className="mx-auto max-w-lg rounded-[18px] border border-border bg-surface p-10 text-center">
          <Lock size={22} className="mx-auto mb-3 text-foreground-muted" aria-hidden="true" />
          <p className="text-[15px] font-bold text-foreground">You don&apos;t have permission to view this page</p>
          <p className="mt-1 text-[13px] text-foreground-muted">Employer statutory settings are managed by your organization admin or payroll admin.</p>
        </div>
      </div>
    );
  }

  const country = ctx?.country || "";
  const known = !!country;
  const tabs = TABS.filter((t) => !t.countries || !known || t.countries.includes(country));
  const current = tabs.find((t) => t.key === active) || tabs[0];
  const countryName = known ? getCountryNameFromCode(country) || country : "";

  return (
    <div className="min-h-full space-y-6 bg-background p-4 sm:p-6 lg:p-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-primary shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
            <Landmark size={18} className="text-white" aria-hidden="true" />
          </div>
          <div>
            <h1 className="text-[24px] font-extrabold tracking-tight text-foreground sm:text-[28px]">Employer statutory</h1>
            <p className="text-[13px] text-foreground-muted">
              Your employer registrations, statutory rates, agreements and filing records{ctx?.organizationName ? ` for ${ctx.organizationName}` : ""}.
            </p>
          </div>
        </div>
        {known && (
          <span className="rounded-full border border-primary/20 bg-primary/10 px-3.5 py-1.5 text-[11px] font-bold text-primary dark:bg-primary/20">
            Jurisdiction: {countryName}
          </span>
        )}
      </div>

      {initialLoading ? (
        <LoadingState text="Loading your organization…" />
      ) : (
        <>
          {!known && (
            <p className="rounded-[14px] border border-info/15 bg-info/5 px-4 py-3 text-[13px] text-foreground-muted dark:bg-info/10">
              We couldn&apos;t determine your organization&apos;s jurisdiction, so every section is shown. Use the one for your country —
              set the jurisdiction under Compliance &gt; Company Details to hide the others.
            </p>
          )}
          <MobileWriteNotice show={isMobile} />

          <div className="flex w-full flex-wrap gap-1 rounded-[14px] bg-surface-muted p-1 sm:w-fit dark:bg-surface-muted/60" role="tablist" aria-label="Employer statutory sections">
            {tabs.map((t) => (
              <button key={t.key} type="button" role="tab" aria-selected={current?.key === t.key} onClick={() => setActive(t.key)}
                className={`rounded-[10px] px-3.5 py-2 text-[13px] font-semibold transition-all duration-200 ${
                  current?.key === t.key
                    ? "bg-surface text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.08)] dark:shadow-none"
                    : "text-foreground-muted hover:text-foreground"
                }`}>
                {t.label}
                {!known && t.countryLabel && <span className="ml-1.5 rounded bg-foreground-muted/10 px-1.5 py-0.5 text-[10px] font-bold">{t.countryLabel}</span>}
              </button>
            ))}
          </div>

          {current && (
            <div role="tabpanel" aria-label={current.label} key={current.key}>
              {current.render({ readOnly: isMobile, country: known ? country : null, organizationId: ctx?.organizationId ?? null })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

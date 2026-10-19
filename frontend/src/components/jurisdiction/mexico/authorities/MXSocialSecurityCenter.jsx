import { useCallback, useEffect, useState } from "react";
import { card, Messages } from "../mxShared";
import {
  getMxAuthoritiesSummary, listMxIsnReturns, listMxLiabilities, listMxMovements, listMxSuaPeriods,
} from "../../../../service/payrollService";
import { Status } from "./authShared";
import MXIsnReturnsPanel from "./MXIsnReturnsPanel";
import MXLiabilitiesPanel from "./MXLiabilitiesPanel";
import MXMovementsPanel from "./MXMovementsPanel";
import MXSuaPanel from "./MXSuaPanel";

// Mexico Social Security Center (ZP-MX-ENG-001 §14, Phase 8) — IMSS movements,
// SUA / SIPARE, INFONAVIT, ISR remittance and state ISN, for YOUR organisation.
// File-export mode (D1): Zoiko prepares, reconciles and records; it never
// transmits to IDSE, SIPARE, SAT or a state portal, and never moves money.
function counts(obj) {
  const entries = Object.entries(obj || {});
  return entries.length ? entries.map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(" · ") : "none";
}

export default function MXSocialSecurityCenter() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [refused, setRefused] = useState(false);
  const [tick, setTick] = useState(0);
  const load = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    let active = true;
    Promise.all([getMxAuthoritiesSummary(), listMxMovements(), listMxLiabilities(), listMxSuaPeriods(), listMxIsnReturns()])
      .then(([summary, movements, liabilities, sua, isn]) => {
        if (!active) return;
        setData({ summary, movements, liabilities, sua, isn });
        setError(null);
      })
      .catch((e) => {
        if (!active) return;
        if (e?.status === 403) setRefused(e.message || "Mexico is not open on this platform.");
        else setError(e?.message || "The Social Security Center could not be loaded.");
      });
    return () => { active = false; };
  }, [tick]);

  if (refused) return <p className="text-[12px] text-foreground-muted" data-testid="mx-ss-refused">{refused}</p>;
  if (!data) return <div className="flex flex-col gap-2"><Messages error={error} />{!error && <p className="text-[12px] text-foreground-muted">Loading…</p>}</div>;
  const s = data.summary;
  const cards = [
    { key: "registration", title: "Employer registration",
      body: (s.registrations || []).map((r) => (
        <div key={r.id} className="flex items-center gap-1">{r.registroPatronal} · class {r.riskClass} · premium {r.riskPremiumPct ?? "—"}% <Status value={r.card} /></div>
      )) },
    { key: "movements", title: "Affiliation movements", body: counts(s.movements) },
    { key: "sua", title: "SUA period", body: counts(s.suaPeriods) },
    { key: "sipare", title: "SIPARE", body: <span className="text-foreground-muted">Payment line layout not transcribed (S12 / S16) — payments are recorded on the SUA period.</span> },
    { key: "workrisk", title: "Work-risk annual", body: <span className="text-foreground-muted">Deferred until S10 / S14 / S29 are transcribed.</span> },
    { key: "differences", title: "Differences", body: s.openDifferences ? <span className="text-error">{s.openDifferences} BLOCKING</span> : "none open" },
  ];
  return (
    <div className="flex flex-col gap-4" data-testid="mx-ss-center">
      <div>
        <h2 className="text-[16px] font-semibold text-foreground">Social Security & Authorities</h2>
        <p className="text-[12px] text-foreground-muted">
          File-export mode: Zoiko prepares worklists, liabilities, reconciliations and returns from committed payroll; you
          upload them to IDSE / SUA / SIPARE / SAT / the state portal and record the outcome here. Nothing is transmitted
          and no money moves from Zoiko.
        </p>
      </div>
      {s.unknown > 0 && (
        <p role="alert" className="rounded-lg border border-error/40 px-3 py-2 text-[12px] text-error" data-testid="mx-ss-unknown-banner">
          {s.unknown} item(s) UNKNOWN — the authority&apos;s answer is not known. Nothing is resent automatically: record a status
          check first; only after a NOT FOUND may an admin confirm a retry (same record, payload and key).
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3" data-testid="mx-ss-cards">
        {cards.map((c) => (
          <section key={c.key} className={card}>
            <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{c.title}</p>
            <div className="text-[12px] text-foreground">{c.body}</div>
          </section>
        ))}
      </div>
      <section className={card} data-testid="mx-ss-blocks">
        <p className="mb-1 text-[12px] font-semibold text-foreground">Not available yet</p>
        <ul className="space-y-1 text-[11px]">
          {(s.blocks || []).map((b) => <li key={b.code}><code>{b.code}</code> ({b.item}) · {b.message}</li>)}
        </ul>
      </section>
      <MXMovementsPanel rows={data.movements} reload={load} />
      <MXLiabilitiesPanel rows={data.liabilities} reload={load} />
      <MXSuaPanel rows={data.sua} registrations={s.registrations} reload={load} />
      <MXIsnReturnsPanel rows={data.isn} reload={load} />
    </div>
  );
}

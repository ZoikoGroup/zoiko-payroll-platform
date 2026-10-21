import WorkerDataLocked from "../../WorkerDataLocked";
import { getNlEmployerReadiness } from "../../../service/superAdminService";
import { NeedOrg, Messages, card, useLoad } from "./nlShared";

// Employer registration (spec §10). ZP-PRIV decision 3: the employer profile
// (KVK, RSIN, loonheffingennummer, PKIoverheid certificate) is the
// organization's own identity and is maintained from its workspace; the
// Super Admin profile routes are retired. The readiness card H stays visible
// — it reports status only.
export default function NLEmployerProfileTab({ orgId }) {
  const [card_, cardError, loading] = useLoad(() => (orgId ? getNlEmployerReadiness(orgId) : Promise.resolve(null)), [orgId]);

  if (!orgId) return <NeedOrg />;

  return (
    <div className="flex flex-col gap-4">
      <WorkerDataLocked variant="tenant" title="The employer profile is maintained by the organization">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          New profile versions are recorded by the organization&apos;s admins. The readiness card below shows its status.
        </p>
      </WorkerDataLocked>
      <Messages error={cardError} />
      {loading && !card_ && <p className="text-[12px] text-foreground-muted">Loading readiness…</p>}
      {card_ && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Readiness (card H) — {card_.overallStatus}</h3>
          {(card_.sections || []).map((s) => (
            <div key={s.section} className="mb-2">
              <p className="text-[12px] font-semibold text-foreground">{s.section}</p>
              <ul className="ml-4 list-disc text-[12px] text-foreground-muted">
                {(s.items || []).map((i) => <li key={i.key}>{i.label}: <span className="text-foreground">{i.status}</span></li>)}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

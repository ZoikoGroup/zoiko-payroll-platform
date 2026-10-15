import { useState } from "react";
import { createNlEmployerProfile, getNlEmployerProfile, getNlEmployerReadiness } from "../../../service/superAdminService";
import { NeedOrg, Messages, Field, card, btnPrimary, input, useAction, useLoad } from "./nlShared";

// Employer registration (spec §10). A change records a NEW profile version
// from its effective date; the open version is closed the day before.
const FIELDS = [
  ["legalName", "Legal name"], ["kvkNumber", "KVK number"], ["rsin", "RSIN"],
  ["loonheffingennummer", "Loonheffingennummer"], ["loonheffingenSubnumber", "Sub-number"],
  ["registrationLetterRef", "Registration letter ref"], ["bankBic", "Bank BIC"],
  ["pkiCertFingerprint", "PKIoverheid cert fingerprint"], ["digipoortChannel", "Digipoort channel"],
];
const SELECTS = {
  returnPeriod: ["Return period", ["MONTH", "FOUR_WEEK"]],
  payrollSchedule: ["Payroll schedule", ["MONTH", "FOUR_WEEK", "WEEK"]],
  caoStatus: ["CAO status", ["NONE", "APPLICABLE", "UNKNOWN"]],
  wkrMode: ["WKR mode", ["STANDALONE", "CONCERN"]],
};

export default function NLEmployerProfileTab({ orgId }) {
  const [profile, profileError, , reload] = useLoad(() => (orgId ? getNlEmployerProfile(orgId) : Promise.resolve(null)), [orgId]);
  const [card_, cardError] = useLoad(() => (orgId ? getNlEmployerReadiness(orgId) : Promise.resolve(null)), [orgId]);
  const [form, setForm] = useState(null);
  const { run, error, notice, busy } = useAction(reload);

  if (!orgId) return <NeedOrg />;
  const startEdit = () => setForm({ ...(profile || {}), effectiveFrom: new Date().toISOString().slice(0, 10) });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    const payload = { effectiveFrom: form.effectiveFrom };
    [...FIELDS.map(([k]) => k), ...Object.keys(SELECTS)].forEach((k) => { if (form[k]) payload[k] = form[k]; });
    if (await run(() => createNlEmployerProfile(orgId, payload), "New employer-profile version recorded.")) setForm(null);
  };

  return (
    <div className="flex flex-col gap-4">
      <Messages error={profileError || cardError || error} notice={notice} />
      <div className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[14px] font-semibold text-foreground">
            Employer profile {profile ? `— version ${profile.version} from ${profile.effectiveFrom}` : "— none recorded"}
          </h3>
          {!form && <button type="button" className={btnPrimary} onClick={startEdit}>Record new version</button>}
        </div>
        {!form && profile && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] md:grid-cols-3">
            {[...FIELDS, ...Object.entries(SELECTS).map(([k, [l]]) => [k, l])].map(([k, l]) => (
              <div key={k}><dt className="text-foreground-muted">{l}</dt><dd className="text-foreground">{profile[k] || "—"}</dd></div>
            ))}
          </dl>
        )}
        {form && (
          <form onSubmit={save} className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <Field label="Effective from"><input type="date" required className={input} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
            {FIELDS.map(([k, l]) => (
              <Field key={k} label={l}><input className={input} value={form[k] || ""} onChange={set(k)} /></Field>
            ))}
            {Object.entries(SELECTS).map(([k, [l, opts]]) => (
              <Field key={k} label={l}>
                <select className={input} value={form[k] || ""} onChange={set(k)}>
                  <option value="">—</option>
                  {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </Field>
            ))}
            <div className="col-span-full flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy}>Save version</button>
              <button type="button" className="text-[12px] text-foreground-muted" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
      </div>
      {card_ && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Readiness (card H) — {card_.overallStatus}</h3>
          {(card_.sections || []).map((s) => (
            <div key={s.section} className="mb-2">
              <p className="text-[12px] font-semibold text-foreground">{s.section}</p>
              <ul className="ml-4 list-disc text-[12px] text-foreground-muted">
                {s.items.map((i) => <li key={i.key}>{i.label}: <span className="text-foreground">{i.status}</span></li>)}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

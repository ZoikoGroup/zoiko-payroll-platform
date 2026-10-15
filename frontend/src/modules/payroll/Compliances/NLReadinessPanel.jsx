import { getNlReadiness } from "../../../service/payrollService";
import { Messages, card, useLoad } from "../../../components/jurisdiction/netherlands/nlShared";

// Netherlands readiness (ZP-NL-ENG-001 §10 card H + §19 gates). The employer
// card is this organisation's own set-up; the G1–G8 gates are platform launch
// gates signed by Zoiko — shown so an employer can see why filing is locked.
const TONE = {
  COMPLETE: "text-success", READY: "text-success", SIGNED: "text-success",
  INCOMPLETE: "text-warning", SUBMITTED: "text-warning", OPEN: "text-foreground-muted",
  BLOCKED: "text-error",
};

export default function NLReadinessPanel() {
  const [data, error] = useLoad(() => getNlReadiness(), []);
  const employer = data?.employer;
  return (
    <div className="flex flex-col gap-4">
      <Messages error={error} />
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">
          Employer readiness {employer && <span className={TONE[employer.overallStatus] || ""}>— {employer.overallStatus}</span>}
        </h3>
        {!employer && <p className="text-[12px] text-foreground-muted">Record your employer registration first.</p>}
        {employer?.sections?.map((section) => (
          <div key={section.section} className="mb-3">
            <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{section.section}</p>
            <ul className="space-y-1">
              {section.items.map((item) => (
                <li key={item.key} className="flex flex-wrap justify-between gap-2 text-[12px]">
                  <span className="text-foreground">{item.label}{item.details && <span className="text-foreground-muted"> — {item.details}</span>}</span>
                  <span className={`font-semibold ${TONE[item.status] || ""}`}>{item.status}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Platform launch gates</h3>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Signed by Zoiko against official evidence. Filing and authority payments stay locked until G3 is signed.
        </p>
        <ul className="space-y-1">
          {(data?.gates || []).map((g) => (
            <li key={g.gate} className="flex justify-between gap-2 text-[12px]">
              <span className="text-foreground">{g.gate} — {g.label}</span>
              <span className={`font-semibold ${TONE[g.state] || ""}`}>{g.state}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

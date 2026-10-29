import { useState } from "react";
import { getMxStatutoryRules } from "../../../service/superAdminService";
import { Messages, OnDateBar, Table, card, useLoad } from "./mxShared";

// Mexico content that is not stored as pack rows (completion W5-1): special
// pay, termination, PTU, annual adjustment, the filing calendar, working
// time, state ISN inclusion and the annual ISR tariff. Read-only: each item
// shows the wording it rests on, the saved source file (manifest row, SHA-256,
// verification status) and [PENDING G1]. These rules change only through a
// code release that passes `verify_mexico_sources.py compare`.
const STATUS_TONE = { VERIFIED: "text-success", ARCHIVE_COPY_VERIFIED: "text-warning" };

function Citations({ item }) {
  return (
    <ul className="flex flex-col gap-1">
      {item.citations.map((c) => (
        <li key={`${c.cite}|${c.ref}`} className="text-[11px]">
          {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="text-primary underline">{c.title || c.cite}</a> : <span>{c.cite}</span>}
          {c.sha256 && <span className="ml-1 font-mono text-[10px] text-foreground-muted">sha256 {c.sha256.slice(0, 12)}…</span>}
          <span className={`ml-1 text-[10px] font-semibold ${STATUS_TONE[c.status] || "text-error"}`}>{c.status}</span>
          <div className="text-foreground-muted">{c.ref}</div>
        </li>
      ))}
    </ul>
  );
}

const pending = (i) => i.pendingG1 && (
  <span className="rounded bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold text-warning">PENDING G1</span>
);

function extra(i) {
  if (i.ratePct != null) return `cuota fija ${i.fixedQuota} + ${i.ratePct}%`;
  if (i.frequency) return [i.frequency, i.dueDay && `day ${i.dueDay}`, i.dueMonth && `month ${i.dueMonth}`].filter(Boolean).join(" · ");
  if (i.included != null) return i.included ? "In the base" : "Not in the base";
  if (i.exclusion) return "Exclusion";
  return "";
}

export default function MXStatutoryRulesTab() {
  const [on, setOn] = useState(null);
  const [view, error] = useLoad(() => getMxStatutoryRules(on), [on]);
  return (
    <div className="flex flex-col gap-4">
      <OnDateBar on={on} onChange={setOn} view={view} />
      <Messages error={error} />
      {view && !view.manifestAvailable && (
        <p className="text-[12px] text-error">The source manifest is not available on this server: citations show no file details.</p>
      )}
      {view?.families.map((f) => (
        <div key={f.family} className={card} data-testid={`mx-rules-${f.family}`}>
          <h3 className="mb-1 text-[14px] font-semibold text-foreground">{f.title}</h3>
          {f.note && <p className="mb-2 text-[12px] text-foreground-muted">{f.note}</p>}
          <Table rows={f.items} rowKey={(i) => i.key}
                 empty="Awaiting transcription — nothing is calculated from it; the calculations that need it BLOCK."
                 columns={[
                   { key: "label", label: "Rule" },
                   { key: "extra", label: "Detail", render: extra },
                   { key: "flags", label: "Review", render: pending },
                   { key: "citations", label: "Source and wording", render: (i) => <Citations item={i} /> },
                 ]} />
        </div>
      ))}
      {view && (
        <div className={card} data-testid="mx-rules-decisions">
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Open decisions (docs/mexico/DECISIONS_PENDING.md)</h3>
          <Table rows={view.decisions} rowKey={(d) => d.name}
                 columns={[
                   { key: "decision", label: "Decision" }, { key: "label", label: "Question" },
                   { key: "state", label: "State", render: (d) => (d.decided
                     ? <span className="text-success">Decided{d.value ? `: ${d.value}` : ""}</span>
                     : <span className="font-semibold text-error">Undecided — calculations that need it BLOCK</span>) },
                 ]} />
        </div>
      )}
      {view && <p className="text-[11px] text-foreground-muted">Read-only — changed only by {view.editVia}.</p>}
    </div>
  );
}

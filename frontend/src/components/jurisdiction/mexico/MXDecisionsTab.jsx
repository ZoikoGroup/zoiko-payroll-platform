import { useState } from "react";
import ConfirmDialog from "../../ConfirmDialog";
import {
  approveMxDecision, listMxDecisions, proposeMxDecision, reviseMxDecision, transcribedMxDecision, withdrawMxDecision,
} from "../../../service/superAdminService";
import { Messages, btn, btnPrimary, card, input, useLoad } from "./mxShared";

// Mexico decision register (final mile X1). Each open decision
// (DECISIONS_PENDING.md, gap register C4 / C5 / C12) with its options and
// sources; a gate owner proposes an answer, a different Super Admin approves
// it (the server enforces four-eyes, the typed grammar and immutability).
// An approved decision changes no calculation: it yields a transcription
// ticket for the next Draft pack.
const STATUS_TONE = {
  OPEN: "text-foreground-muted", PROPOSED: "text-warning", APPROVED: "text-success", TRANSCRIBED: "text-success",
  WITHDRAWN: "text-foreground-muted", SUPERSEDED: "text-foreground-muted",
};
const GATES = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"];
const STATUSES = ["OPEN", "PROPOSED", "APPROVED", "TRANSCRIBED", "WITHDRAWN", "SUPERSEDED"];

function Proposal({ d, onDone }) {
  const [form, setForm] = useState({ chosenOption: "", rationale: "", citedSources: "", ownerRole: d.ownerRole || "" });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const typed = d.allowedValues && d.allowedValues.length;
  return (
    <form className="mt-2 grid gap-2 md:grid-cols-2" aria-label={`Propose ${d.code}`}
          onSubmit={(e) => { e.preventDefault(); onDone({ ...form, citedSources: form.citedSources.split(",").map((s) => s.trim()).filter(Boolean) }); }}>
      <label className="text-[12px] text-foreground-secondary">Chosen option
        {typed
          ? <select aria-label="Chosen option" className={`${input} mt-1 w-full`} value={form.chosenOption} onChange={set("chosenOption")} required>
              <option value="">— choose —</option>{d.allowedValues.map((v) => <option key={v}>{v}</option>)}
            </select>
          : <input aria-label="Chosen option" className={`${input} mt-1 w-full`} value={form.chosenOption} onChange={set("chosenOption")} required
                   placeholder={d.answerKind === "ROUNDING_RULE" ? "MODE:QUANTUM, e.g. HALF_UP:0.01" : ""} />}
      </label>
      <label className="text-[12px] text-foreground-secondary">Cited sources (comma-separated S-codes or documents)
        <input aria-label="Cited sources" className={`${input} mt-1 w-full`} value={form.citedSources} onChange={set("citedSources")} required />
      </label>
      <label className="text-[12px] text-foreground-secondary md:col-span-2">Rationale
        <textarea aria-label="Rationale" className={`${input} mt-1 w-full`} rows={2} value={form.rationale} onChange={set("rationale")} required />
      </label>
      <label className="text-[12px] text-foreground-secondary">Owner role (text — D-23)
        <input aria-label="Owner role" className={`${input} mt-1 w-full`} value={form.ownerRole} onChange={set("ownerRole")} />
      </label>
      <div className="flex items-end"><button type="submit" className={btnPrimary}>Propose</button></div>
    </form>
  );
}

function Decision({ d, act }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [text, setText] = useState("");
  return (
    <div className="rounded-lg border border-border" data-testid={`mx-decision-${d.code}-v${d.version}`}>
      <button type="button" className="flex w-full items-start justify-between gap-3 px-3 py-2 text-left" onClick={() => setOpen(!open)}>
        <span className="text-[13px] text-foreground">
          <span className="font-semibold">{d.code}{d.version > 1 ? ` v${d.version}` : ""}</span> · {d.title}
          <span className="ml-2 text-[11px] text-foreground-muted">{d.gates.join(", ") || "no gate"}</span>
        </span>
        <span className={`shrink-0 text-[12px] font-semibold ${STATUS_TONE[d.status]}`} data-testid="mx-decision-status">{d.status}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2 text-[12px] text-foreground">
          <p>{d.question}</p>
          {d.options.length > 0 && (
            <div>
              <p className="font-semibold">Options</p>
              <ol className="ml-4 list-decimal space-y-1">
                {d.options.map((o, i) => <li key={i}>{o.label}{o.sources.length ? <span className="ml-1 text-foreground-muted">({o.sources.join(", ")})</span> : null}</li>)}
              </ol>
            </div>
          )}
          <p className="text-foreground-muted">
            Clears: {d.blockCodes.length ? d.blockCodes.map((c) => <code key={c} className="mr-1">{c}</code>) : "no engine block"} ·
            Populates: {d.contentKeys.length ? d.contentKeys.map((k) => <code key={k} className="mr-1">{k}</code>) : "—"} ·
            Question rests on: {d.questionSources.join(", ") || "—"} · Owner: {d.ownerRole || "—"}
          </p>
          {d.chosenOption && (
            <p data-testid="mx-decision-answer">
              <span className="font-semibold">Answer:</span> <code>{d.chosenOption}</code> — {d.rationale}
              <span className="ml-1 text-foreground-muted">(sources {d.citedSources.join(", ")}; hash {String(d.contentHash || "").slice(0, 12)})</span>
            </p>
          )}
          {d.ticket && (
            <div className="rounded border border-success/40 bg-success/5 p-2" data-testid="mx-decision-ticket">
              <p className="font-semibold">Transcription ticket{d.ticket.transcribed ? ` — transcribed (${d.ticket.transcriptionRef})` : ""}</p>
              <p>Set {d.ticket.contentKeys.join(", ") || "—"} = <code>{d.ticket.value}</code>, citing <code>{d.ticket.citation}</code>, in {d.ticket.target}; then {d.ticket.then}.</p>
            </div>
          )}
          {d.status === "OPEN" && <Proposal d={d} onDone={(form) => act(proposeMxDecision, d.id, form)} />}
          <div className="flex flex-wrap gap-2">
            {d.status === "PROPOSED" && <button type="button" className={btnPrimary} onClick={() => setConfirm("approve")}>Approve (second Super Admin)</button>}
            {(d.status === "PROPOSED" || d.status === "OPEN") && <button type="button" className={btn} onClick={() => setConfirm("withdraw")}>{d.status === "PROPOSED" ? "Withdraw proposal" : "Withdraw decision"}</button>}
            {(d.status === "APPROVED" || d.status === "TRANSCRIBED") && <button type="button" className={btn} onClick={() => setConfirm("revise")}>Revise (new version)</button>}
            {d.status === "APPROVED" && <button type="button" className={btn} onClick={() => setConfirm("transcribed")}>Mark transcribed</button>}
          </div>
          {(confirm === "withdraw" || confirm === "transcribed") && (
            <input aria-label={confirm === "withdraw" ? "Withdrawal reason" : "Transcription reference"} className={`${input} w-full`}
                   placeholder={confirm === "withdraw" ? "Reason" : "Commit / Draft pack that carries the value"} value={text} onChange={(e) => setText(e.target.value)} />
          )}
        </div>
      )}
      {confirm && (
        <ConfirmDialog
          title={{ approve: `Approve ${d.code}?`, withdraw: `Withdraw ${d.code}?`, revise: `Revise ${d.code}?`, transcribed: `Mark ${d.code} transcribed?` }[confirm]}
          message={{
            approve: "Approving records this answer as final and immutable. It changes no calculation: an engineer seeds it into a Draft pack, which still needs its own approval.",
            withdraw: d.status === "PROPOSED" ? "The proposal is cleared and the decision returns to OPEN." : "The decision is closed as no longer needed.",
            revise: "A new OPEN version is created; this one stays in force until the new version is approved.",
            transcribed: "Records the commit or Draft pack that carries the value.",
          }[confirm]}
          confirmLabel={{ approve: "Approve", withdraw: "Withdraw", revise: "Revise", transcribed: "Mark transcribed" }[confirm]}
          onClose={() => setConfirm(null)}
          onConfirm={async () => {
            const payload = confirm === "withdraw" ? { reason: text } : confirm === "transcribed" ? { reference: text } : undefined;
            const fn = { approve: approveMxDecision, withdraw: withdrawMxDecision, revise: reviseMxDecision, transcribed: transcribedMxDecision }[confirm];
            setConfirm(null);
            setText("");
            await act(fn, d.id, payload);
          }}
        />
      )}
    </div>
  );
}

export default function MXDecisionsTab() {
  const [gate, setGate] = useState("");
  const [status, setStatus] = useState("");
  const [tick, setTick] = useState(0);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [rows, error] = useLoad(() => listMxDecisions(gate, status), [gate, status, tick]);

  async function act(fn, id, payload) {
    setActionError(null);
    setNotice(null);
    try {
      const out = await fn(id, payload);
      setNotice(`${out.code} v${out.version} is now ${out.status}.`);
      setTick((t) => t + 1);
    } catch (e) {
      setActionError(e?.message || "The change was refused.");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className={card}>
        <h3 className="text-[14px] font-semibold text-foreground">Decision register</h3>
        <p className="mt-1 text-[12px] text-foreground-muted">
          Each open question from DECISIONS_PENDING.md, with its options and sources. A proposal is approved by a different Super Admin;
          an approved decision is immutable and changes no calculation by itself — it becomes a transcription ticket for the next Draft pack.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <select aria-label="Filter by gate" className={input} value={gate} onChange={(e) => setGate(e.target.value)}>
            <option value="">All gates</option>{GATES.map((g) => <option key={g}>{g}</option>)}
          </select>
          <select aria-label="Filter by status" className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      </div>
      <Messages error={error || actionError} />
      {notice && <p role="status" className="text-[12px] text-success">{notice}</p>}
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">No decision matches (the register is seeded with scripts/seed_mexico_decisions.py).</p>}
      <div className="flex flex-col gap-2" data-testid="mx-decisions">
        {(rows || []).map((d) => <Decision key={d.id} d={d} act={act} />)}
      </div>
    </div>
  );
}

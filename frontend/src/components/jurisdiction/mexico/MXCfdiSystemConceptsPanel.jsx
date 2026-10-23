import { useState } from "react";
import {
  approveMxSystemConcept, listMxSystemConcepts, proposeMxSystemConcept, withdrawMxSystemConcept,
} from "../../../service/superAdminService";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad } from "./mxShared";

// Phase 11a (D4): the SAT code of each amount the engine produces itself (ISR
// withheld, IMSS, INFONAVIT credit, the subsidy, special payments, the annual
// adjustment). One Super Admin proposes it — a code of the node's own catalog in
// that release, citing the S28 row or S4 page — and a different one approves.
const EMPTY = { conceptKey: "", nodeType: "", satCode: "", sourceRef: "" };

export default function MXCfdiSystemConceptsPanel({ releases }) {
  const [releaseId, setReleaseId] = useState("");
  const [data, error, , reload] = useLoad(() => listMxSystemConcepts(releaseId || undefined), [releaseId]);
  const { run, error: actError, notice, busy } = useAction(reload);
  const [form, setForm] = useState(EMPTY);
  const loaded = releases.filter((r) => r.entries > 0 && r.status !== "Superseded");
  return (
    <div className={card} data-testid="mx-cfdi-system-concepts">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">SAT codes for engine-produced amounts</h3>
      <p className="mb-2 text-[11px] text-foreground-muted">
        Each mapping is per release, cites its S28 catalog row or S4 guide page, and needs a second Super Admin.
      </p>
      <Messages error={error || actError} notice={notice} />
      <form className="mb-3 flex flex-wrap items-end gap-2" onSubmit={async (e) => {
        e.preventDefault();
        if (await run(() => proposeMxSystemConcept({ ...form, releaseId: Number(releaseId) }),
          "Proposed — a different Super Admin approves it.")) setForm(EMPTY);
      }}>
        <Field label="Release">
          <select required className={input} aria-label="Concept release" value={releaseId} onChange={(e) => setReleaseId(e.target.value)}>
            <option value="">Choose…</option>
            {loaded.map((r) => <option key={r.id} value={r.id}>#{r.id} {r.revision || ""} ({r.status})</option>)}
          </select>
        </Field>
        <Field label="Engine amount">
          <select required className={input} aria-label="Concept key" value={form.conceptKey} onChange={(e) => setForm({ ...form, conceptKey: e.target.value })}>
            <option value="">Choose…</option>
            {(data?.concepts || []).map((c) => <option key={c.key} value={c.key}>{c.key} — {c.label}</option>)}
          </select>
        </Field>
        <Field label="Node">
          <select required className={input} aria-label="Concept node" value={form.nodeType} onChange={(e) => setForm({ ...form, nodeType: e.target.value })}>
            <option value="">Choose…</option>
            {Object.entries(data?.nodeTypes || {}).map(([node, cat]) => <option key={node} value={node}>{node} ({cat})</option>)}
          </select>
        </Field>
        <Field label="SAT code"><input required className={input} aria-label="Concept SAT code" value={form.satCode} onChange={(e) => setForm({ ...form, satCode: e.target.value })} /></Field>
        <Field label="Source (S28 row / S4 page)"><input required className={input} aria-label="Concept source" value={form.sourceRef} onChange={(e) => setForm({ ...form, sourceRef: e.target.value })} /></Field>
        <button type="submit" className={btnPrimary} disabled={busy || !releaseId}>Propose</button>
      </form>
      <Table rows={data?.rows || []} empty="No mapping yet." columns={[
        { key: "releaseId", label: "Release", render: (r) => `#${r.releaseId}` },
        { key: "conceptKey", label: "Engine amount" }, { key: "nodeType", label: "Node" },
        { key: "satCode", label: "SAT code" }, { key: "sourceRef", label: "Source" }, { key: "status", label: "Status" },
        { key: "act", label: "", render: (r) => (r.status === "PROPOSED" ? (
          <span className="flex gap-2">
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => approveMxSystemConcept(r.id), "Approved.")}>Approve (another Super Admin)</button>
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => withdrawMxSystemConcept(r.id), "Withdrawn.")}>Withdraw</button>
          </span>
        ) : "") },
      ]} />
    </div>
  );
}

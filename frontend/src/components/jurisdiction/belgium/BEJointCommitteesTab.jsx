import { useState } from "react";
import { Plus } from "lucide-react";
import { useToast } from "../../../context/ToastContext";
import {
  listBeJointCommittees, setCollectiveAgreementStatus, upsertCollectiveAgreement,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { ErrorNote } from "../new_zealand/nzShared";
import { SE_CBA_TYPES } from "../sweden/seComponentConfig";

// Belgian Joint Committee / sub-committee CBA packs (D3) on the SHARED
// collective-agreement registry: created, edited and moved through the existing
// /compliance/collective-agreements routes (jurisdictionCountry "BE"), where
// the backend validates the code BE-PC-<committee>[-<sub>]-<version> and
// enforces four-eyes (the approver is never the author; the activator is never
// the approver). The committee / sub-committee shown are parsed by the BACKEND
// (/compliance/belgium/joint-committees) — the frontend never parses codes.

const NEXT = { Draft: ["In Review"], "In Review": ["Draft", "Approved"], Approved: ["Draft", "Active"] };

function AgreementForm({ onClose, onSaved }) {
  const [form, setForm] = useState({ agreementCode: "", name: "", agreementType: SE_CBA_TYPES[1], version: "1.0" });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (name) => (e) => setForm({ ...form, [name]: e.target.value });
  async function save() {
    setSaving(true);
    setError(null);
    try {
      await upsertCollectiveAgreement({ jurisdictionCountry: "BE", organizationId: null,
        agreementCode: form.agreementCode.trim(), name: form.name.trim(), agreementType: form.agreementType,
        version: form.version.trim() });
      onSaved();
    } catch (err) {
      setError(err.message || "The agreement was refused.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="mt-3 grid grid-cols-2 gap-3 rounded-lg border border-border p-3" data-testid="be-jc-form">
      <div><label className={labelClass} htmlFor="be-jc-code">Agreement code * (BE-PC-…)</label>
        <input id="be-jc-code" className={inputClass} value={form.agreementCode} onChange={set("agreementCode")} /></div>
      <div><label className={labelClass} htmlFor="be-jc-name">Name *</label>
        <input id="be-jc-name" className={inputClass} value={form.name} onChange={set("name")} /></div>
      <div><label className={labelClass} htmlFor="be-jc-type">Agreement type</label>
        <select id="be-jc-type" className={inputClass} value={form.agreementType} onChange={set("agreementType")}>
          {SE_CBA_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select></div>
      <div><label className={labelClass} htmlFor="be-jc-version">Version</label>
        <input id="be-jc-version" className={inputClass} value={form.version} onChange={set("version")} /></div>
      <div className="col-span-2"><ErrorNote message={error} /></div>
      <div className="col-span-2 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold">Cancel</button>
        <button type="button" onClick={save} disabled={saving || !form.agreementCode.trim() || !form.name.trim()}
          className="rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50">
          {saving ? "Saving…" : "Save Draft"}
        </button>
      </div>
    </div>
  );
}

export default function BEJointCommitteesTab() {
  const [rows, error, , reload] = useLoad(listBeJointCommittees);
  const [adding, setAdding] = useState(false);
  const [moveError, setMoveError] = useState(null);
  const { addToast } = useToast() || {};

  async function move(row, status) {
    setMoveError(null);
    try {
      await setCollectiveAgreementStatus(row.id, status, null);
      addToast?.(`${row.agreementCode} → ${status}.`, "success");
      reload();
    } catch (err) {
      setMoveError(err.message || "The move was refused.");
    }
  }

  return (
    <div className={card} data-testid="be-joint-committees">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[14px] font-semibold text-foreground">Joint Committees (sector CBA packs)</h3>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] font-semibold">
            <Plus size={11} /> New agreement
          </button>
        )}
      </div>
      <p className="mb-2 text-[12px] text-foreground-secondary">
        No sector fallback: an employee without a classified Joint Committee blocks (BE-020). Wage scales and modules
        are configured per agreement; employees link explicitly through their employment classification.
      </p>
      <ErrorNote message={error || moveError} />
      <Table rows={rows || []} empty="No Belgian Joint Committee packs yet."
        columns={[
          { label: "Code", render: (row) => <span className="font-mono">{row.agreementCode}</span> },
          { label: "Committee", render: (row) => row.jointCommittee || (row.codeValid ? "—" : <span className="text-error">invalid code</span>) },
          { label: "Sub-committee", render: (row) => row.subCommittee || "—" },
          { label: "Name", render: (row) => row.name },
          { label: "Status", render: (row) => row.status },
          { label: "", render: (row) => (
            <span className="inline-flex gap-1">
              {(NEXT[row.status] || []).map((status) => (
                <button key={status} type="button" onClick={() => move(row, status)}
                  className="rounded border border-border px-2 py-0.5 text-[11px] font-semibold">{status}</button>
              ))}
            </span>
          ) },
        ]} />
      {adding && <AgreementForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); }} />}
    </div>
  );
}

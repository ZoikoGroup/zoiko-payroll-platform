import { useState } from "react";
import { importNlTaxTable, listNlTaxTables, transitionNlTaxTable } from "../../../service/superAdminService";
import { Messages, Field, Table, card, btn, btnPrimary, input, useAction, useLoad } from "./nlShared";

// Official Belastingdienst wage-tax tables (gate G1). National authority
// data: imported -> validated -> approved -> active, with four-eyes (the
// importer cannot approve; the approver cannot activate).
const NEXT = { IMPORTED: ["validate"], VALIDATED: ["approve", "reject"], APPROVED: ["activate", "reject"] };

export default function NLTaxTablesTab({ pack }) {
  const [rows, loadError, , reload] = useLoad(() => listNlTaxTables(), []);
  const [file, setFile] = useState(null);
  const [meta, setMeta] = useState({ tax_year: new Date().getFullYear(), table_color: "WHITE", table_kind: "PERIOD", period: "MONTH", residence_variant: "NL", source_url: "" });
  const { run, error, notice, busy } = useAction(reload);
  const set = (k) => (e) => setMeta((m) => ({ ...m, [k]: e.target.value }));

  const upload = async (e) => {
    e.preventDefault();
    if (!pack?.id) return;
    const fields = { ...meta, jurisdiction_pack_id: pack.id, period: meta.table_kind === "PERIOD" ? meta.period : "" };
    if (await run(() => importNlTaxTable(file, fields), "File imported — validate it next.")) setFile(null);
  };
  const act = (r, action) => {
    let reason;
    if (action === "reject") {
      reason = window.prompt("Reason for rejecting this table file?");
      if (!reason) return;
    }
    run(() => transitionNlTaxTable(r.id, action, reason), `File ${action}d.`);
  };

  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <h3 className="mb-3 text-[14px] font-semibold text-foreground">Import an official table file (CSV)</h3>
        {!pack?.id ? <p className="text-[12px] text-foreground-muted">Select a Netherlands pack above first.</p> : (
          <form onSubmit={upload} className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="File"><input type="file" accept=".csv,.tsv,.txt" required className={input} onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
            <Field label="Tax year"><input type="number" required className={input} value={meta.tax_year} onChange={set("tax_year")} /></Field>
            <Field label="Colour"><select className={input} value={meta.table_color} onChange={set("table_color")}><option>WHITE</option><option>GREEN</option></select></Field>
            <Field label="Kind"><select className={input} value={meta.table_kind} onChange={set("table_kind")}><option>PERIOD</option><option>SPECIAL_REMUNERATION</option></select></Field>
            {meta.table_kind === "PERIOD" && (
              <Field label="Period"><select className={input} value={meta.period} onChange={set("period")}>
                {["DAY", "WEEK", "FOUR_WEEK", "MONTH", "QUARTER", "YEAR"].map((p) => <option key={p}>{p}</option>)}
              </select></Field>
            )}
            <Field label="Residence variant"><input required className={input} value={meta.residence_variant} onChange={set("residence_variant")} /></Field>
            <Field label="Source URL"><input className={input} value={meta.source_url} onChange={set("source_url")} /></Field>
            <div className="col-span-full"><button type="submit" className={btnPrimary} disabled={busy || !file}>Import</button></div>
          </form>
        )}
      </div>
      <div className={card}>
        <h3 className="mb-3 text-[14px] font-semibold text-foreground">Table files</h3>
        <Table rows={rows} columns={[
          { key: "tax_year", label: "Year" }, { key: "table_color", label: "Colour" }, { key: "table_kind", label: "Kind" },
          { key: "period", label: "Period" }, { key: "residence_variant", label: "Residence" }, { key: "row_count", label: "Rows" },
          { key: "file_sha256", label: "SHA-256", render: (r) => <code>{(r.file_sha256 || "").slice(0, 12)}…</code> },
          { key: "effective_from", label: "From" }, { key: "status", label: "Status" },
          { key: "actions", label: "", render: (r) => (
            <div className="flex gap-1">{(NEXT[r.status] || []).map((a) => (
              <button key={a} type="button" className={btn} disabled={busy} onClick={() => act(r, a)}>{a}</button>))}</div>) },
        ]} />
      </div>
    </div>
  );
}

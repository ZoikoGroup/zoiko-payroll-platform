import { useState } from "react";
import {
  addMxCfdiEntry, createMxCfdiRelease, listMxCfdiEntries, listMxCfdiReleases, transitionMxCfdiRelease,
} from "../../../service/superAdminService";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad } from "./mxShared";

// CFDI 4.0 + Complemento de Nómina 1.2 schema releases and SAT catalog
// entries (MX-015). Releases are Draft → In Review → Approved (four-eyes);
// pinning one live needs the Phase 7 PAC validation, so "Activate" is
// refused in Phase 2. Entries are frozen once a release leaves Draft.
export default function MXCfdiCatalogTab() {
  const [releases, loadError, , reload] = useLoad(() => listMxCfdiReleases(), []);
  const [selected, setSelected] = useState(null);
  const [entries, , , reloadEntries] = useLoad(() => (selected ? listMxCfdiEntries(selected) : Promise.resolve([])), [selected]);
  const { run, error, notice, busy } = useAction(() => { reload(); reloadEntries(); });
  const [release, setRelease] = useState({ cfdiVersion: "", complementVersion: "", catalogRelease: "" });
  const [entry, setEntry] = useState({ catalogName: "", code: "", description: "" });
  const current = (releases || []).find((r) => r.id === selected);
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Schema releases</h3>
        <p className="mb-3 text-[11px] text-foreground-muted">
          No SAT catalog is loaded until the Nómina 1.2 catalog workbook and nomina12.xsd (S28) are saved and verified.
        </p>
        <form className="mb-3 flex flex-wrap items-end gap-2" onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => createMxCfdiRelease(release), "Release registered (Draft).")) setRelease({ cfdiVersion: "", complementVersion: "", catalogRelease: "" });
        }}>
          <Field label="CFDI version"><input required className={input} value={release.cfdiVersion} onChange={(e) => setRelease({ ...release, cfdiVersion: e.target.value })} /></Field>
          <Field label="Complement version"><input required className={input} value={release.complementVersion} onChange={(e) => setRelease({ ...release, complementVersion: e.target.value })} /></Field>
          <Field label="Catalog release"><input className={input} value={release.catalogRelease} onChange={(e) => setRelease({ ...release, catalogRelease: e.target.value })} /></Field>
          <button type="submit" className={btnPrimary} disabled={busy}>Register release</button>
        </form>
        <Table rows={releases} empty="No schema release registered yet." columns={[
          { key: "id", label: "#" }, { key: "cfdiVersion", label: "CFDI" }, { key: "complementVersion", label: "Nómina" },
          { key: "catalogRelease", label: "Catalog release" }, { key: "entries", label: "Entries" }, { key: "status", label: "Status" },
          { key: "actions", label: "", render: (r) => (
            <span className="flex flex-wrap gap-1">
              <button type="button" className={btn} onClick={() => setSelected(r.id)}>Entries</button>
              {["submit", "approve", "activate"].map((a) => (
                <button key={a} type="button" className={btn} disabled={busy}
                        onClick={() => run(() => transitionMxCfdiRelease(r.id, a), `${a} done.`)}>{a}</button>
              ))}
            </span>
          ) },
        ]} />
      </div>
      {current && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Entries of release #{current.id} ({current.status})</h3>
          {current.status === "Draft" && (
            <form className="mb-3 flex flex-wrap items-end gap-2" onSubmit={async (e) => {
              e.preventDefault();
              if (await run(() => addMxCfdiEntry(current.id, entry), "Entry added.")) setEntry({ catalogName: "", code: "", description: "" });
            }}>
              <Field label="Catalog"><input required className={input} value={entry.catalogName} onChange={(e) => setEntry({ ...entry, catalogName: e.target.value })} /></Field>
              <Field label="Code"><input required className={input} value={entry.code} onChange={(e) => setEntry({ ...entry, code: e.target.value })} /></Field>
              <Field label="Description"><input required className={input} value={entry.description} onChange={(e) => setEntry({ ...entry, description: e.target.value })} /></Field>
              <button type="submit" className={btnPrimary} disabled={busy}>Add entry</button>
            </form>
          )}
          <Table rows={entries} empty="No entries." columns={[
            { key: "catalogName", label: "Catalog" }, { key: "code", label: "Code" }, { key: "description", label: "Description" },
            { key: "validFrom", label: "From" }, { key: "validTo", label: "To" },
          ]} />
        </div>
      )}
    </div>
  );
}

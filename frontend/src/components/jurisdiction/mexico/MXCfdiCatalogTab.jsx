import { useState } from "react";
import {
  addMxCfdiEntry, createMxCfdiRelease, listMxCfdiEntries, listMxCfdiReleases, listMxPinnedSets, loadMxPinnedSet,
  transitionMxCfdiRelease,
} from "../../../service/superAdminService";
import MXCfdiSystemConceptsPanel from "./MXCfdiSystemConceptsPanel";
import { Field, Messages, Table, btn, btnPrimary, card, input, useAction, useLoad } from "./mxShared";

// CFDI 4.0 + Complemento de Nómina 1.2 schema releases and SAT catalog
// entries (MX-015). Releases are Draft → In Review → Approved (four-eyes);
// pinning one live needs the PAC validation, so "Activate" is refused.
// Phase 11a: an empty Draft release is filled from a pinned SAT set (the SAT
// XSDs + catalogs saved from S28 / S30, checksum-verified) — never typed.
// Entries are frozen once a release leaves Draft.
function PinnedSets({ sets }) {
  return (
    <div className={card} data-testid="mx-pinned-sets">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">Pinned SAT sets</h3>
      <p className="mb-2 text-[11px] text-foreground-muted">
        The SAT schemas and catalogs saved from S28 (Nómina 1.2) and S30 (CFDI 4.0, Anexo 20), stored with their
        checksums. A set whose files no longer match cannot be loaded.
      </p>
      <Table rows={sets || []} rowKey={(s) => s.setId} empty="No pinned set is installed." columns={[
        { key: "setId", label: "Set" },
        { key: "versions", label: "CFDI / Nómina", render: (s) => `${s.cfdiVersion} / ${s.complementVersion}` },
        { key: "catalogRelease", label: "Catalog revision" },
        { key: "verified", label: "Files", render: (s) => (s.verified ? "Verified" : `Not usable: ${s.problems.join("; ")}`) },
        { key: "entries", label: "Catalog rows", render: (s) => Object.values(s.catalogCounts).reduce((a, b) => a + b, 0) },
        { key: "xsdChecksum", label: "XSD checksum", render: (s) => <span className="font-mono">{(s.xsdChecksum || "").slice(0, 12)}…</span> },
      ]} />
    </div>
  );
}

function Entries({ release, onChanged }) {
  const [catalog, setCatalog] = useState("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, , , reload] = useLoad(
    () => listMxCfdiEntries(release.id, { ...(catalog ? { catalog } : {}), ...(search ? { q: search } : {}) }),
    [release.id, catalog, search],
  );
  const { run, error, notice, busy } = useAction(() => { reload(); onChanged(); });
  const [entry, setEntry] = useState({ catalogName: "", code: "", description: "" });
  const counts = page?.counts || {};
  return (
    <div className={card} data-testid="mx-cfdi-entries">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Entries of release #{release.id} ({release.status})</h3>
      <Messages error={error} notice={notice} />
      {release.status === "Draft" && release.entries === 0 && (
        <p className="mb-2 text-[12px] text-foreground-muted">Empty — load a pinned SAT set (above, in the release row).</p>
      )}
      {release.status === "Draft" && (
        <form className="mb-3 flex flex-wrap items-end gap-2" onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => addMxCfdiEntry(release.id, entry), "Entry added.")) setEntry({ catalogName: "", code: "", description: "" });
        }}>
          <Field label="Catalog"><input required className={input} value={entry.catalogName} onChange={(e) => setEntry({ ...entry, catalogName: e.target.value })} /></Field>
          <Field label="Code"><input required className={input} value={entry.code} onChange={(e) => setEntry({ ...entry, code: e.target.value })} /></Field>
          <Field label="Description"><input required className={input} value={entry.description} onChange={(e) => setEntry({ ...entry, description: e.target.value })} /></Field>
          <button type="submit" className={btnPrimary} disabled={busy}>Add entry</button>
        </form>
      )}
      <div className="mb-2 flex flex-wrap items-end gap-2">
        <Field label="Catalog">
          <select className={input} aria-label="Catalog filter" value={catalog} onChange={(e) => setCatalog(e.target.value)}>
            <option value="">All catalogs</option>
            {Object.entries(counts).map(([name, n]) => <option key={name} value={name}>{name} ({n})</option>)}
          </select>
        </Field>
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); }}>
          <Field label="Code or description"><input className={input} aria-label="Catalog search" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
          <button type="submit" className={btn}>Search</button>
        </form>
      </div>
      {page && (
        <p className="mb-1 text-[11px] text-foreground-muted" data-testid="mx-cfdi-entries-total">
          {page.total} matching {page.total > page.entries.length ? `(first ${page.entries.length} shown)` : ""}
        </p>
      )}
      <Table rows={page?.entries || []} empty="No entries." columns={[
        { key: "catalogName", label: "Catalog" }, { key: "code", label: "Code" }, { key: "description", label: "Description" },
        { key: "validFrom", label: "From" }, { key: "validTo", label: "To" },
      ]} />
    </div>
  );
}

export default function MXCfdiCatalogTab() {
  const [releases, loadError, , reload] = useLoad(() => listMxCfdiReleases(), []);
  const [sets] = useLoad(() => listMxPinnedSets(), []);
  const [selected, setSelected] = useState(null);
  const { run, error, notice, busy } = useAction(reload);
  const [release, setRelease] = useState({ cfdiVersion: "", complementVersion: "", catalogRelease: "" });
  const current = (releases || []).find((r) => r.id === selected);
  const usable = (sets || []).filter((s) => s.verified);
  return (
    <div className="flex flex-col gap-4">
      <Messages error={loadError || error} notice={notice} />
      <PinnedSets sets={sets} />
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Schema releases</h3>
        <p className="mb-3 text-[11px] text-foreground-muted">
          Register a Draft release, load a pinned SAT set into it, submit, and a different Super Admin approves.
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
          { key: "revision", label: "Pinned set", render: (r) => r.revision || "—" },
          { key: "catalogRelease", label: "Catalog release" }, { key: "entries", label: "Entries" }, { key: "status", label: "Status" },
          { key: "actions", label: "", render: (r) => (
            <span className="flex flex-wrap gap-1">
              <button type="button" className={btn} onClick={() => setSelected(r.id)}>Entries</button>
              {r.status === "Draft" && r.entries === 0 && usable.map((s) => (
                <button key={s.setId} type="button" className={btn} disabled={busy}
                        onClick={() => run(() => loadMxPinnedSet(r.id, s.setId), `Loaded ${s.setId}.`)}>
                  Load {s.setId}
                </button>
              ))}
              {["submit", "approve", "activate"].map((a) => (
                <button key={a} type="button" className={btn} disabled={busy}
                        onClick={() => run(() => transitionMxCfdiRelease(r.id, a), `${a} done.`)}>{a}</button>
              ))}
            </span>
          ) },
        ]} />
      </div>
      {current && <Entries key={current.id} release={current} onChanged={reload} />}
      <MXCfdiSystemConceptsPanel releases={releases || []} />
    </div>
  );
}

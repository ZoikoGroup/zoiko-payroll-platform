import { useState } from "react";
import {
  compareMxConfigVersions, getMxConfigPack, getMxConfigVersions, newMxConfigVersion,
} from "../../../service/superAdminService";
import { Messages, Table, btn, btnPrimary, card, input, useLoad } from "./mxShared";

// Mexico statutory configuration versions (Hong Kong parity). Every version of
// the national pack and of each state ISN pack, one version's rows with their
// sources, a row-level compare, and "New version" — a Draft copy of the CHOSEN
// version, the rollback path. Rows are never edited here (W5-2): values change
// only through a code release that re-seeds the pack; a copy goes live only
// through four-eyes approval and the activation checks.
const STATE_TONE = {
  CURRENT_ACTIVE: "text-success", NEXT_ACTIVE: "text-success", PAST_ACTIVE: "text-foreground-muted",
  DRAFT: "text-warning", FUTURE_DRAFT: "text-warning", SUPERSEDED: "text-foreground-muted", RETIRED: "text-foreground-muted",
};

function valueText(v) {
  return Object.entries(v || {}).filter(([, x]) => x !== null && x !== undefined && x !== "")
    .map(([k, x]) => `${k} ${x}`).join(" · ") || "—";
}

function NewVersion({ v, onDone }) {
  const [form, setForm] = useState({ version: "", reason: "" });
  const [error, setError] = useState(null);
  async function submit(e) {
    e.preventDefault();
    setError(null);
    try {
      onDone(await newMxConfigVersion(v.id, form));
    } catch (err) {
      setError(err?.message || "The new version was refused.");
    }
  }
  return (
    <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={submit} aria-label={`New version from ${v.version}`}>
      <label className="text-[12px] text-foreground-secondary">New version
        <input aria-label="New version number" className={`${input} mt-1 w-28`} value={form.version}
               onChange={(e) => setForm({ ...form, version: e.target.value })} required />
      </label>
      <label className="text-[12px] text-foreground-secondary">Reason (rollback or change it starts)
        <input aria-label="New version reason" className={`${input} mt-1 w-80`} value={form.reason}
               onChange={(e) => setForm({ ...form, reason: e.target.value })} required />
      </label>
      <button type="submit" className={btnPrimary}>Create Draft copy of v{v.version}</button>
      {error && <p className="w-full text-[12px] text-error" role="alert">{error}</p>}
    </form>
  );
}

export default function MXConfigVersionsTab() {
  const [data, error, , reload] = useLoad(() => getMxConfigVersions(), []);
  const [rows, setRows] = useState(null);
  const [copyFrom, setCopyFrom] = useState(null);
  const [cmp, setCmp] = useState({ from: "", to: "" });
  const [diff, setDiff] = useState(null);
  const [notice, setNotice] = useState(null);
  const [actionError, setActionError] = useState(null);
  const all = (data?.packs || []).flatMap((g) => g.versions.map((v) => ({ ...v, packId: g.packId, state: g.state })));

  async function open(v) {
    setActionError(null);
    try { setRows(await getMxConfigPack(v.id)); } catch (e) { setActionError(e?.message || "Could not load the version."); }
  }
  async function compare() {
    setActionError(null); setDiff(null);
    try { setDiff(await compareMxConfigVersions(cmp.from, cmp.to)); } catch (e) { setActionError(e?.message || "Compare failed."); }
  }

  return (
    <div className="flex flex-col gap-4" data-testid="mx-config-versions">
      <div className={card}>
        <h3 className="text-[14px] font-semibold text-foreground">Configuration versions</h3>
        <p className="mt-1 text-[12px] text-foreground-muted">{data?.rule}</p>
        <Messages error={error || actionError} notice={notice} />
      </div>

      {(data?.packs || []).map((g) => (
        <div key={g.packId} className={card} data-testid={`mx-versions-${g.state || "national"}`}>
          <h4 className="mb-2 text-[13px] font-semibold text-foreground">{g.packId} {g.state ? `· ${g.state} ISN` : "· national"}</h4>
          <Table rows={g.versions} columns={[
            { key: "version", label: "Version", render: (v) => `v${v.version}` },
            { key: "versionState", label: "State", render: (v) => <span className={`font-semibold ${STATE_TONE[v.versionState] || ""}`}>{v.versionState}</span> },
            { key: "status", label: "Status" },
            { key: "effective", label: "In force", render: (v) => `${v.effectiveFrom || "—"} → ${v.effectiveTo || "open"}` },
            { key: "rows", label: "Rows (with source)", render: (v) => `${v.rows} (${v.rowsWithSource})` },
            { key: "approvedById", label: "Approved by", render: (v) => (v.approvedById ? `#${v.approvedById}` : "—") },
            { key: "changeSummary", label: "Change", render: (v) => v.changeSummary || "—" },
            { key: "act", label: "", render: (v) => (
              <span className="flex gap-2">
                <button type="button" className={btn} onClick={() => open(v)}>Rows</button>
                <button type="button" className={btn} onClick={() => setCopyFrom(copyFrom === v.id ? null : v.id)}>New version</button>
              </span>
            ) },
          ]} />
          {g.versions.filter((v) => v.id === copyFrom).map((v) => (
            <NewVersion key={v.id} v={v} onDone={(made) => {
              setCopyFrom(null);
              setNotice(`Created ${made.packId} v${made.version} (Draft, ${made.rows} rows copied from v${made.copiedFrom.version}).`);
              reload();
            }} />
          ))}
        </div>
      ))}

      <div className={card} data-testid="mx-config-compare">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Compare two versions</h3>
        <div className="flex flex-wrap gap-2">
          {["from", "to"].map((k) => (
            <select key={k} aria-label={`Compare versions ${k}`} className={input} value={cmp[k]}
                    onChange={(e) => setCmp((c) => ({ ...c, [k]: e.target.value }))}>
              <option value="">— {k} —</option>
              {all.map((v) => <option key={v.id} value={v.id}>{v.packId} v{v.version} ({v.status})</option>)}
            </select>
          ))}
          <button type="button" className={btn} disabled={!cmp.from || !cmp.to} onClick={compare}>Compare</button>
        </div>
        {diff && (
          <div className="mt-2 text-[12px] text-foreground" data-testid="mx-config-diff">
            <p>{diff.identical ? "Identical: every row, value, date and source matches."
              : `Changed ${diff.changed.length} · added ${diff.added.length} · removed ${diff.removed.length} · unchanged ${diff.unchanged}`}</p>
            {diff.changed.map((c) => (
              <p key={`${c.kind}${c.key}${c.label}`}>
                {c.key} — {Object.entries(c.changes).map(([f, ch]) => `${f}: ${ch.from ?? "—"} → ${ch.to ?? "—"}`).join("; ")}
              </p>
            ))}
            {diff.added.map((r) => <p key={`a${r.key}${r.effectiveFrom}`}>Added {r.key} ({r.effectiveFrom || "—"})</p>)}
            {diff.removed.map((r) => <p key={`r${r.key}${r.effectiveFrom}`}>Removed {r.key} ({r.effectiveFrom || "—"})</p>)}
          </div>
        )}
      </div>

      {rows && (
        <div className={card} data-testid="mx-config-rows">
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">
            {rows.pack.packId} v{rows.pack.version} — {rows.rates.length + rows.slabs.length} rows (read-only)
          </h3>
          <Table rows={[...rows.rates, ...rows.slabs]} rowKey={(r) => `${r.kind}${r.id}`} columns={[
            { key: "kind", label: "Kind" }, { key: "key", label: "Key" }, { key: "label", label: "Label" },
            { key: "value", label: "Value", render: (r) => valueText(r.value) },
            { key: "effective", label: "In force", render: (r) => (r.effectiveFrom || r.effectiveTo
              ? `${r.effectiveFrom || "—"} → ${r.effectiveTo || "open"}` : "pack window") },
            { key: "source", label: "Source", render: (r) => (r.source ? `#${r.source.id} ${(r.source.sha256 || "").slice(0, 10)}…` : "—") },
          ]} />
        </div>
      )}
    </div>
  );
}

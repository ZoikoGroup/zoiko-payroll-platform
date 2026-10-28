import { useState } from "react";
import { getMxTemplateVersions, newMxTemplateVersion } from "../../../service/superAdminService";
import { Messages, Table, btn, btnPrimary, card, input, useLoad } from "./mxShared";

// Mexico report-template versions: every version of every template with what
// the activation gate answers for it (gates SIGNED, content Active, fields
// proven) and its content hash; "New version" makes a Draft copy of the CHOSEN
// version — the rollback path (the shared lifecycle copies only the latest).
// Edit, approve and activate stay in the shared lifecycle above.
export default function MXTemplateVersionsPanel() {
  const [data, error, , reload] = useLoad(() => getMxTemplateVersions(), []);
  const [open, setOpen] = useState(null);
  const [form, setForm] = useState({ version: "", reason: "" });
  const [notice, setNotice] = useState(null);
  const [actionError, setActionError] = useState(null);

  async function submit(e, v) {
    e.preventDefault();
    setActionError(null);
    try {
      const made = await newMxTemplateVersion(v.id, form);
      setNotice(`Created ${made.templateKey} v${made.version} (Draft, copied from v${made.copiedFrom.version}).`);
      setOpen(null);
      setForm({ version: "", reason: "" });
      reload();
    } catch (err) {
      setActionError(err?.message || "The new version was refused.");
    }
  }

  return (
    <div className={card} data-testid="mx-template-versions">
      <h3 className="text-[14px] font-semibold text-foreground">Template versions</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        Every version with its activation-gate answer. &ldquo;New version&rdquo; copies the version you choose (fields included) as a
        Draft — the rollback path. Editing, approval (a Super Admin who made none of the edits) and activation stay in the
        lifecycle above.
      </p>
      <Messages error={error || actionError} notice={notice} />
      {(data || []).map((g) => (
        <div key={g.templateKey} className="mt-3" data-testid={`mx-template-versions-${g.templateKey}`}>
          <p className="text-[12px] font-semibold text-foreground">{g.templateKey} · {g.name}</p>
          <Table rows={g.versions} columns={[
            { key: "version", label: "Version", render: (v) => `v${v.version}` },
            { key: "status", label: "Status" },
            { key: "fields", label: "Fields" },
            { key: "contentHash", label: "Content hash", render: (v) => `${v.contentHash.slice(0, 12)}…` },
            { key: "activationRefusal", label: "Activation gate",
              render: (v) => (v.activationRefusal ? <span className="text-warning">{v.activationRefusal}</span> : <span className="text-success">would pass</span>) },
            { key: "changeSummary", label: "Change", render: (v) => v.changeSummary || "—" },
            { key: "act", label: "", render: (v) => (
              <button type="button" className={btn} onClick={() => setOpen(open === v.id ? null : v.id)}>New version</button>
            ) },
          ]} />
          {g.versions.filter((v) => v.id === open).map((v) => (
            <form key={v.id} className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => submit(e, v)}
                  aria-label={`New version of ${g.templateKey} from ${v.version}`}>
              <label className="text-[12px] text-foreground-secondary">New version
                <input aria-label="Template new version number" className={`${input} mt-1 w-28`} value={form.version}
                       onChange={(e) => setForm({ ...form, version: e.target.value })} required />
              </label>
              <label className="text-[12px] text-foreground-secondary">Reason
                <input aria-label="Template new version reason" className={`${input} mt-1 w-80`} value={form.reason}
                       onChange={(e) => setForm({ ...form, reason: e.target.value })} required />
              </label>
              <button type="submit" className={btnPrimary}>Create Draft copy of v{v.version}</button>
            </form>
          ))}
        </div>
      ))}
    </div>
  );
}

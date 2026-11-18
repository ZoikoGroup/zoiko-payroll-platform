import { useState } from "react";
import { getMxTemplateVersions, newMxTemplateVersion } from "../../../service/superAdminService";
import { Messages, Table, btn, btnPrimary, card, input, useLoad } from "./mxShared";
import { MXTemplateCompare } from "./MXTemplateLibraryPanel";

// Mexico report-template versions — the "Versions & gates" detail tab for the
// SELECTED template (rendered through ReportTemplateLayout's extraDetailTabs):
// each version with what the activation gate answers for it (gates SIGNED,
// content Active, fields proven) and its content hash; "New version" makes a
// Draft copy of the CHOSEN version — the rollback path (the shared lifecycle
// copies only the latest). Compare is limited to this template's versions.
// Edit, approve and activate stay in the shared lifecycle (status select +
// Approve above); the server still runs every gate.
export default function MXTemplateVersionsPanel({ detail, ctx }) {
  const [data, error, , reload] = useLoad(() => getMxTemplateVersions(), [detail]);
  const [open, setOpen] = useState(null);
  const [form, setForm] = useState({ version: "", reason: "" });
  const [notice, setNotice] = useState(null);
  const [created, setCreated] = useState(null);
  const [actionError, setActionError] = useState(null);
  const group = (data || []).find((g) => g.templateKey === detail.templateKey);

  async function submit(e, v) {
    e.preventDefault();
    setActionError(null);
    try {
      const made = await newMxTemplateVersion(v.id, form);
      setNotice(`Created ${made.templateKey} v${made.version} (Draft, copied from v${made.copiedFrom.version}).`);
      setCreated(made);
      setOpen(null);
      setForm({ version: "", reason: "" });
      reload();
      ctx?.reloadTemplates?.();
    } catch (err) {
      setActionError(err?.message || "The new version was refused.");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className={card} data-testid="mx-template-versions">
        <h3 className="text-[14px] font-semibold text-foreground">Versions &amp; gates</h3>
        <p className="mt-1 text-[12px] text-foreground-muted">
          Every version of {detail.templateKey} with its activation-gate answer. &ldquo;New version&rdquo; copies the version you
          choose (fields included) as a Draft — the rollback path. Editing, approval (a Super Admin who made none of the
          edits) and activation stay in the template lifecycle above.
        </p>
        <Messages error={error || actionError} notice={notice} />
        {created && ctx?.selectTemplate && (
          <button type="button" className={`${btn} mt-2`} onClick={() => ctx.selectTemplate(created.id)}>
            Open {created.templateKey} v{created.version}
          </button>
        )}
        {data && !group && <p className="mt-2 text-[12px] text-foreground-muted">This template is not in the Mexico library.</p>}
        {group && (
          <div className="mt-3" data-testid={`mx-template-versions-${group.templateKey}`}>
            <Table rows={group.versions} columns={[
              { key: "version", label: "Version", render: (v) => (v.id === detail.id ? <strong>v{v.version} (open)</strong> : `v${v.version}`) },
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
            {group.versions.filter((v) => v.id === open).map((v) => (
              <form key={v.id} className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => submit(e, v)}
                    aria-label={`New version of ${group.templateKey} from ${v.version}`}>
                <label className="text-[12px] text-foreground-secondary">New version
                  <input aria-label="Template new version number" className={`${input} mt-1 w-28`} value={form.version}
                         onChange={(e) => setForm({ ...form, version: e.target.value })} required />
                </label>
                <label className="text-[12px] text-foreground-secondary">Reason
                  <input aria-label="Template new version reason" className={`${input} mt-1 w-full sm:w-80`} value={form.reason}
                         onChange={(e) => setForm({ ...form, reason: e.target.value })} required />
                </label>
                <button type="submit" className={btnPrimary}>Create Draft copy of v{v.version}</button>
              </form>
            ))}
          </div>
        )}
      </div>
      {group && (
        <MXTemplateCompare
          key={`${detail.id}:${group.versions.length}`} defaultTo={detail.id}
          options={group.versions.map((v) => ({ ...v, templateKey: group.templateKey }))}
        />
      )}
    </div>
  );
}

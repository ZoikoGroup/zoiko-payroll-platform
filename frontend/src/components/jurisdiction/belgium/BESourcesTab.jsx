import { getSourceArtifacts } from "../../../service/superAdminService";
import { card, useLoad } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { ErrorNote } from "../new_zealand/nzShared";
import { reviewed } from "../new_zealand/nzForm";
import SourceEvidencePanel from "../SourceEvidencePanel";
import { loadConfiguration } from "./beShared";

// The Belgium evidence register (S1–S24, ZP-BE-ENG-001 §19) as seeded: a URL
// alone is NOT archived evidence. A source counts as archived only once a file
// with its checksum is stored and reviewed by a Super Admin other than its
// uploader. Uploading / reviewing uses the shared Source Evidence panel below.

export default function BESourcesTab({ pack }) {
  const [config] = useLoad(() => loadConfiguration(pack));
  const [sources, error] = useLoad(getSourceArtifacts);
  const prefix = config?.sourcePrefix;
  const rows = prefix ? (sources || []).filter((s) => String(s.formNumber || "").startsWith(prefix)) : [];
  return (
    <div className="space-y-4">
      <div className={card} data-testid="be-sources">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Belgium evidence register</h3>
        <ErrorNote message={error} />
        <Table rows={rows} empty={pack ? "No Belgian evidence registered yet (seed the Draft pack)." : "Select a Belgium pack."}
          columns={[
            { label: "Ref", render: (row) => <span className="font-mono">{String(row.formNumber).slice(prefix.length)}</span> },
            { label: "Authority", render: (row) => row.agency },
            { label: "Title", render: (row) => row.title },
            { label: "URL", render: (row) => (row.sourceUrl
              ? <a className="text-primary underline" href={row.sourceUrl} target="_blank" rel="noreferrer">open</a> : "—") },
            { label: "Archived", render: (row) => (reviewed(row)
              ? <span className="text-success">Archived and reviewed</span>
              : <span className="text-warning">Not archived</span>) },
          ]} />
      </div>
      <SourceEvidencePanel />
    </div>
  );
}

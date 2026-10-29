import { card, useLoad } from "./mxShared";
import { getMxCfdiValidations, getMxSaCfdiLifecycle } from "../../../service/superAdminService";

// Super Admin, read-only (Phase 7 §7): CFDI documents by status, UNKNOWN
// items, the pinned schema release, and why production cannot generate yet.
export default function MXCfdiLifecycleTab() {
  const [data, error] = useLoad(() => getMxSaCfdiLifecycle(), []);
  const [validations] = useLoad(() => getMxCfdiValidations(), []);
  if (error) return <p className="text-[12px] text-error" role="alert">{error}</p>;
  if (!data) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  const counts = Object.entries(data.counts || {});
  return (
    <div className="space-y-4" data-testid="mx-cfdi-lifecycle">
      <section className={card}>
        <h4 className="mb-2 text-[13px] font-bold text-foreground">CFDI lifecycle — all Mexican organisations</h4>
        <p className="text-[12px] text-foreground-muted">
          {data.total} document(s){counts.length ? ": " + counts.map(([k, v]) => `${k} ${v}`).join(" · ") : ""}.
          {" "}{data.unknownCount ?? data.unknown?.length ?? 0} UNKNOWN (awaiting a status query; the organization resolves them in its own workspace).
        </p>
        <p className="mt-1 text-[12px] text-foreground-muted">
          Schema release: {data.schemaRelease ? `CFDI ${data.schemaRelease.cfdiVersion} + Nómina ${data.schemaRelease.complementVersion} (${data.schemaRelease.status})` : "none Active"}
        </p>
      </section>
      <section className={card}>
        <h4 className="mb-2 text-[13px] font-bold text-foreground">Why no CFDI can be generated yet</h4>
        {data.blocked.length === 0 ? (
          <p className="text-[12px] text-foreground-muted">Nothing at platform level — builder, signer and PAC adapter are all configured here.</p>
        ) : (
          <ul className="space-y-1 text-[12px]">
            {data.blocked.map((b) => (
              <li key={b.code}><code className="text-[11px]">{b.code}</code> · {b.message}</li>
            ))}
          </ul>
        )}
      </section>
      <section className={card} data-testid="mx-cfdi-validations">
        <h4 className="mb-2 text-[13px] font-bold text-foreground">Validate-only previews (G1 evidence)</h4>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Run by organisation admins on committed runs: counts, refusal codes and payload hashes only — no worker data, no XML.
        </p>
        {!(validations || []).length ? <p className="text-[12px] text-foreground-muted">No preview yet.</p> : (
          <table className="w-full text-[12px]">
            <thead><tr className="text-left text-foreground-muted"><th className="py-1">When</th><th>Org</th><th>Run</th><th>Release</th><th>Valid</th><th>Refused</th><th>Codes</th></tr></thead>
            <tbody>
              {validations.map((v) => (
                <tr key={v.id} className="border-b border-border/50" data-testid="mx-cfdi-validation-row">
                  <td className="py-1">{v.at ? v.at.slice(0, 16).replace("T", " ") : "—"}</td><td>{v.organizationId}</td><td>#{v.runId}</td>
                  <td>#{v.releaseId} {v.setId}</td><td>{v.valid}/{v.payslips}</td><td>{v.refused}</td>
                  <td>{Object.entries(v.codes || {}).map(([k, n]) => `${k} ×${n}`).join(", ") || "—"}
                    {v.awaitingG1Decision ? " · awaiting a G1 decision" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

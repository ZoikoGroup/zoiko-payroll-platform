import { card, useLoad } from "./mxShared";
import { getMxSaCfdiLifecycle } from "../../../service/superAdminService";

// Super Admin, read-only (Phase 7 §7): CFDI documents by status, UNKNOWN
// items, the pinned schema release, and why production cannot generate yet.
export default function MXCfdiLifecycleTab() {
  const [data, error] = useLoad(() => getMxSaCfdiLifecycle(), []);
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
    </div>
  );
}

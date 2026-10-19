import { card, useLoad } from "./mxShared";
import { getMxSaAuthorities } from "../../../service/superAdminService";

// Super Admin, read-only (Phase 8 §7): movements, liabilities, SUA periods and
// ISN returns by status across Mexican organisations, and what is not built yet.
function line(obj) {
  const entries = Object.entries(obj || {});
  return entries.length ? entries.map(([k, v]) => `${k} ${v}`).join(" · ") : "none";
}

export default function MXAuthoritiesTab() {
  const [data, error] = useLoad(() => getMxSaAuthorities(), []);
  if (error) return <p className="text-[12px] text-error" role="alert">{error}</p>;
  if (!data) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return (
    <div className="space-y-4" data-testid="mx-authorities">
      <section className={card}>
        <h4 className="mb-2 text-[13px] font-bold text-foreground">Authorities — all Mexican organisations</h4>
        <dl className="grid grid-cols-2 gap-1 text-[12px]">
          <dt className="text-foreground-muted">IMSS movements</dt><dd>{line(data.movements)}</dd>
          <dt className="text-foreground-muted">Liabilities</dt><dd>{line(data.liabilities)}</dd>
          <dt className="text-foreground-muted">SUA periods</dt><dd>{line(data.suaPeriods)}</dd>
          <dt className="text-foreground-muted">ISN returns</dt><dd>{line(data.isnReturns)}</dd>
        </dl>
      </section>
      <section className={card}>
        <h4 className="mb-2 text-[13px] font-bold text-foreground">Not available yet</h4>
        <ul className="space-y-1 text-[12px]">
          {data.blocks.map((b) => <li key={b.code}><code className="text-[11px]">{b.code}</code> ({b.item}) · {b.message}</li>)}
        </ul>
      </section>
    </div>
  );
}

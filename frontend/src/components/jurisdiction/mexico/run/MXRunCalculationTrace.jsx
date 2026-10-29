// Mexico calculation trace drill-down (MX-007 / MX-063). Every figure is read
// from the payslip's frozen snapshot — nothing is recomputed in the browser.
// A blocked payslip shows its reasons instead (no figures exist for it).

function Section({ title, children }) {
  return (
    <div className="mb-3">
      <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{title}</p>
      {children}
    </div>
  );
}

function Rows({ rows }) {
  return (
    <table className="w-full text-[12px]">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k} className="border-b border-border/50">
            <td className="py-1 pr-3 text-foreground-muted">{k}</td>
            <td className="py-1 text-right tabular-nums text-foreground">{v ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function MXRunCalculationTrace({ snapshot }) {
  if (!snapshot) return null;
  if (snapshot.blocked) {
    return (
      <div className="mb-3 max-w-3xl rounded-[12px] border border-error/40 p-3 text-[12px]" data-testid="mx-trace-blocked">
        <p className="font-semibold text-error">Blocked — no figures were calculated</p>
        <ul className="mt-1 list-disc pl-5">
          {(snapshot.reasons || []).map((r, i) => (
            <li key={i}><code className="text-[11px]">{r.code}</code> · {r.message}</li>
          ))}
        </ul>
      </div>
    );
  }
  const r = snapshot.result || {};
  const sbc = r.sbc || {};
  const comp = sbc.components || {};
  return (
    <div className="mb-3 max-w-3xl rounded-[12px] border border-border p-3" data-testid="mx-trace">
      {snapshot.pilot && (
        <p className="mb-2 rounded-md border border-warning bg-warning/10 px-2 py-1 text-[12px] font-semibold text-foreground"
          data-testid="mx-trace-pilot" role="status">
          PILOT — parallel run. This payslip is non-binding: never paid, filed or stamped for real.
        </p>
      )}
      <p className="mb-2 text-[12px] text-foreground-muted">
        Pay date {r.pay_date} · {r.tariff_period} · {r.days_paid} salary day(s) · {r.contribution_days} contribution
        day(s) · pack {snapshot.pack?.pack_id} v{snapshot.pack?.version} · engine {r.engine_version} · rounding{" "}
        {r.rounding_rule}
      </p>
      <Section title="Perceptions">
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-foreground-muted">
            <th className="py-1">Code</th><th>Gross</th><th>ISR taxable</th><th>SBC</th><th>ISN</th><th>CFDI</th>
          </tr></thead>
          <tbody>
            {(r.concepts || []).map((c) => (
              <tr key={c.code} className="border-b border-border/50">
                <td className="py-1">{c.code}</td><td className="tabular-nums">{c.gross}</td>
                <td className="tabular-nums">{c.isr_taxable}</td><td>{c.sbc}</td><td>{c.isn ? "yes" : "no"}</td>
                <td>{c.cfdi_node}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="ISR and employment subsidy">
        <Rows rows={[
          ["Taxable base", r.isr_taxable],
          ["Bracket", r.isr_bracket ? `${r.isr_bracket.lower} – ${r.isr_bracket.upper ?? "∞"} · fixed ${r.isr_bracket.fixed} · ${r.isr_bracket.rate_pct}%` : "—"],
          ["ISR", r.isr],
          ["Subsidy", r.subsidy?.eligible ? r.subsidy?.amount : "not eligible"],
          ["ISR withheld", r.isr_withheld],
        ]} />
      </Section>
      {r.annual_adjustment && (
        <Section title={`Annual ISR adjustment ${r.annual_adjustment.fiscal_year} (MX-010 — the year's payslips are not edited)`}>
          <Rows rows={[
            ["Difference (annual ISR − withheld)", r.annual_adjustment.difference],
            ["Period ISR withheld before the adjustment", r.annual_adjustment.period_withheld],
            ["Applied in this payslip", r.annual_adjustment.change],
            ["Carried forward", r.annual_adjustment.carry_forward],
            ["Rule", r.annual_adjustment.rule_source],
          ]} />
        </Section>
      )}
      <Section title="SBC (contribution base — shown apart from pay, MX-037)">
        <Rows rows={[
          ["Daily salary", comp.daily_salary], ["Integration factor", comp.factor],
          ["Fixed part", comp.fixed], ["Variable part (daily)", comp.variable_daily],
          ...(sbc.segments || []).map((s) => [`SBC ${s.start} (${s.days} days, UMA ${s.uma_daily})`,
            `${s.sbc}${s.capped ? " (capped)" : ""}${s.floored ? " (floor)" : ""}`]),
        ]} />
      </Section>
      <Section title="IMSS branches">
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-foreground-muted"><th className="py-1">Branch</th><th>Side</th><th>Amount</th></tr></thead>
          <tbody>
            {(r.imss || []).map((b) => (
              <tr key={`${b.branch}-${b.side}`} className="border-b border-border/50">
                <td className="py-1">{b.branch}{b.lines?.[0]?.band ? ` · band ${b.lines[0].band}` : ""}</td>
                <td>{b.side}</td><td className="tabular-nums">{b.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="INFONAVIT, state ISN and totals">
        <Rows rows={[
          ["INFONAVIT employer", r.infonavit_employer], ["INFONAVIT credit (employee)", r.infonavit_credit],
          [`ISN ${r.isn?.state || ""}`, r.isn ? `${r.isn.base} × ${r.isn.rate_pct}% = ${r.isn.amount}` : "—"],
          ["Employee statutory deductions", r.employee_total], ["Employer cost", r.employer_total],
        ]} />
      </Section>
      <Section title="Content rows read">
        <p className="text-[11px] text-foreground-muted">
          {(r.content_rows || []).map((c) => `${c.key}=${c.value}`).join(" · ")}
        </p>
      </Section>
    </div>
  );
}

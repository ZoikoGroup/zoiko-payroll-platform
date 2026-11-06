import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Copy, Download, History, Loader2, X } from "lucide-react";
import {
  downloadMxPayHistory, downloadMxReciboDuplicate, downloadPayslip, getMxPayHistory, getMxRecibo,
} from "../../../service/payrollService";

// Recibo de nómina v2.0 (docs/mexico/MEXICO_RECIBO_REPORT.md): the on-screen
// Mexican payslip. Every figure, state and (masked) identifier comes from the
// server's recibo view — the same object the PDF is drawn from — so the
// screen and the PDF cannot disagree. Spanish first, English secondary.

const serif = { fontFamily: "Georgia, 'Times New Roman', serif" };

function Section({ title, children }) {
  return (
    <section className="mt-6">
      <h3 className="text-base font-bold text-foreground" style={serif}>{title}</h3>
      <div className="mb-3 mt-1 h-0.5 w-12 bg-category-teal" aria-hidden="true" />
      {children}
    </section>
  );
}

function Table({ head, rows, align, caption, totalRow = false, wide = false }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className={`w-full text-[13px] ${wide ? "min-w-[480px]" : ""}`}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="bg-brand-navy-deep text-left text-[11px] uppercase tracking-wide text-white">
            {head.map((h, i) => (
              <th key={h} scope="col" className={`px-3 py-2 font-semibold ${align[i] === "right" ? "text-right" : ""}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => {
            const last = totalRow && r === rows.length - 1;
            return (
              <tr key={r} className={last ? "bg-category-teal-light font-bold" : r % 2 ? "bg-surface-muted" : ""}>
                {row.map((cell, i) => (
                  <td key={i} className={`px-3 py-2 align-top text-foreground ${align[i] === "right" ? "text-right tabular-nums" : ""}`}>{cell}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MobileSummary({ s }) {
  // MX24-PAY-003: what a phone leads with — net, period, both statuses, key lines.
  return (
    <section role="region" aria-label="Resumen del recibo de nómina" className="mb-5 rounded-xl border border-border bg-category-teal-light p-4 sm:hidden">
      <p className="text-[11px] font-bold uppercase tracking-wide text-category-teal">Neto a pagar</p>
      <p className="text-2xl font-bold text-foreground" style={serif} aria-label={s.ariaLabel}>{s.net} {s.currency}</p>
      <p className="mt-1 text-[13px] text-foreground-secondary">{s.period}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-[13px]">
        <div><dt className="text-foreground-muted">CFDI</dt><dd className="font-semibold text-foreground">{s.fiscalStatus}</dd></div>
        <div><dt className="text-foreground-muted">Pago</dt><dd className="font-semibold text-foreground">{s.paymentStatus}</dd></div>
        <div><dt className="text-foreground-muted">Devengado</dt><dd className="tabular-nums text-foreground">{s.gross}</dd></div>
        <div><dt className="text-foreground-muted">Descuentos</dt><dd className="tabular-nums text-foreground">{s.deductions}</dd></div>
      </dl>
      {s.keyLines.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px]" aria-label="Deducciones principales">
          {s.keyLines.map((l) => (
            <li key={l.label} className="flex justify-between gap-3"><span className="text-foreground-secondary">{l.label}</span><span className="tabular-nums text-foreground">{l.amount}</span></li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PayHistory({ employeeId, payDate }) {
  const year = (payDate || "").slice(0, 4) || String(new Date().getFullYear());
  const [start, setStart] = useState(`${year}-01-01`);
  const [end, setEnd] = useState(`${year}-12-31`);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true);
    setError(null);
    try { setData(await getMxPayHistory(employeeId, start, end)); } catch (e) { setError(e?.message || "No se pudo cargar el historial"); }
    setBusy(false);
  };
  return (
    <Section title="Historial de pagos / Pay history">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[12px] text-foreground-secondary">Desde
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 block rounded-lg border border-border bg-surface px-2 py-1.5 text-[13px] text-foreground" />
        </label>
        <label className="text-[12px] text-foreground-secondary">Hasta
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1 block rounded-lg border border-border bg-surface px-2 py-1.5 text-[13px] text-foreground" />
        </label>
        <button type="button" onClick={load} disabled={busy} className="rounded-lg bg-primary px-3 py-2 text-[13px] font-semibold text-white disabled:opacity-60">
          {busy ? "Cargando…" : "Consultar"}
        </button>
        {data && (
          <button type="button" onClick={() => downloadMxPayHistory(employeeId, start, end)} className="rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-foreground">
            Descargar PDF
          </button>
        )}
      </div>
      {error && <p role="alert" className="mt-2 text-[13px] text-error">{error}</p>}
      {data && (
        <div className="mt-3">
          <Table wide caption="Historial de pagos" head={["Periodo", "Tipo", "Devengado", "Descuentos", "Neto", "CFDI", "Pago"]}
            align={["left", "left", "right", "right", "right", "left", "left"]}
            rows={data.rows.length ? data.rows.map((r) => [r.period, r.type, r.gross, r.deductions, r.net, r.cfdi, r.payment])
              : [["Sin recibos en el rango", "", "", "", "", "", ""]]} />
          <p className="mt-1 text-[11px] text-foreground-muted">Extracto informativo · no es un CFDI.</p>
        </div>
      )}
    </Section>
  );
}

export default function MexicoRecibo({ payslip, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMxRecibo(payslip.id)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e?.message || "No se pudo cargar el recibo"); });
    return () => { cancelled = true; };
  }, [payslip.id]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  const v = data?.view;
  const ribbonTone = v?.fiscal.state === "CANCELLED" ? "border-error bg-error-light" : "border-category-teal bg-category-teal-light";

  return createPortal(
    <>
      <div className="fixed inset-0 z-[9998] bg-background/40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-[9999] flex items-center justify-center p-2 sm:p-4" role="dialog" aria-modal="true" aria-label="Recibo de nómina">
        <div className="relative max-h-[94vh] w-full max-w-4xl overflow-auto rounded-[18px] bg-surface shadow-[0_24px_48px_rgba(0,0,0,0.15)]">
          <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface/95 px-4 py-3 backdrop-blur sm:px-6">
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => downloadPayslip(payslip)} disabled={!v}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[13px] font-semibold text-white disabled:opacity-60">
                <Download size={14} /> PDF
              </button>
              <button type="button" onClick={() => downloadMxReciboDuplicate(payslip.id)} disabled={!v}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[13px] font-semibold text-foreground disabled:opacity-60">
                <Copy size={14} /> Duplicado
              </button>
              <button type="button" onClick={() => setShowHistory((x) => !x)} disabled={!v} aria-expanded={showHistory}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[13px] font-semibold text-foreground disabled:opacity-60">
                <History size={14} /> Historial
              </button>
            </div>
            <button type="button" onClick={onClose} aria-label="Cerrar" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
              <X size={18} />
            </button>
          </div>

          <div className="px-4 py-5 sm:px-8 sm:py-6">
            {!v && !error && (
              <p className="flex items-center gap-2 text-[13px] text-foreground-muted"><Loader2 size={14} className="animate-spin" /> Cargando recibo…</p>
            )}
            {error && <p role="alert" className="rounded-lg border border-error/30 bg-error-light p-3 text-[13px] text-error">{error}</p>}
            {v && (
              <article aria-label={v.title}>
                <MobileSummary s={data.summary} />
                <p className="text-right text-[10px] font-bold uppercase tracking-[0.18em] text-category-teal">ZOIKO PAYROLL / GLOBAL DOCUMENT ENGINE / MX–24</p>
                <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
                  <p className="flex items-baseline gap-2">
                    <span className="text-3xl font-bold text-brand-navy dark:text-foreground" style={serif}>zoiko</span>
                    <span className="text-[13px] font-bold tracking-[0.2em] text-category-teal">PAYROLL</span>
                  </p>
                  {v.duplicate && <span className="text-lg font-bold tracking-widest text-warning">DUPLICADO</span>}
                </div>
                <p className="mt-1 text-[11px] font-bold tracking-[0.15em] text-category-teal">COUNTRY PACK 24 / MÉXICO / MXN</p>
                <h2 className="mt-4 text-2xl font-bold text-foreground sm:text-3xl" style={serif}>{v.title}</h2>
                <p className="mt-1 text-[13px] text-foreground-muted">{v.subtitle}</p>
                <p className={`mt-3 border-l-4 px-3 py-2 text-[12px] font-bold text-foreground ${ribbonTone}`} role="status">{v.ribbon}</p>

                <Section title="Datos del patrón y del trabajador / Parties">
                  <Table caption="Emisor y receptor" head={["Emisor / Employer", "Receptor / Employee"]} align={["left", "left"]} rows={[
                    [v.parties.employer.name || "—", v.parties.employee.name || "—"],
                    [`RFC: ${v.parties.employer.rfc || "—"} · Registro patronal: ${v.parties.employer.registroPatronal || "—"}`,
                      `RFC: ${v.parties.employee.rfc || "—"} · CURP: ${v.parties.employee.curp || "—"}`],
                    [`${v.parties.employer.state || "—"} · C.P. ${v.parties.employer.postalCode || "—"}`,
                      `Empleado: ${v.parties.employee.employeeCode || "—"} · NSS: ${v.parties.employee.nss || "—"}`],
                    [`Régimen fiscal: ${v.parties.employer.fiscalRegime || "—"}`, `Régimen fiscal receptor: ${v.parties.employee.fiscalRegime || "—"}`],
                  ]} />
                  <div className="mt-3">
                    <Table caption="Nómina, fechas y estado fiscal" head={["Nómina / Periodo", "Fecha / Pago", "Fiscal"]} align={["left", "left", "left"]}
                      rows={[[`${v.payroll.type} · ${v.payroll.periodicity}`, v.payroll.period, `CFDI: ${v.fiscal.label}`]]} />
                  </div>
                </Section>

                <Section title="Percepciones / Earnings">
                  <Table wide caption="Percepciones" head={["Clave / Concepto", "Gravado MXN", "Exento MXN", "Total MXN"]} align={["left", "right", "right", "right"]} totalRow
                    rows={[...v.perceptions.map((l) => [`${l.satCode || "clave pendiente"} · ${l.concept}`, l.taxed, l.exempt, l.total]),
                      ["TOTAL PERCEPCIONES", v.perceptionTotals.taxed, v.perceptionTotals.exempt, v.perceptionTotals.total]]} />
                </Section>

                {v.otherPayments.length > 0 && (
                  <Section title="Otros pagos / Other payments">
                    <Table wide caption="Otros pagos" head={["Clave / Concepto", "Importe (MXN)", "Nota"]} align={["left", "right", "left"]}
                      rows={v.otherPayments.map((o) => [`${o.satCode || "clave pendiente"} · ${o.concept}`, o.amount, o.note || ""])} />
                  </Section>
                )}

                <Section title="Deducciones / Employee deductions">
                  <Table wide caption="Deducciones del trabajador" head={["Concepto", "Importe (MXN)", "Base / Justificante"]} align={["left", "right", "left"]} totalRow
                    rows={[...v.deductions.map((l) => [l.concept, l.amount, l.basis]), ["TOTAL DEDUCCIONES", v.totals.deductions, ""]]} />
                </Section>

                <Section title="Resumen / Totals">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    {[["Total devengado", v.totals.gross, false], ["Descuentos del trabajador", v.totals.deductions, false], ["Neto a pagar", v.totals.net, true]].map(([label, value, strong]) => (
                      <div key={label} className={`rounded-lg p-3 ${strong ? "bg-brand-navy-deep text-white" : "bg-category-teal-light text-foreground"}`}>
                        <p className={`text-[11px] font-bold uppercase tracking-wide ${strong ? "text-white/80" : "text-category-teal"}`}>{label}</p>
                        <p className="mt-1 text-right text-xl font-bold tabular-nums" style={serif}>{value} MXN</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 rounded-lg bg-category-teal-light p-3 text-[13px] text-foreground">
                    <p>{v.employer.note}</p>
                    <dl className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                      {[["Cuotas patronales IMSS", v.employer.imss], ["Aportación patronal INFONAVIT", v.employer.infonavit],
                        ["Impuesto sobre nómina estatal", v.employer.isn], ["Total costo patronal", v.employer.total]].map(([k, val]) => (
                        <div key={k} className="flex justify-between gap-3"><dt className="text-foreground-secondary">{k} (informativo)</dt><dd className="whitespace-nowrap font-semibold tabular-nums">{val} MXN</dd></div>
                      ))}
                    </dl>
                  </div>
                </Section>

                <Section title="Timbre fiscal / SAT status">
                  <Table caption="Timbre fiscal" head={["Concepto", "Valor"]} align={["left", "left"]} rows={[
                    ["Folio fiscal (UUID)", v.fiscal.sat.uuid], ["Timbre SAT", v.fiscal.sat.stamp], ["Sello SAT", v.fiscal.sat.seal],
                    ["XML/QR", v.fiscal.sat.xmlQr], ["Estado de pago", `Pago: ${v.payment.label}`],
                  ]} />
                </Section>

                {showHistory && <PayHistory employeeId={v.employeeId} payDate={v.payroll.payDate} />}

                <footer className="mt-6 flex flex-wrap justify-between gap-2 border-t border-border pt-3 text-[11px] text-foreground-muted">
                  <span className="font-semibold tracking-wide">{v.footer.confidential} · {v.footer.documentState} · {v.footer.issueDate}</span>
                  <span>{v.documentCode} · {v.rendererVersion} · snapshot {v.footer.snapshotHash}</span>
                </footer>
              </article>
            )}
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}

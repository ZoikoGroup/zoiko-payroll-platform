// Brazil (ZP-BR-ENG-001 Phase 6) — Payslip line helpers.
// Pure, ORM-free, matches the flat br_* columns on PayslipItem and the
// frozen br_calculation_snapshot (br_result) returned by the engine.

export const BR_LABELS = {
  // Employee statutory
  br_inss_employee: "INSS — Employee (8–14%)",
  br_irrf: "IRRF — Withholding Tax",
  br_irrf_reduction: "IRRF — 2026 Reduction (Lei 15.270)",
  br_vale_transporte_deduction: "Vale-Transporte — 6% Cap",
  br_salario_familia: "Salário-Família (net addition)",
  br_alimony_deduction: "Alimony — Court Order",

  // Bases (informational)
  br_base_inss: "Base — INSS",
  br_base_irrf: "Base — IRRF",
  br_base_fgts: "Base — FGTS",

  // Employer charges
  br_fgts_deposit: "FGTS — Employer Deposit (8%/2%)",
  br_cpp_employer: "CPP — Employer (20% / 10% CPRB)",
  br_rat_adjusted: "RAT × FAP — Employer",
  br_third_parties: "Third Parties — Employer (5.8%)",

  // Engine trace
  br_result: "Engine Result (trace, contentHash, bases, employer)",
};

export const BR_EARNING_LABELS = {
  BR_SALARIO_BASE: "Salário Base",
  BR_HORA_EXTRA_50: "Hora Extra 50%",
  BR_HORA_EXTRA_100: "Hora Extra 100%",
  BR_ADIC_NOTURNO: "Adicional Noturno 20%",
  BR_DSR: "DSR (Descanso Semanal Remunerado)",
  BR_SAL_FAMILIA: "Salário-Família",
  BR_13_ADIANT: "13º Salário — 1ª Parcela",
  BR_13_FINAL: "13º Salário — 2ª Parcela",
  BR_FERIAS_GOZO: "Férias Gozadas",
  BR_FERIAS_TERCO: "1/3 Constitucional de Férias",
};

export const BR_DEDUCTION_LABELS = {
  BR_INSS_EMP: "INSS Empregado",
  BR_IRRF: "IRRF Retido na Fonte",
  BR_DESC_VT: "Desconto Vale-Transporte",
  BR_PENSAO_ALIM: "Pensão Alimentícia Judicial",
};

export function formatBRL(value) {
  if (value == null) return "—";
  const n = Number(value);
  if (isNaN(n)) return String(value);
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(n);
}

export function getBrEarningsLines(item) {
  const lines = [];
  if (item.allowanceItems) {
    for (const a of item.allowanceItems) {
      const label = BR_EARNING_LABELS[a.key] || a.label || a.key;
      if (Number(a.amount) > 0) {
        lines.push({ label, amount: formatBRL(a.amount), isEarning: true });
      }
    }
  }
  // Add standard earnings from item if present
  for (const [key, label] of Object.entries(BR_EARNING_LABELS)) {
    const val = item[key] || item[key.toLowerCase()];
    if (val && Number(val) > 0) {
      // Check if already added from allowanceItems
      if (!lines.some(l => l.label === label)) {
        lines.push({ label, amount: formatBRL(val), isEarning: true });
      }
    }
  }
  return lines;
}

export function getBrDeductionsLines(item) {
  const lines = [];
  for (const [key, label] of Object.entries(BR_DEDUCTION_LABELS)) {
    const val = item[key] || item[key.toLowerCase()];
    if (val && Number(val) > 0) {
      lines.push({ label, amount: formatBRL(val), isEarning: false });
    }
  }
  // Standard statutory deductions
  if (item.br_inss_employee && Number(item.br_inss_employee) > 0) {
    lines.push({ label: BR_LABELS.br_inss_employee, amount: formatBRL(item.br_inss_employee), isEarning: false });
  }
  if (item.br_irrf && Number(item.br_irrf) > 0) {
    lines.push({ label: BR_LABELS.br_irrf, amount: formatBRL(item.br_irrf), isEarning: false });
  }
  if (item.br_vale_transporte_deduction && Number(item.br_vale_transporte_deduction) > 0) {
    lines.push({ label: BR_LABELS.br_vale_transporte_deduction, amount: formatBRL(item.br_vale_transporte_deduction), isEarning: false });
  }
  if (item.br_alimony_deduction && Number(item.br_alimony_deduction) > 0) {
    lines.push({ label: BR_LABELS.br_alimony_deduction, amount: formatBRL(item.br_alimony_deduction), isEarning: false });
  }
  return lines;
}

export function getBrEmployerLines(item) {
  const lines = [];
  if (item.br_cpp_employer && Number(item.br_cpp_employer) > 0) {
    lines.push({ label: BR_LABELS.br_cpp_employer, amount: formatBRL(item.br_cpp_employer) });
  }
  if (item.br_rat_adjusted && Number(item.br_rat_adjusted) > 0) {
    lines.push({ label: BR_LABELS.br_rat_adjusted, amount: formatBRL(item.br_rat_adjusted) });
  }
  if (item.br_third_parties && Number(item.br_third_parties) > 0) {
    lines.push({ label: BR_LABELS.br_third_parties, amount: formatBRL(item.br_third_parties) });
  }
  if (item.br_fgts_deposit && Number(item.br_fgts_deposit) > 0) {
    lines.push({ label: BR_LABELS.br_fgts_deposit, amount: formatBRL(item.br_fgts_deposit) });
  }
  return lines;
}

export function getBrBasesLines(item) {
  const lines = [];
  if (item.br_base_inss != null) lines.push({ label: BR_LABELS.br_base_inss, amount: formatBRL(item.br_base_inss) });
  if (item.br_base_irrf != null) lines.push({ label: BR_LABELS.br_base_irrf, amount: formatBRL(item.br_base_irrf) });
  if (item.br_base_fgts != null) lines.push({ label: BR_LABELS.br_base_fgts, amount: formatBRL(item.br_base_fgts) });
  return lines;
}

export function getBrTrace(snapshot) {
  if (!snapshot) return null;
  const trace = snapshot.trace;
  if (!trace) return null;
  return {
    spec: trace.spec,
    engineVersion: trace.engineVersion,
    competenceMonth: trace.competenceMonth,
    contentHash: trace.contentHash,
    inputsHash: trace.inputsHash,
    blocked: trace.blocked,
    blockKey: trace.blockKey,
    profileHash: trace.profileHash,
    establishmentHash: trace.establishmentHash,
    employerHash: trace.employerHash,
    bases: trace.bases,
    earnings: trace.earnings,
    steps: trace.steps,
  };
}
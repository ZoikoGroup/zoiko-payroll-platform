// Plain-language notices for the selected Mexico report template, from the
// server's library row (coverage: kind, fields, fieldProof) and the template
// detail (status, approver). Presentation only: the activation gate, the
// payslip field proof and maker-checker stay server-side.

const RELEASED = ["Published", "Active", "Superseded"];

// Components tab: what this template is built from and, when a snapshot-field
// template has no fields, why and how it gets them.
export function componentsNotice(row, detail) {
  if (!row) return null;
  if (row.kind === "DEDICATED") {
    return {
      tone: "info", title: "Built by a dedicated generator: no components",
      body: `${row.templateKey} is produced by Mexico's own report generator from its service views, so there are no `
        + "components or fields to configure here. Its activation gate checks the report's release gates and Active "
        + "content, not fields.",
    };
  }
  if (row.kind === "RECEIPT") {
    return {
      tone: "info", title: "CFDI receipt: no components",
      body: "The printed receipt is rendered on demand from the stored stamped CFDI XML, so there are no components or "
        + "fields to configure here.",
    };
  }
  if (row.fields > 0) {
    return {
      tone: "ok", title: `Snapshot fields: ${row.fields} field${row.fields === 1 ? "" : "s"}`,
      body: `Each field reads the frozen Mexico calculation. Field check: ${row.fieldProof}.`,
    };
  }
  const status = detail?.status || row.status;
  const seed = "the report-template seed (scripts/seed_statutory_report_templates.py, an engineering step)";
  let body;
  if (status === "Draft") {
    body = `Its field set is written by ${seed}, which refreshes a Draft template. Re-run the seed, or add components `
      + "below from this report type's own list.";
  } else if (RELEASED.includes(status)) {
    body = "A released version is never edited in place: make a new version (Versions & gates), then fill the Draft copy.";
  } else {
    body = `Its field set is written by ${seed}, but the seed only refreshes a Draft template. This one is ${status}, so `
      + `it was skipped and still holds an early empty shell. Set the status back to Draft (allowed from ${status}), `
      + "then re-run the seed.";
  }
  return { tone: "warning", title: "No fields yet: activation refuses this template (\"the template has no fields\")", body };
}

// Overview: who approved it. "Approved" is a lifecycle status; the approver is
// recorded separately by "Approve", and Publish needs one (maker-checker).
export function approverNote(detail) {
  if (!detail) return null;
  if (detail.approvedById) return { tone: "ok", text: `Approved by user #${detail.approvedById}` };
  if (detail.status === "Approved") {
    return {
      tone: "warning",
      text: "Status is Approved, but no approver is recorded. Publishing needs \"Approve\" by a Super Admin other than "
        + "the last editor (maker-checker).",
    };
  }
  return { tone: "muted", text: "No approver recorded" };
}

// "G2 IMSS / SUA: OPEN" for each of the template's gates; the area and state
// come from the readiness view (null while it loads or if it is unavailable).
export function gateLines(gates, readinessGates) {
  const byKey = Object.fromEntries((readinessGates || []).map((g) => [g.gate, g]));
  return (gates || []).map((g) => {
    const r = byKey[g];
    return { gate: g, label: r?.label || null, state: r?.state || null, signed: r?.state === "SIGNED" };
  });
}

// Belgium (ZP-BE-ENG-001 Block A4) capture-form payload shapers. Shape only:
// the server validates every value and never trusts these.

// A declaration's structured value: the form sends `count` / `note` flat; they
// are folded into `value` (a blank count is never sent).
export function declarationPayload(values) {
  const out = { ...values };
  const value = {};
  if (out.count !== undefined && out.count !== "") value.count = Number(out.count);
  if (out.note) value.note = out.note;
  delete out.count;
  delete out.note;
  out.value = value;
  return out;
}

// Mandates are typed as a comma-separated list of REFERENCES (never secrets).
export function registrationPayload(values) {
  const out = { ...values };
  if (typeof out.mandate_refs === "string") {
    const refs = out.mandate_refs.split(",").map((s) => s.trim()).filter(Boolean);
    if (refs.length) out.mandate_refs = refs;
    else delete out.mandate_refs;
  }
  return out;
}

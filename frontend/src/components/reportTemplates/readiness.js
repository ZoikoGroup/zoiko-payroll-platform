// How a report template's activation readiness reads in the UI. Plain JS (no
// JSX) so scripts/report-template-ui-validation.mjs can evaluate it under Node.
//
// Every rule lives in the backend: `activationReadiness` is a dry run of the
// status change's own checks (service.report_template_activation_readiness),
// computed for the signed-in Super Admin. Detail responses carry the full
// object; list responses carry only `countryGate` (`partial: true`). Nothing
// here decides whether a template may be activated — the status change still
// refuses — it only presents what the backend said, before the click.
//
//   activationReadiness = {
//     canActivate, blockedReason, blockerKind, gate,   // first check the real change would refuse
//     countryGate: { allowed, message, blockerKind, gate },
//     deferredChecks: [string], nextStatuses: [status],
//   }
// blockerKind: transition | four_eyes | jurisdiction_gate | not_built | conflict | unknown_status

export const NOT_BUILT = "not_built";
export const JURISDICTION_GATE = "jurisdiction_gate";

const readinessOf = (template) => template?.activationReadiness || null;

// The country's own gate when it blocks (the hard blocker: evidence, schemas,
// certification, or nothing built yet) — null when there is none.
export function countryBlock(template) {
  const gate = readinessOf(template)?.countryGate;
  if (!gate || gate.allowed) return null;
  if (gate.blockerKind !== JURISDICTION_GATE && gate.blockerKind !== NOT_BUILT) return null;
  return gate;
}

// Small badge beside the status pill in the template list (and the detail
// header): "Not built" / "Blocked" with the backend's reason as its tooltip.
export function listBadge(template) {
  if (!template || template.status === "Active" || template.status === "Superseded") return null;
  const gate = countryBlock(template);
  if (!gate) return null;
  return gate.blockerKind === NOT_BUILT
    ? { key: "not-built", label: "Not built", title: gate.message }
    : { key: "blocked", label: gate.gate ? `Blocked · ${gate.gate}` : "Blocked", title: gate.message };
}

// The statement shown instead of a bare status when nothing can be activated
// because the country's report engine is not built.
export function availabilityLabel(template) {
  const gate = countryBlock(template);
  return gate && gate.blockerKind === NOT_BUILT && template.status !== "Active" ? "Not available — engine not built" : null;
}

// The status dropdown: the current status, then every other status — enabled
// only when the backend's lifecycle allows the move (nextStatuses), and Active
// only when the dry run says it would be accepted. `reason` is why an option is
// disabled. Without readiness (an older response) every option stays enabled,
// as before; the server refuses what it must.
export function statusOptions(statuses, template) {
  const ready = readinessOf(template);
  const full = ready && !ready.partial && Array.isArray(ready.nextStatuses);
  return statuses.map((value) => {
    if (!template || value === template.status || !full) return { value, disabled: false, reason: null };
    // Active first: the dry run's own message (transition, four-eyes, gate, slot).
    if (value === "Active" && !ready.canActivate) {
      return { value, disabled: true, reason: ready.blockedReason || "Cannot be activated yet." };
    }
    if (!ready.nextStatuses.includes(value)) {
      return { value, disabled: true, reason: `Not allowed from ${template.status}.` };
    }
    return { value, disabled: false, reason: null };
  });
}

// Why "Active" is unavailable right now (text shown beside the dropdown — a
// native <option> tooltip is not reliable), or null.
export function activeOptionReason(statuses, template) {
  return statusOptions(statuses, template).find((o) => o.value === "Active" && o.disabled)?.reason || null;
}

// The detail banner: shown when the country gate blocks (whatever the status),
// or when a Published template — the one step before Active — cannot be
// activated for any other reason. { tone, title, message, deferred, linkToReadiness }.
export function activationBanner(template) {
  const ready = readinessOf(template);
  if (!template || !ready || ready.partial || template.status === "Active" || template.status === "Superseded") return null;
  const gate = countryBlock(template);
  const deferred = Array.isArray(ready.deferredChecks) ? ready.deferredChecks : [];
  if (gate) {
    return {
      tone: "error",
      title: gate.blockerKind === NOT_BUILT ? "Not available — engine not built" : "Cannot activate yet",
      message: gate.message, gate: gate.gate || null, deferred,
      // A named release gate is tracked on the country's compliance page.
      linkToReadiness: Boolean(gate.gate),
    };
  }
  if (template.status === "Published" && !ready.canActivate) {
    return { tone: "warning", title: "Cannot activate yet", message: ready.blockedReason, gate: ready.gate || null,
      deferred, linkToReadiness: false };
  }
  if (template.status === "Published" && deferred.length) {
    return { tone: "info", title: "Checked when activating", message: null, gate: null, deferred, linkToReadiness: false };
  }
  return null;
}

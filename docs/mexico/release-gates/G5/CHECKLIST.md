# Mexico release gate G5 — Labor

**Definition (spec §22).** Minimum wage zones / professions, 2026 workweek / overtime, vacations, aguinaldo and PTU validated.

**Evidence tag.** `MX-GATE-G5`. Upload the signed evidence pack as a source artifact with this form number; a **different** Super Admin reviews it. Only then does the gate show SIGNED in the Super Admin readiness view.

**When the evidence is produced: PRE-PILOT.** Signed **before** a pilot grant (D2). The labour policy is checked from the employer's own policy documents, in a non-production environment; it is re-confirmed in the pilot organisation.

**State today.** OPEN. Nothing is signed.

## Sources it needs

- S8, S9 (CONASAMI / DOF — 2026 minimum wages)
- S17, S18 (STPS / DOF — 40-hour workweek transition)
- S21 (SAT — PTU 2026)
- S26 (LFT, primary)
- S19, S20 (PROFEDET — vacations, aguinaldo; cross-checks)

## Evidence checklist

Each item is tagged: **PRE-PILOT** (produced before any real Mexican data, from sources, synthetic cases or a test environment), **PILOT-GENERATED** (produced by the non-binding pilot, Phase 10e), or **GO-LIVE CHECK** (a real filing or payment, possible only after general availability; checked in the activation runbook, not gate evidence).

- [ ] **[PRE-PILOT]** Minimum wage zones and professional minimums, the 2026 workweek and overtime rules, vacations and the vacation premium, aguinaldo and PTU transcribed from S8, S9, S17, S18, S21 and S26
- [ ] **[PRE-PILOT]** Each employer's labour policy passes its floor check (from its policy documents; re-confirmed in the pilot)
- [ ] **[PRE-PILOT]** Golden cases for overtime (double / triple), Sunday premium, rest days, vacations, aguinaldo, PTU and finiquito

## What Zoiko already provides

Phases 3, 6, 9b–9d (labour policy, hour lines, vacations, aguinaldo, PTU, terminations).

## Sign-off

| Role | Name | Date | Signature / reference |
|---|---|---|---|
| Preparer (Super Admin) | | | |
| Reviewer (a different Super Admin) | | | |
| Employer payroll owner (G5, G8) | | | |
- [ ] **[PRE-PILOT]** **PTU trusted-worker salary cap (LFT Art. 127 II), recorded 2026-10-26 (W1-4).** The PTU rule cannot apply it: the engine knows neither who is a trusted worker nor the highest unionised salary. Before a pilot PTU cycle, the employer confirms that no trusted worker exceeds that cap, or the cap is modelled

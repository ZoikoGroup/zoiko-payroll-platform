# DEÜV Production Requirements — Specification Gap Document

**Phase:** Master Audit (following Phase 8BF)
**Status:** `SPECIFICATION_REQUIRED` — no code exists, and per this project's own governing rule, none was written this phase.

---

## 1. Why This Document Exists Instead of Code

Prior phases (8BE, 8BF) each independently searched this entire repository — every `.py`, `.md`, `.jsx`, and `.docx` file, not just `backend/app` — for any trace of DEÜV (Datenübermittlungsverordnung) requirements. This master audit re-ran that search fresh, case-insensitively, for `deuv`, `deüv`, `datenübermittlungsverordnung`, and `Datensatz`. Result: **zero hits** anywhere in the project's own documentation, specifications, or prior phase reports, except this document itself and one disclaiming docstring in the new ELSTER boundary code (Phase 8BF) that explicitly states it does not know ELSTER's or DEÜV's Datensatz shape.

This project's Germany work has, in every other area (PAP, ELStAM, church tax, contribution ceilings), been built against an actual sourced document — the BMF's own PAP XML (hashed and provenance-tracked across 8+ phases), a named "Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack" specification (cited throughout `core.py`/`models.py` as `ZP-TAX-DE-2026-001`), and named phase reports for each statutory dimension. **DEÜV has none of this.** Writing DEÜV code today would mean inventing message formats, field names, and validation rules with no authoritative backing — precisely the fabrication this project's rules (and this phase's own explicit instruction) forbid.

## 2. What DEÜV Actually Is (General, Public-Domain Knowledge — Not Project-Specific Evidence)

DEÜV governs the *Meldungen zur Sozialversicherung* (social-insurance notifications) a German employer must submit to the relevant Krankenkasse/Einzugsstelle: Anmeldung (start of employment), Abmeldung (end of employment), Jahresmeldung (annual), Unterbrechungsmeldung (interruption), and related correction/cancellation messages (Stornierung). Transmission runs over the same `sv.net`/ITSG "Kommunikationsserver" infrastructure the broader German social-security reporting ecosystem uses (a separate channel from ELSTER's own BZSt-facing tax transmission, though both are part of the same general electronic-reporting landscape). Required identifiers include the employer's Betriebsnummer and the employee's Versicherungsnummer, plus a `Grund der Abgabe` (reason-for-submission) code identifying which of the message types above is being sent.

**None of the above is sourced from this project's own documentation** — it is stated here only to make the gap concrete, not as something this codebase should implement from. A future phase must independently obtain and cite an authoritative source (ITSG/GKV-Spitzenverband technical specification, or a licensed reference) before writing any DEÜV code.

## 3. Missing Specification (What Would Need to Be Sourced)

1. The exact Datensatz message formats for each DEÜV message type (Anmeldung/Abmeldung/Jahresmeldung/Unterbrechungsmeldung/Stornierung) — field-by-field.
2. The exact `Grund der Abgabe` code vocabulary and when each applies.
3. Validation rules DEÜV itself imposes (e.g., Betriebsnummer/Versicherungsnummer format checks, required-field combinations per message type).
4. The transmission protocol/envelope (whether it is the same `sv.net` channel other employer-side SV reporting uses, and what credential/certificate model that channel requires — likely distinct from an ELSTER organizational certificate).
5. Response/acknowledgement and correction/rejection handling semantics specific to DEÜV (as opposed to ELSTER's own, separately-documented Transferticket model).

## 4. Required External Contracts / Credentials

- A DEÜV-capable transmission channel registration (likely via the `sv.net` ecosystem or a certified DEÜV service provider), separate from the ELSTER organizational certificate covered by the Phase 8BF ELSTER boundary.
- Employer Betriebsnummer registration (Bundesagentur für Arbeit) — status in this project unknown; not modeled anywhere in `PayrollEmployee`/`Organization` today.
- A licensed or otherwise verified copy of the current DEÜV technical specification (message layouts and validation rules).

## 5. Engineering Prerequisites (Once a Real Specification Is Obtained)

1. Add Betriebsnummer (employer) and Versicherungsnummer (employee) fields to the relevant models — neither exists today (confirmed: no such column on `Organization`/`PayrollEmployee`/`EmployeeStatutoryProfile`).
2. A DEÜV-specific transmission-record model, analogous in shape to `GermanyElsterTransmission` (Phase 8BF) but carrying DEÜV's own `Grund der Abgabe` vocabulary and Datensatz payload shape once known.
3. A fail-closed transmitter boundary mirroring `engine/germany_elster.py`'s and `engine/germany_pap/elstam.py`'s established pattern (`ABC` interface, one `Unavailable*` implementation, a `resolve_*_transmitter()` function that stays fail-closed until a real specification and credentials exist) — this pattern is reusable once the actual message shape is known; it should not be built ahead of that, since the interface itself would otherwise encode a guessed shape.
4. Decision (product, not engineering): whether DEÜV transmission shares infrastructure/credentials with the ELSTER boundary or is fully independent — cannot be answered without the specification in §3.4.

## 6. Classification

**Status: `NOT_IMPLEMENTED`.**
**Blocker type: `SPECIFICATION_REQUIRED`** (not merely `BLOCKED_EXTERNAL` in the credentials sense — even with full external authorization and credentials, no code could be written today because the message format itself is unknown to this project).
**Owner: EXTERNAL AUTHORITY** (to supply/confirm the specification) **+ PRODUCT** (to decide the credential/infrastructure-sharing question in §5.4) **+ ENGINEERING** (to implement, only after both of the above).

No DEÜV code, model, migration, or test was added in this or any prior phase. This document is the complete and only DEÜV deliverable for this phase.

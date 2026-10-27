# Mexico completion programme — report

Written for the associate who pushes these commits and for the gate owners. Date: 2026-10-27. Branch: `nikhil`. Master prompt: `docs/mexico/MEXICO_COMPLETION_MASTER_PROMPT.md`. Step detail: `docs/mexico/MEXICO_COMPLETION_PROGRESS.md`.

**Mexico stays dormant and fail-closed.** No migration in any commit. No pack, release, registry or gate was activated or signed. Every Mexican calculation is still blocked, first by D-01 (rounding).

## 1. Every gap-register item and its final state

States: DONE · BLOCKED-ON-DECISION · BLOCKED-ON-SOURCE · EXTERNAL · OPEN — engineering (buildable, not done in this programme).

| # | Item | State | Note |
|---|---|---|---|
| A1 | Report templates were empty shells | DONE | W4-1, W4-2: snapshot-bound templates and dedicated generators |
| A2 | MX-EMPLOYER-COST showed 0 | DONE | W4-1: bound to the engine's employer figures |
| A3 | MX-PAYROLL-REGISTER lacked IMSS employee, INFONAVIT credit, subsidy | DONE | W4-1 |
| A4 | No Mexico snapshot-field catalog | DONE | W4-1: `PAYSLIP_ITEM_JSON` catalog for MX |
| A5 | Per-branch IMSS list not addressable | DONE | W4-1: keyed list selector `name[k=v]` |
| A6 | Template activation refused forever | DONE | W4-3a: gates SIGNED + content Active + fields proven |
| A7 | Mexico policy page fell back to India's | DONE | W5-4: explicit no-policy page (other countries: OOS-6) |
| A8 | Stale "not implemented" text | DONE | Phase 11d |
| A9 | The seed could not load what was saved | DONE | Phase 11d (archive copies feed Draft only) |
| A10 | CFDI nodes still refused | BLOCKED-ON-SOURCE | SubsidioAlEmpleo: C6 (source); CompensacionSaldosAFavor: C5 (decision); Incapacidades: needs an IMSS incapacity record — **engineering, not started**; separation node: B11/C10; shares and pensions out of scope |
| A11 | Triple-rate overtime on the CFDI | DONE | W6-1 (overtime itself waits for D-17) |
| A12 | Runs stop at Approved | EXTERNAL | Needs stamping (C1, C3) and bank settlement (C7) |
| A13 | SEPARACION classification | DONE | W5-4: refused at approval |
| A14 | Dead code | DONE | Phase 11d |
| A15 | Engine seams with no table | BLOCKED-ON-DECISION | W3: every seam has an interface; hourly rate D-17, FIXED SBC D-18, termination fixed days D-19; INFONAVIT proration BLOCKED-ON-SOURCE |
| A16 | No ISR for a minimum-wage-only worker | DONE | W3-5 (LISR Art. 96 ¶1) |
| A17 | Special runs carry no month-to-date income | OPEN — engineering | Build the month-to-date accumulator for finiquito / aguinaldo / PTU runs; not started in this programme |
| A18 | One IMSS liability mixes monthly and bimonthly branches | OPEN — engineering | Split the RCV branches into their own liability, then add the IMSS filing rules; not started |
| B1 | ISR tariffs | DONE | Batch 1, [PENDING G1]; activation needs VERIFIED sources (C2) |
| B2 | UMA | DONE | Batch 1, [PENDING G1] |
| B3 | Employment subsidy | DONE | Batch 1–2, W1-6, W3-1 |
| B4 | IMSS rates and SBC ceiling | DONE | Batch 2 |
| B5 | CEAV schedule | DONE | Batch 2 (lowest-band anchor: D-03) |
| B6 | Minimum wages and ZLFN municipalities | DONE | Batch 2 |
| B7 | Workweek, overtime tiers, hourly-rate rule | BLOCKED-ON-DECISION | Workweek and tiers done; hourly rate D-17 |
| B8 | Vacation days and benefit floors | DONE | Batch 2 |
| B9 | INFONAVIT | BLOCKED-ON-SOURCE | Employer 5% and percentage basis done (W1-1); fixed-amount basis and proration need INFONAVIT's payment regulation |
| B10 | State ISN | BLOCKED-ON-DECISION | CDMX done (W1-2); D-06, D-10; other states have no saved source |
| B11 | Rounding, SBC floor, risk-premium range | BLOCKED-ON-DECISION | SBC floor (W1-1) and range (Batch 2) done; rounding D-01 |
| B12 | Special-pay rules | BLOCKED-ON-DECISION | Transcribed (W1-3a); D-07, D-08, D-09 |
| B13 | Pay-frequency → Art. 96 period map | BLOCKED-ON-DECISION | 02 / 04 / 05 / 10 mapped; 01 Diario D-02 |
| B14 | Termination reasons and finiquito | BLOCKED-ON-DECISION | Transcribed (W1-3b); D-11, D-12, D-13, D-07b |
| B15 | PTU rule and exclusions | BLOCKED-ON-DECISION | Transcribed (W1-4); D-14; LFT Art. 127 II not modelled |
| B16 | Annual ISR adjustment | DONE | W1-4 |
| B17 | Art. 93 ordinary exemptions, FIXED SBC, absences | BLOCKED-ON-DECISION | W3-3, W3-4 done (wait for D-07); D-18 |
| B18 | Filing calendar, IMSS deadline, holidays, risk-premium period | BLOCKED-ON-DECISION | ISR, INFONAVIT, CDMX ISN, risk period, 5-day deadline done; holidays D-16; IMSS filing waits for A18 |
| B19 | System-concept SAT codes | EXTERNAL | Load `sat_2026_08` into a release in production; two Super Admins approve it and each mapping (C5 for the undecided codes) |
| B20 | SAT codes on earning classifications | EXTERNAL | Per employer, approved by a second Super Admin |
| B21 | Golden vectors | BLOCKED-ON-DECISION | W7 blocked: D-01 (rounding) blocks every calculation and decides every expected figure |
| B22 | CFDI cancellation reasons (c_MotivoCancelacion) | BLOCKED-ON-SOURCE | W2-3: not in the saved sources |
| C1 | PAC choice, contract, sandbox | EXTERNAL | Release owner |
| C2 | Archive copies of S4 / S28 / S30 (and 28 more) | EXTERNAL | Direct download from the official sites + `verify_mexico_sources verify`; only S22 is VERIFIED |
| C3 | CSD custody and signing | EXTERNAL | Security lead + release owner |
| C4 | Source of SalarioDiarioIntegrado | BLOCKED-ON-DECISION | G1 owner (same question as D-12) |
| C5 | Undecided SAT codes | BLOCKED-ON-DECISION | G1 owner |
| C6 | Subsidy on the CFDI after the 2024 reform | BLOCKED-ON-SOURCE | SAT's current instructions not saved |
| C7 | Bank / SPEI file | EXTERNAL | Choose the bank(s), get their layout |
| C8 | IDSE / SUA / SIPARE layouts and transmission | BLOCKED-ON-SOURCE | Layouts not saved; outputs are NOT AN OFFICIAL FILE |
| C9 | State ISN return transmission | EXTERNAL | Per state |
| C10 | Separation receipt validation | EXTERNAL | Needs the PAC test environment (C1) |
| C11 | 830 CHH postal codes, inconsistent time zone | BLOCKED-ON-DECISION | D-21 (readings built, switch undecided) |
| C12 | Union membership (Sindicalizado) | BLOCKED-ON-DECISION | Release owner |
| C13 | Q9: identifiers at rest | BLOCKED-ON-DECISION | Security lead (legal) |
| C14 | MX_IDENTITY_TOKEN_KEY in production | EXTERNAL | Ops |
| C15 | Durable XML storage (GCS) | EXTERNAL | Release owner + ops |
| C16 | ZP-PRIV reviews owed | EXTERNAL | Rugvedh — see §3 |
| C17 | Code-owner review not enforced | EXTERNAL | Repository admin (branch protection) |
| C18 | Employer chart of accounts | EXTERNAL | Per employer |
| C19 | Hosting decision, Q9, the pilot organisation | EXTERNAL | Legal + release owner |
| C20 | G1–G8 sign-off and activation | EXTERNAL | Gate owners; evidence drafts in `release-gates/G*/EVIDENCE_DRAFT.md` |

**Count:** DONE 21, BLOCKED-ON-SOURCE 5, EXTERNAL 16, BLOCKED-ON-DECISION 16, OPEN — engineering 2 (of 60).

## 2. Decisions for the G1 owner (`DECISIONS_PENDING.md`)

Each is built behind a switch or an interface where it can be. Undecided, the affected calculation blocks with its own code; nothing is guessed.

| Priority | Decisions | Why |
|---|---|---|
| 1 | **D-01** rounding | Blocks **every** calculation, pack activation and every golden vector (W7) |
| 2 | **D-07**, D-08, D-09, D-12 (= C4), D-13 | Every special payment, separation and finiquito |
| 3 | **D-17** hourly rate | Every overtime line (W6's triple-rate CFDI waits for it) |
| 4 | D-02, D-03, D-04, D-05, D-16, D-18, D-19 | Daily pay, CEAV band 1, readings behind transcribed rows, January–April workweek, IMSS business days, FIXED SBC items, fixed days at termination |
| 5 | D-06, D-10 (G4) · D-11, D-14 (G5) | CDMX ISN on separation lines and the micro / small benefit; other termination reasons; the PTU cap |
| 6 | D-20, D-21, C5, C12 | QR total on the printed receipt, Chihuahua border time zones, undecided SAT codes, union membership |

D-15 was resolved by sources (W2-5).

## 3. Local commits, in order

Each commit is one step and can be its own PR. The ZP-PRIV column marks what needs **Rugvedh's review before merge**; four of those are already on `main` (PR #134, merged before his review).

| Commit | Step | Production effect | ZP-PRIV | Where |
|---|---|---|---|---|
| `79da2b8` | Mexico planning: Phase 12 plan and completion master prompt | Docs only | No | on main (PR #134) |
| `52af6eb` | Mexico 11d + transcription batches 1-2: seed fixes, sources gate, ISR/UMA/subsidy/IMSS/CEAV/INFONAVIT/min-wage/LFT content | Draft-pack content + seed fixes; activation needs VERIFIED sources | **Yes** — sources gate | on main (PR #134) |
| `43efac9` | Mexico W1-1: SBC floor, INFONAVIT percentage basis, S34 de-indexation decree | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `8cf5dd8` | Mexico W1-2: CDMX state ISN rate and special-pay inclusions | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `11b3359` | Mexico W1-3a: special-pay exemption and withholding rules, aguinaldo rule | Mexico content; the shared PayrollContext gains two optional Mexico fields (default None) | No | on main (PR #134) |
| `a8ec12e` | Mexico W1-3b: termination-reason catalog and finiquito rule (LFT, LISR Art. 96) | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `b6d901e` | Mexico W1-4: PTU rule and annual ISR adjustment, 2026 annual tariff | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `ae6b00d` | Mexico W1-5: filing calendar, IMSS movement deadline, risk-premium period, S35 (CFF) | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `7b55b46` | Mexico W1-6: subsidy remainder done; CFDI subsidy reporting (C6) blocked on source | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `58362d6` | Mexico W2: sources — S36 ISSSTE law, INFONAVIT bimonthly due date, W1 full-suite result | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `a55d59d` | Mexico W3-1: subsidy monthly cap interface, transcribed from S3 Art. Segundo para 4 | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `798ffec` | Mexico W3-2: rest-day work interface, transcribed from LFT Arts. 73 and 75 | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `2d3dacb` | Mexico W3-3: contribution days with absences and incapacity (LSS Art. 31, Ley INFONAVIT Art. 29) | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `6f91372` | Mexico W3-4: LISR Art. 93 exemptions for ordinary earnings (overtime, Sunday premium) | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `84847ab` | Mexico W3-5: interfaces for hourly rate, INFONAVIT proration, FIXED SBC items, termination fixed days; A16 | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `aa92e1d` | Mexico W3: full backend suite result after W3 (7,505 passed; known local-only failures) | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `d4c69f0` | Mexico W4-1 (Phase 12a): snapshot-bound report templates, keyed list selector | Mexico report catalog added to the shared report service (additive; NL / IE / SE pinned unchanged) | No | on main (PR #134) |
| `df94606` | Mexico W4-2 (Phase 12b): dedicated report generators [ZP-PRIV review: new org route] | New org route (dormant: refused while Mexico is off) | **Yes** — org route | on main (PR #134) |
| `a935f85` | Mexico W4-3a (Phase 12c, E6): template activation gate replaces the permanent refusal | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `3a44dc1` | Mexico W4-3b (Phase 12c): stamped XML kept, printed CFDI receipt [ZP-PRIV review: new org route renders raw RFC/CURP/NSS] | New org route; stamped XML stored | **Yes** — renders raw RFC / CURP / NSS | on main (PR #134) |
| `4ae643c` | Mexico W4 full suite: 7,530 passed, only the known local-only failures | Mexico-only engine / content / docs; dormant in production; no migration | No | on main (PR #134) |
| `512b8ce` | Mexico W5-1: Super Admin views for every content family, with sources [ZP-PRIV review: two new read-only Super Admin routes] | Two read-only Super Admin routes | **Yes** — new routes | on main (PR #134) |
| `5485762` | Mexico W5-2: no statutory edit outside the governed paths [ZP-PRIV review: Mexico refused on generic row editor and hotfix] | Generic row editor and hotfix refuse Mexico | **Yes** — authorisation change | local |
| `89a444a` | Mexico W5-3: readiness per gate, code-confirmed vs awaiting evidence [ZP-PRIV review: one new read-only Super Admin route] | One read-only Super Admin route | **Yes** — new route | local |
| `69a767a` | Mexico W5-4: no-policy page, SEPARACION refused at approval, action-refusal wording; end-of-W5 suite | Mexico-only engine / content / docs; dormant in production; no migration | No | local |
| `ec1db02` | Mexico W6: triple-rate overtime on the CFDI (A11); time-zone readings for C11 (D-21) | Approved-hours route takes an optional field; Mexico-only CFDI input | No | local |
| `f0e80eb` | Mexico W7 (blocked on D-01, recorded) and W8: gate evidence drafts G1-G8 | Docs only | No | local |

**Never staged:** your own uncommitted files (`backend/app/main.py`, `backend/.env.example`, `frontend/vite.config.js`, `backend/scripts/validate_environment.py`, `docs/SINGAPORE_*`, `docs/HONG_KONG_*`) and every source binary under `docs/mexico/sources/`.

## 4. What remains

**Before a pilot** (G1, G2, G4, G5, G7 signed, Q9, hosting, the identity key; release checklist):
- the G1 owner's decisions, D-01 first, then golden vectors (W7) from an independent calculation;
- a direct download of every source used by an activated pack (`verify_mexico_sources verify`), so the packs can be approved and activated four-eyes;
- the PAC chosen with sandbox credentials (C1), CSD custody (C3), durable XML storage (C15);
- Rugvedh's ZP-PRIV reviews (C16) of every flagged commit, his changes merged first;
- engineering: A17 (special-run month-to-date income), A18 (IMSS RCV liability split), the IMSS incapacity record behind the `Incapacidades` node;
- the gate evidence packs signed (drafts: `docs/mexico/release-gates/G*/EVIDENCE_DRAFT.md`).

**Before general availability** (all of G1–G8, the registry AVAILABLE):
- G6: the bank file (C7), the authority layouts and transmission (C8, C9), runs past Approved (A12);
- G8: two parallel cycles in the pilot organisation, a reconciled bimester and ISR period, employer sign-off;
- every state to be enabled transcribed from its own saved code (B10).

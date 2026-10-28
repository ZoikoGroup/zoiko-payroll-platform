# Mexico final mile — report

**For:** the release owner, the gate owners (G1–G8), Rugvedh (ZP-PRIV) and Engineering.
**Programme:** `MEXICO_FINAL_MILE_MASTER_PROMPT.md` (X1–X9), 2026-10-27 to 2026-10-28. Step details are in `MEXICO_FINAL_MILE_PROGRESS.md`.

**In one paragraph.** Everything that turns an outside input into a governed action inside the product is now built:
- a four-eyes **decision register** (X1);
- a watermarked **calculation sandbox** (X2);
- the **report catalogue** the spec asks for (X3);
- **parallel-payroll** tooling for G8 (X4);
- ready-to-plug **kits** for the PAC, CSD custody, XML storage and the bank / IMSS files (X5).

The outside inputs themselves are not: decisions, VERIFIED sources, a PAC, a bank, IMSS layouts, custody, retention, reviews and signatures. Nothing statutory was chosen and nothing was activated. **Mexico is still dormant in production.** The configuration re-audit (X8) closed four governance gaps, including one where a statutory value could change outside a governed path.

---

## 1. Session-zero results

| Check | Result |
|---|---|
| Production head at the start | **`c7d2e9a4f1b6`** (A18), from the head check of deploy run 40472214932. Nothing Mexican Active |
| Production head now | **`92c67cab49fc`** expected, from the head check of deploy run **40634575955** (PR #139, green). Nobody has run `alembic current` on the host; whoever has access should confirm |
| Live-app check | **Deferred.** It needs a Super Admin sign-in on the live app, which this programme does not have |
| Privacy smoke secrets | **Not configured**, so the post-deploy privacy smoke step is skipped on every deploy. A repository admin sets `ZP_SMOKE_BASE_URL`, `ZP_SMOKE_IDENTITIES`, `ZP_SMOKE_EMPLOYEE_ID` and, optionally, `ZP_SMOKE_ALERT_WEBHOOK` |

**Incident during the programme.** PR #138 merged Mexico m20 and Venu's South Africa chain, both children of `c7d2e9a4f1b6`, and left two Alembic heads.
- **Backend:** the deploy failed at the test stage and was skipped, so production was not migrated.
- **Frontend:** it deployed anyway, so for about an hour the new Super Admin screens called routes that were not live.
- **Fix:** an empty merge revision `92c67cab49fc` (PR #139), proven on PostgreSQL 17 from `c7d2e9a4f1b6`.

Details are in `PRODUCTION_STATE.md` and the progress file.

## 2. Every gap-register item: state, next action, owner

"In product" means the next action can now be taken in the product, by a person, using X1–X5. "Outside" means it needs something the product cannot supply.

### A. Code

| Item | State | Next action | Owner | Where |
|---|---|---|---|---|
| A1–A9, A11, A13, A14, A16, A17, A18 | DONE (completion programme) | — | — | — |
| A10 CFDI nodes still refused | Blocked | **Incapacidades:** answer the ten questions in `INCAPACITY_RECORD_PROPOSAL.md` (X6) before any build. SubsidioAlEmpleo: C6. CompensacionSaldosAFavor: C5. Separation node: C10 | Rugvedh + legal; G1 owner | Outside (proposal written) |
| A12 Runs stop at Approved | External | Stamping (C1, C3) and bank settlement (C7) | Release owner | Outside (kits ready, X5) |
| A15 Engine seams with no table | Blocked on decision | Answer D-17 (hourly rate), D-18 (FIXED SBC), D-19 (termination fixed days) | G5 / G2 owners | **In product:** Decisions tab (X1) |

### B. Content and configuration

| Item | State | Next action | Owner | Where |
|---|---|---|---|---|
| B1–B6, B8, B16 | Transcribed, [PENDING G1] | Verify sources (C2), then sign at G1 / G2 / G5 | Gate owners | In product: Statutory rules views; runbook for C2 |
| B7 Workweek, overtime, hourly rate | Blocked on decision | D-17 | G5 owner | **In product** (X1) |
| B9 INFONAVIT fixed-amount basis and proration | Blocked on source | Save INFONAVIT's payment regulation | Release owner | Outside |
| B10 State ISN | Blocked on decision | D-06, D-10 (CDMX); other states have no source | G4 owner | **In product** (X1) |
| B11 Rounding rule | Blocked on decision | **D-01**: brief `D01_ROUNDING_DECISION_BRIEF.md` with sandbox what-ifs | G1 owner | **In product** (X1, X2) |
| B12 Special-pay rules | Blocked on decision | D-07, D-08, D-09 | G1 owner | **In product** (X1) |
| B13 Pay-frequency map | Blocked on decision | D-02 | G1 owner | **In product** (X1) |
| B14 Termination | Blocked on decision | D-11, D-12, D-13, D-07b | G1 / G5 owners | **In product** (X1) |
| B15 PTU | Blocked on decision | D-14 | G5 owner | **In product** (X1) |
| B17 Art. 93, FIXED SBC, absences | Blocked on decision | D-07, D-18; uncertified sick leave (X6 finding) | G1 / G2 owners | **In product** (X1) |
| B18 Calendar, holidays | Blocked on decision | D-16 | G2 owner | **In product** (X1) |
| B19 System-concept SAT codes | External | Load `sat_2026_08` into a release; two Super Admins approve it (since X8, an entry author cannot approve) | Super Admins | In product (CFDI catalogs tab) |
| B20 SAT codes on earning classifications | External | Per employer, four-eyes | Employer + Super Admin | In product |
| B21 Golden vectors | Blocked on decision | D-01 first, then **D-03**. The sandbox now shows the figures each reading gives | G1 / G2 owners | **In product** (X2) |
| B22 c_MotivoCancelacion | Blocked on source | Save the catalogue | Release owner | Outside |

### C. External inputs and decisions

| Item | State | Next action | Owner | Where |
|---|---|---|---|---|
| C1 PAC | External | Choose a PAC using `PAC_SELECTION_CHECKLIST.md`; its adapter must pass the conformance kit (10 checks) in its sandbox | Release owner, then Eng | Kit ready (X5); choice outside |
| C2 Sources | External | Run `SOURCE_DOWNLOAD_RUNBOOK.md` from a network that resolves sat.gob.mx (32 files, plus 14 cited sources not yet saved, including S23) | Release owner / a colleague in Mexico | Outside (runbook, X7) |
| C3 CSD custody | External | Security lead decides custody (`CSD_CUSTODY_CONTRACT.md`); Eng implements the provider and the sealer | Security lead + Eng | Interface ready (X5); decision outside |
| C4 SalarioDiarioIntegrado | Blocked on decision | C4 in the register (same question as D-12) | G1 owner | **In product** (X1) |
| C5 Undecided SAT codes | Blocked on decision | C5 in the register | G1 owner | **In product** (X1) |
| C6 Subsidy on the CFDI | Blocked on source | Save SAT's current instruction | Release owner | Outside |
| C7 SPEI file | External | Choose the bank(s); send `intake/SPEI_INTAKE.md` | Release owner + employer | Intake ready (X5) |
| C8 IDSE / SUA / SIPARE | Blocked on source | Send the intake templates; decide who transmits | Release owner + employer | Intake ready (X5) |
| C9 State ISN return transmission | External | Per state portal process | Release owner | Outside |
| C10 Separation receipt validation | External | Needs the PAC sandbox (C1) | G1 owner | Outside |
| C11 CHH postal codes | Blocked on decision | D-21 | G1 owner | **In product** (X1) |
| C12 Sindicalizado | Blocked on decision | C12 in the register | Release owner | **In product** (X1) |
| C13 Q9 identifiers at rest | Blocked on decision | Security lead and legal; see also the `payslip_items.compliance_fields` note | Security lead + Rugvedh | Outside |
| C14 `MX_IDENTITY_TOKEN_KEY` | External | Set in production | Ops | Outside |
| C15 Durable XML storage | External | GCS bucket and retention period (`CFDI_XML_STORAGE_CONTRACT.md`) | Release owner + legal + Eng | Interface ready (X5) |
| C16 ZP-PRIV reviews | External | `ZP_PRIV_REVIEW_PACKETS.md`: 13 packets, W4-3b first, plus 10c, 10f, 10g, 11a and 11b, all still owed | Rugvedh | Packets ready (X7) |
| C17 Code-owner review not enforced | External | Branch protection on `main` | Repository admin | Outside |
| C18 Employer chart of accounts | External | Per employer (journal mappings) | Employer | In product |
| C19 Hosting, Q9, pilot organisation | External | Decide; then a four-eyes pilot grant | Legal + release owner | In product for the grant |
| C20 G1–G8 sign-off | External | Evidence drafts updated with the final-mile tooling (`release-gates/G*/EVIDENCE_DRAFT.md`); G8 uses the X4 tooling plus D-25 | Gate owners | In product (Readiness tab) |

**New decisions from this programme:**
- D-23: gate-owner role;
- D-24: variance threshold;
- D-25: parallel materiality;
- D-26: general-availability four-eyes;
- D-27: retiring Active content;
- D-28: organisation-side four-eyes and effective dating.

All are in the register.

## 3. Commits, in order, grouped as they were (or will be) reviewed

| PR | Commit | Step | Production effect | Migration | ZP-PRIV |
|---|---|---|---|---|---|
| #136 → state doc | `cd98323` | PRODUCTION_STATE after PR #134–#136 | None (docs) | — | — |
| #137 | `fa4c762` | Final-mile prompt and session-zero record | None (docs) | — | — |
| #138 | `2dece5e` | Session zero: head recorded | None (docs) | — | — |
| #138 | `8ffe7f4` | X1 decision register | Eight Super Admin routes, Decisions tab | **`d3f8b2a6c1e9`** (`payroll_mx_decisions`) | Yes |
| #138 | `06e9480` | X2 sandbox | One Super Admin route (writes nothing) | — | Yes |
| #138 | `bafb287` | X3 report catalogue | 8 report types, receipt-render audit, 3 Super Admin routes | `AMOUNT` added to X1's check (unmerged at the time) | Yes |
| #138 | `db9eeb7` | X4 parallel payroll | Six org routes (dormant), panel | Two tables added to `d3f8b2a6c1e9` (TENANT + WORKER, RLS) | Yes |
| #138 | `80fbf09` | X5 kits | One Super Admin route (CSD expiry); interfaces not installed | — | Yes |
| #138 | `e47d433` | X6 incapacity proposal | None (docs) | — | Yes (and legal) |
| #138 | `4b9a76c` | X7 packets, D-01 brief, runbook | None (docs) | — | — |
| #139 | `8635a7e` | Merge revision for the two heads | Unblocked the deploy | **`92c67cab49fc`** (empty merge) | Yes |
| **next PR** | `9e65ae4` | X8 configuration re-audit | Mexico rows no longer movable; Mexico evidence frozen after review; stricter template and catalogue approval; reconcile button | — | **Yes** |
| **next PR** | (this commit) | X9 close-out | None (docs) | — | — |

**#138 was merged before the ZP-PRIV review of X1–X5 and of the migration.** These are post-merge reviews now: see `ZP_PRIV_REVIEW_PACKETS.md`. The next PR (X8, X9) should wait for Rugvedh.

## 4. Path to pilot (dependencies, with owners)

1. **D-01 rounding** (G1 owner) → **D-03 CEAV lowest band** (G2 owner). Until both are answered, every calculation is blocked.
2. Transcribe the D-01 / D-03 answers into the 2026 pack (Eng), then **golden vectors** for the §21 fixtures (G1 / G2 owners; B21). The X2 sandbox shows the expected figures for any candidate.
3. **Sources VERIFIED** (C2; a colleague on a network that reaches sat.gob.mx), then `verify_mexico_sources compare` (Eng).
4. The remaining G1 / G2 / G5 decisions in the register: D-07, D-08, D-09, D-17, D-12, D-13 and D-02 (order in the D-01 brief).
5. **PAC chosen** (C1, release owner), then the adapter passes the conformance kit in the sandbox (Eng). **CSD custody decided** (C3, security lead), then provider and sealer (Eng). **XML storage and retention** (C15, release owner and legal).
6. **ZP-PRIV reviews** (C16, Rugvedh), **Q9 / hosting** (C13, C19, security lead and legal), and **`MX_IDENTITY_TOKEN_KEY`** (C14, ops).
7. **Gate evidence G1–G7** signed: the gate owner uploads, a second Super Admin reviews (Readiness tab).
8. **Pilot organisation and grant** (C19; four-eyes grant), then **two parallel cycles** with the X4 tooling plus **D-25** (G8, release owner and employer), then G8 signed.
9. **General availability** (D-26 decides whether this needs two people).

Bank (C7) and IMSS file layouts (C8) are needed for production payments and filings, not for the pilot: the pilot never pays or files.

## 5. What contradicts an earlier report or instruction

1. **The master prompt's pointer:** it says the rounding candidates are in `MEXICO_TRANSCRIPTION_BATCH_2_REPORT.md` §3. They are in **§4**.
2. **D-03 blocks every calculation,** not only ZLFN workers in band 1, because band 1's lower bound is read for every SBC (X2). `DECISIONS_PENDING.md` was corrected.
3. **"Sick" leave counts as IMSS incapacity days** (`mexico_run_service._attendance_counts`). The W3-3 rule, and LSS Art. 31 IV, cover only IMSS-certified incapacity (X6).
4. **One migration for the programme:** there are two. `d3f8b2a6c1e9` holds all the programme's tables; `92c67cab49fc` is the merge PR #138 made necessary.
5. **The W5-2 report** said Mexico statutory rows cannot be edited through the generic editors. A row could still be **moved** out of a Mexico pack through another country's pack id (X8, fixed). **The same hole remains for every other country.**
6. **Master-copy routes** are live, but the UI comment calls them "retired" (X8, reported).
7. **Venu's ZA migration notes** say the chain "stays linear". After PR #138 it was not, until the merge revision.

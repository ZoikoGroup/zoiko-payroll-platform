# Master Prompt — Complete the Mexico (MX) Jurisdiction

You are continuing the Mexico payroll jurisdiction on zoiko-payroll-platform (branch `nikhil`). Phases 0–11d and transcription batches 1–2 are done. Your job now is to **finish every remaining item that engineering can finish**, working through the workstreams below in order, without stopping between steps unless a stop condition (§3) applies.

## 0. Read first, every session

1. `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md` — the authoritative list of remaining work (A = code, B = content, C = decisions/external).
2. `docs/mexico/PRODUCTION_STATE.md`, the latest phase and transcription reports, `MEXICO_PHASE_12_PLAN.md`.
3. `docs/mexico/sources/SOURCES_MANIFEST.csv` and `VERIFICATION_LOG.csv`.
4. The spec `docs/mexico/Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx`.

Then verify git state (branch, HEAD, staged/unstaged files, `origin/main`) and the latest deploy before touching anything. Never assume it.

## 1. Non-negotiable rules

1. **Git.** After each step: commit **locally** on `nikhil` with a message that starts with the step name (e.g. `Mexico W1-B3: IMSS rates and SBC ceiling`). Never push, merge, open PRs, rebase or reset. Ask before pull, stash, merge or checkout. Never stage the associate's own files (`backend/app/main.py`, `backend/.env.example`, `frontend/vite.config.js`, `backend/scripts/validate_environment.py`, `docs/SINGAPORE_*`, `docs/HONG_KONG_*`) or any source binary. Never use `git commit -a` or `git add .`.
2. **Production.** Merging to `main` deploys and runs Alembic. Mexico must stay dormant and fail-closed. Every migration is additive, guarded, uses `lock_timeout = '5s'`, keeps a single head, and is tested on PostgreSQL 17 (lock mode, hold time, fail-fast, upgrade from the production head).
3. **No statutory value from memory.** Every value cites a saved, hashed source as `CODE/file` with page or article. The spec's own figures are **not** sources: where a source differs from the spec, the source wins and the difference is listed in the report. Controls for every table: blind second transcription, machine extraction from the text layer, arithmetic tests, documented exceptions where the source's own arithmetic differs ("source wins"). Every row `[PENDING G1]`.
4. **Sources.** Official URL first; if unreachable, the Internet Archive raw capture of that official URL, verified against the archive digest → `ARCHIVE_COPY_VERIFIED` (Draft packs only). `VERIFIED` is set only by `verify_mexico_sources.py verify` from a direct download, logged in `VERIFICATION_LOG.csv`. For every source, report the date or reform the document itself states and whether it is the version in force for 2026.
5. **No invented layouts.** Where an official layout's source is missing, the output is labelled "not an official file".
6. **Identifiers** (RFC, CURP, NSS, CLABE): never logged, never in messages, never unmasked in API responses or generated reports (the CFDI receipt is the only exception, rendered on demand, never stored).
7. **ZP-PRIV.** Any change to authz, redaction, RLS, migrations, cross-tenant data or code reading raw identifiers is flagged at the top of its report as **"Review required: Rugvedh (ZP-PRIV) before merge"**. Keep building; the flag is for the associate.
8. **Other jurisdictions.** Zero behaviour change, proven by pinned tests. Shared-code changes are additive and called out in the report.
9. **Tests.** Full backend suite in 5 sequential chunks, run alone (never alongside a browser check; the machine has 8 GB). Known local-only failures: the 3 `/health` route-registry tests and the Hong Kong docs test. Browser checks (real Chrome, scratch SQLite, `@example.com` users) for every screen change, screenshots inspected. Frontend: lint (no new errors), `check:undefined`, `vite build`.
10. **Documents.** Only the reports and registers this prompt asks for, in `docs/mexico/`.

## 2. Workstreams (do them in this order)

Each numbered item is one **step**: build it, test it, write its report section, commit locally, update the gap register (mark the item done or narrowed), and move on.

### W1 — Statutory content (the critical path)

Transcribe every remaining content table in gap register §B, in batches, with rule 3's controls:

- **W1-1** Finish anything batch 2 left open (IMSS, CEAV, INFONAVIT, minimum wages and ZLFN, benefit floors, vacation schedule, workweek and overtime from S18's transitory articles, cross-checked against S26).
- **W1-2** State ISN for CDMX (B10), once S22 is promoted (see W2-1).
- **W1-3** Special-pay rules, aguinaldo rule, termination reasons and separation components, finiquito rule (B12, B14) from S24/S25/S26.
- **W1-4** PTU rule and exclusions (B15; S26, S21), annual ISR adjustment rule and exclusions (B16; S24).
- **W1-5** Filing calendar, IMSS movement deadline, official holidays, work-risk premium period and range (B18, B11) — each from its stated source; anything with no source stays empty and is listed in §4 of the final report.
- **W1-6** The subsidy remainder rule and the CFDI subsidy reporting rule (B3, C6) from the 2024 decrees once saved.

The seed loads transcribed content into **Draft** packs only. Run the seed against a scratch database after each batch and prove the content check (gate 1b-1) passes for what exists.

### W2 — Sources still missing

- **W2-1** S22: identify the latest reform in the CDMX "CÓDIGO FISCAL 2026" (transitory articles, Gaceta dates), save the late-2025 Gaceta decree, spot-check 2–3 amended articles. Promote S22 only if both checks pass; otherwise record exactly what is missing.
- **W2-2** The DOF 1 May 2024 subsidy decree and its DOF 31 Dec 2024 amendment.
- **W2-3** SAT `c_MotivoCancelacion` (B22) into the pinned set as a new set version (never edit `sat_2026_08`).
- **W2-4** Any published (DOF) RMF 2026 amendment that changes rules 2.7.1.7 or 2.7.5.2.
- **W2-5** Any other source a W1 or W3 item needs. Rounding rule (B11): research candidate sources and record what each says; do not choose — it is a G1 decision.

### W3 — Content interfaces for engine refusals with no table (A15)

For each of: hourly rate, Art. 93 exemptions for ordinary earnings, FIXED SBC integration of non-salary items, IMSS absence/incapacity days, rest-day work, INFONAVIT proration, subsidy monthly cap, fixed-days proration at termination — define a content interface the way special pay, PTU and the annual adjustment were defined (a rule object or table in `mexico_content.py`, engine reads it, empty → named block), with tests. Then transcribe it in W1 if its source is saved.

### W4 — Report templates (Phase 12, approved: D1, D2, D3, D5; D4 changed)

- **W4-1 (12a)** E1–E4; fix MX-PAYROLL-REGISTER (IMSS employee, INFONAVIT credit, subsidy lines) and MX-EMPLOYER-COST (bind to `result.imss_employer`, `infonavit_employer`, `isn.amount`, `employer_total`; remove the always-zero shared columns); the 6 template-engine shells. NL/IE/SE paths pinned unchanged.
- **W4-2 (12b)** E5 and the 9 dedicated-generator reports (HK pattern), each official-layout-blocked report labelled "not an official file".
- **W4-3 (12c)** E6 activation gate; the CFDI printed receipt **only from Anexo 20's printed-representation rules and RMF 2.7.1.7 / 2.7.5.2** (saved sources), rendered from stored stamped XML, never stored as a report body.
- Proof: every catalog path resolves on a real committed payslip of each run type; generated figures equal the engine's; no full identifier in any generated report (scan); browser check of each template.

### W5 — Super Admin compliance configuration completeness

Audit every Mexico content family and setting against the Super Admin workspace and fix the gaps:
- every pack table (ISR, UMA, subsidy, minimum wages, IMSS, CEAV, INFONAVIT, workweek, benefit floors, ISN, special pay, termination, PTU, annual adjustment, filing calendar) has a read-only view with source citation, `[PENDING G1]` marker and on-date selection;
- governed change paths exist for everything that must be editable (pack lifecycle, earning classifications, system concepts, CFDI releases, ISN states, onboarding pause, pilot grants) and nothing statutory is editable outside them;
- readiness G1–G8 shows, per gate, which checklist items are met by code and which await evidence;
- A7 / OOS-6: a "no policy page" state instead of India's fallback, and a Mexico policy page if Mexico needs one; OOS-11 refusal wording; A13 SEPARACION classification decided as "refuse at approval".
Browser-check every screen touched.

### W6 — CFDI completeness

Build each A10 node whose inputs exist (`SubsidioAlEmpleo` after W1-6, `CompensacionSaldosAFavor` once its code is decided, `Incapacidades` after W3); A11 triple-rate overtime by recording hours per date; C11 time-zone rows (report options, do not decide). Keep every undecided item refused with its named code.

### W7 — Golden vectors (B21)

Once W1 makes a case computable end to end, author engineering golden vectors in `tests/fixtures/mx_golden/`: ordinary (weekly, quincenal, monthly), January/February UMA boundary, subsidy case, CEAV high band, minimum-wage geography, CDMX ISN, aguinaldo, vacation premium, finiquito, PTU, annual adjustment. Each vector's expected figures come from an **independent step-by-step calculation written from the sources** (not by running the engine), shown in the vector file with every source citation. Mark each `ENGINEERING — pending G1 confirmation against SUA / PAC / an independent payroll specialist`.

### W8 — Gate evidence packs

For each gate G1–G8, assemble the evidence the code can produce (test outputs, golden vectors, source manifest, verification log, screenshots, reports) into `docs/mexico/release-gates/G*/EVIDENCE_DRAFT.md`, clearly separating "produced by engineering" from "requires a human signature or external party". Never mark a gate signed.

## 3. Stop conditions — stop and ask only for these

1. A source's version in force for 2026 is doubtful, or two sources conflict on a value.
2. A G1-owner decision is required and **every** remaining step depends on it. Otherwise record the decision in `docs/mexico/DECISIONS_PENDING.md` (question, options, sources, what it blocks), keep the affected item blocked with a named code, and continue with other steps.
3. A failing test you cannot fix without changing another jurisdiction's behaviour.
4. Any action that would need push, merge, production access or credentials.
5. Machine resource exhaustion that persists after a clean rerun.

## 4. What you must not attempt (record as external in the register)

PAC adapter or sandbox (until a provider is chosen), CSD signing and GCP Secret Manager, SPEI bank files, IDSE/SUA/SIPARE transmission, legal decisions (hosting, retention, Q9), gate signatures, Rugvedh's reviews, the pilot organisation and parallel payroll, activating any pack, release or registry state.

## 5. Reporting

- Per step: a short section in `docs/mexico/MEXICO_COMPLETION_PROGRESS.md` (what changed, tests, production-effect table, ZP-PRIV flag if any, gap-register items closed).
- At the end, or when a stop condition applies: `docs/mexico/MEXICO_COMPLETION_REPORT.md` with
  1. every gap-register item and its final state (DONE / BLOCKED-ON-DECISION / BLOCKED-ON-SOURCE / EXTERNAL);
  2. `DECISIONS_PENDING.md` summarised for the G1 owner;
  3. the list of local commits, in order, each with its production effect and ZP-PRIV flag, so the associate can push and open PRs in reviewable pieces;
  4. what remains before pilot and before general availability.

Start with §0, then W1-1.

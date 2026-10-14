# Hong Kong activation readiness: what still blocks launch

**Measured 2026-10-14 08:59 UTC on a LOCAL scratch PostgreSQL database**, never production. The database was the production-schema copy upgraded to `d1e5a7c3b9f2` (code `nikhil` at `4c45af9`), with the canonical HK packs and templates seeded (both packs Draft). Raw output: `scratchpad/t5/task5_out.json`, SHA-256 `c83e62d3a7622f1e2bee8d8cb070ab1f73fab728cdcbe200f826f5fa65acb8fe`.

## 1. Golden-vector certification ("Test Certification" → "Run Now")

`POST /api/super-admin/compliance/test-certification/run` with `{"jurisdiction_country": "HK"}`, the same call the button makes:

| Result | Real cases | Passed | Failed |
|---|---|---|---|
| **PASS** | 11 | **11** | 0 |

## 2. Activation is refused, as designed

`POST /api/super-admin/compliance/hong-kong/service-registry` with `availability=AVAILABLE` returned **400**: "Hong Kong cannot be made AVAILABLE — **30 requirement(s) unmet**". The registry stayed **PLANNED**. Nothing was activated, and no pack was made Active. The list below is that refusal's exact list, grouped by gate.

| # | Unmet requirement (as the product states it) | Gate | Resolved by |
|---|---|---|---|
| 1 | G1 evidence accepted (HK-GATE-G1): EVIDENCE_REQUIRED | G1 | `SIGNOFF_PACKETS/01_HK_specialist.md`, then packet 09 (upload, independent review) |
| 2 | G2 evidence accepted (HK-GATE-G2) | G2 | packet 07 (credentials, conformance tests), then 09 |
| 3 | G3 evidence accepted (HK-GATE-G3) | G3 | packet 07 (two parallel cycles) + packet 05 (thresholds), then 09 |
| 4 | G4 evidence accepted (HK-GATE-G4) | G4 | packet 02 (QA lead), then 09 |
| 5 | G5 evidence accepted (HK-GATE-G5) | G5 | packets 03 (Security) and 04 (counsel), then 09 |
| 6 | G6 evidence accepted (HK-GATE-G6) | G6 | packet 05 (Payroll Ops), then 09 |
| 7 | G7 evidence accepted (HK-GATE-G7) | G7 | packet 08 (six signers), only after 1–6 |
| 8 | An Active HK rule pack in force today (none in force on 2026-10-14) | Pack | After G1: two Super Admins approve, then activate HK-PAYROLL-2026 v1.0 (four-eyes), in production |
| 9 | The in-force pack reproduces its golden vectors (no pack in force) | Pack | Follows from 8. The vectors already pass 11/11 (§1) |
| 10 | Production read-only verification and restore rehearsal recorded (HK-PRODUCTION-VERIFICATION) | Production | `ops/HK_DEPLOY_RUNBOOK.md` §1/§4 + packet 09 (verification output upload). **Blocked first by `ops/DEPLOY_FAILURE_4c5d6e7f8a9b.md`** |
| 11 | Owner decision D-1 recorded (eMPF submission interface at launch) | Decisions | packet 06 |
| 12 | D-2 recorded (retention period per data category) | Decisions | packet 06 after packet 04 |
| 13 | D-3 recorded (deletion vs anonymisation) | Decisions | packet 06 after packet 04 |
| 14 | D-4 recorded (encryption at rest) | Decisions | packet 06 after packet 03 |
| 15 | D-5 recorded (production HK identity-token secret) | Decisions | packet 06 after packet 03 |
| 16 | D-6 recorded (bilingual output) | Decisions | packet 06 |
| 17 | D-7 recorded (launch-scope exclusions) | Decisions | packet 06 |
| 18 | D-8 recorded (HK payroll-run approval four-eyes) | Decisions | packet 06 |
| 19 | D-9 recorded (legal-hold policy) | Decisions | packet 06 after packet 04 |
| 20 | D-10 recorded (privileged / assisted access policy) | Decisions | packet 06 after packet 03 |
| 21 | D-11 recorded (future-year template publication owner) | Decisions | packet 06 |
| 22 | HK_IDENTITY_TOKEN_KEY configured as a dedicated secret (D-5): not configured | Production config | `ops/HK_IDENTITY_TOKEN_KEY_provisioning.md` (Ops / Security) |
| 23 | BIR56A 2026/27: an Active template with reviewed source evidence and an independent approval | Templates | Super Admins: archive the IRD source, then approve / publish / activate (two people). Owner named by D-11 |
| 24 | IR56B 2026/27: same | Templates | same. **No 2026/27 version exists yet**; only 2025/26 is seeded |
| 25 | IR56E 2026/27: same | Templates | same (no 2026/27 version yet) |
| 26 | IR56F 2026/27: same | Templates | same (no 2026/27 version yet) |
| 27 | IR56G 2026/27: same | Templates | same (no 2026/27 version yet) |
| 28 | EMPF REMITTANCE 2026: same | Templates | same, plus the eMPF specification (G2) |
| 29 | MPF CONTRIBUTION RECORD 2026: same | Templates | same |
| 30 | TERMINATION STATEMENT 2026: same | Templates | same |

**In short:**
* 7 gates;
* 2 pack items (they follow from G1);
* 1 production verification, blocked first by the deploy failure;
* 11 owner decisions;
* 1 production secret;
* 8 Active templates, 4 of which need a 2026/27 version that does not exist yet.

Engineering can resolve none of these alone. Each needs a named person's evidence, decision or approval, and two Super Admins in production.

## 3. Re-checking after deploy

After a successful deploy, a Super Admin opens Hong Kong → Test Certification and clicks **Run Now**. Expect **PASS 11/11**, and then this same blocker list in Statutory Summary & Gates (fewer items as packets are signed and accepted).

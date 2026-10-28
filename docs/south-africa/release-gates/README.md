# South Africa Release Gates (G0–G7)

This directory defines the release gates for South Africa (ZA) per ZP-ZA-ENG-001 §13–§14.

## How a gate is signed
1. Upload evidence in the Super Admin → Sources tab with form number `ZA-GATE-Gn` (or `ZA-DECISION-D-n` for decisions).
2. A DIFFERENT Super Admin marks it reviewed — that counts as SIGNED / RECORDED.
3. The code checks are evaluated live by `south_africa_readiness.code_checks()`.
4. A gate is met only when all required evidence is reviewed by someone other than the uploader.
5. Nothing in code signs gates or records decisions — these are human acts on real evidence.

## Gates
| Gate | Owner | Exit condition |
|---|---|---|
| G0 | Engineering lead | Architecture, interfaces, data model, rule-pack contract, no duplicated country logic |
| G1 | Payroll/Tax lead + SA reviewer | Signed 2026/27 pack with all statutory content; zero unresolved production candidates |
| G2 | Product + Legal/Implementation | Supported cohort, BCEA/NMW/sector applicability, matrixes, unsupported cases blocked |
| G3 | Tax Ops | BRS-conformant export, EMP201/EMP501/IRP5 balancing, runbooks, rehearsals |
| G4 | Finance + Treasury | Bank connector validation, beneficiary controls, payment reconciliation, journals, recovery |
| G5 | Security + Privacy | POPIA posture, access controls, encryption, logging minimisation, retention/location, incident/DR tests |
| G6 | QA lead | Automated suites + golden fixtures + two parallel cycles, no unexplained material differences |
| G7 | CTO + Product + Tax Ops | Runbook, monitoring, support ownership, implementation checklist, rollback/freeze plan, signed go-live record |

## NO-GO conditions
- the current SARS deduction algorithm and test tables
- UIF/SDL/ETI eligibility semantics
- source-code/BRS validation
- the tax-directive workflow
- reconciliation balancing
- mandatory tax-reference handling
- sector/bargaining scope
- POPIA/data-location posture
- bank/payment recovery
- independent payroll/tax sign-off

The onboarding flag (`south_africa_dormancy.onboarding_enabled()`) is a deployment-only kill switch.

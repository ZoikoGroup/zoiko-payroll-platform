# Malaysia release gates

> **Superseded 2026-11-25 (gate removal, owner decision).** The release gates, evidence, sign-offs and parallel-run requirements described here no longer apply: this country goes live like Spain once its pack is Active. See `docs/GATE_REMOVAL.md` and `docs/malaysia/MALAYSIA_GAPS_AND_DECISIONS.md`. Kept for history.

Malaysia (ZP-MY-ENG-001) stays switched off (`MY_TENANT_ONBOARDING_ENABLED=False`, `MY_CANARY_ORG_IDS` empty) and its service availability stays PLANNED until every gate below passes and the launch-blocking owner decision D-8 (retention) is recorded. The service-registry step to AVAILABLE is refused by the server until then.

| Gate | Subject | Owner |
|---|---|---|
| [G1](G1.md) | Statutory content | Payroll Content + Malaysian payroll / tax specialist |
| [G2](G2.md) | Territory matrix and worker coverage | Product + Legal / Malaysian payroll specialist |
| [G3](G3.md) | Authority interfaces | Integration + Payroll Ops |
| [G4](G4.md) | PDPA and privacy | Security + Privacy |
| [G5](G5.md) | Parallel run | QA + Implementation |
| [G6](G6.md) | Operations | Payroll Ops |
| [G7](G7.md) | Commercial | Product / Management |

Each gate needs its checks green **and** its evidence `MY-GATE-Gn` reviewed by someone other than its uploader (G7 also needs the four `MY-SIGNOFF-*` documents).

The live state is the Super Admin Malaysia page's **Release gates** tab (and the `readiness` block of `GET /api/payroll/malaysia/summary`). The go-live order is in [`../RUNBOOK_GO_LIVE.md`](../RUNBOOK_GO_LIVE.md).

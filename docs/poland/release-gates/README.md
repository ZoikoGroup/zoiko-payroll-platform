# Poland release gates

> **Superseded 2026-11-25 (gate removal, owner decision).** The release gates, evidence, sign-offs and parallel-run requirements described here no longer apply: this country goes live like Spain once its pack is Active. See `docs/GATE_REMOVAL.md` and `docs/poland/POLAND_GAPS_AND_DECISIONS.md`. Kept for history.

Poland (ZP-PL-ENG-001) stays switched off (`PL_TENANT_ONBOARDING_ENABLED=False`, `PL_CANARY_ORG_IDS` empty) and its service availability stays PLANNED until every gate below passes and the launch-blocking owner decision D-7 (retention) is recorded. The service-registry step to AVAILABLE is refused by the server until then.

| Gate | Subject | Owner |
|---|---|---|
| [G1](G1.md) | Statutory content | Payroll Content + Polish payroll / tax specialist |
| [G2](G2.md) | Worker coverage | Product + Legal / Polish payroll specialist |
| [G3](G3.md) | Labour pay and benefits | Product + Polish payroll specialist |
| [G4](G4.md) | Filing and settlement | Integration + Payroll Ops |
| [G5](G5.md) | Security and privacy | Security + Privacy |
| [G6](G6.md) | Parallel payroll | QA + Implementation |
| [G7](G7.md) | Operations and commercial | Payroll Ops + Product / Management |

Each gate needs its checks green **and** its evidence `PL-GATE-Gn` reviewed by someone other than its uploader (G7 also needs the four `PL-SIGNOFF-*` documents).

The live state is the Super Admin Poland page's **Release gates** tab. The go-live order is in [`../RUNBOOK_GO_LIVE.md`](../RUNBOOK_GO_LIVE.md).

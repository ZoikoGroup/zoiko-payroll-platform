# New Zealand release gates

New Zealand (ZP-NZ-ENG-001) stays switched off (`NZ_TENANT_ONBOARDING_ENABLED=False`, `NZ_CANARY_ORG_IDS` empty) and its service availability stays PLANNED until every gate below passes and owner decisions D-1 to D-7 are recorded. The service-registry step to AVAILABLE is refused by the server until then.

| Gate | Subject | Owner |
|---|---|---|
| [G1](G1.md) | Statutory content signed (PAYE, ACC, KiwiSaver, student loan, child support) | Payroll / tax specialist |
| [G2](G2.md) | Holidays and leave content (public holidays, Holidays Act values) | Employment / leave specialist |
| [G3](G3.md) | Payday filing certified (IRD schema, deadlines, remittance dates) | Compliance (IRD gateway) |
| [G4](G4.md) | IRD-number security and privacy | Security lead |
| [G5](G5.md) | Parallel cycles accepted | Payroll operations |
| [G6](G6.md) | Operations ready (go-live runbook reviewed) | Operations / support lead |
| [G7](G7.md) | Launch sign-off (product, compliance, engineering, commercial) | CTO + commercial |

Each gate needs its checks green **and** its evidence `NZ-GATE-Gn` reviewed by someone other than its uploader (G7 also needs the four `NZ-SIGNOFF-*` documents).

The live state is the Super Admin New Zealand page's **Release gates** tab or `GET /api/payroll/new-zealand/readiness`. The go-live order is in [`../RUNBOOK_GO_LIVE.md`](../RUNBOOK_GO_LIVE.md).

# Japan release gates

Japan (ZP-JP-ENG-001) stays switched off (`JP_TENANT_ONBOARDING_ENABLED=False`) and its service availability stays PLANNED until every gate below passes and owner decisions D-1 to D-5 are recorded.

| Gate | Subject | Owner |
|---|---|---|
| [G0](G0.md) | Scope: monthly pay, resident employees | Engineering lead |
| [G1](G1.md) | National withholding and year-end tables signed | Payroll / tax lead |
| [G2](G2.md) | Corrections and due-date policies | Product + legal |
| [G3](G3.md) | Social-insurance grades, rates and care rules | Social-insurance specialist |
| [G4](G4.md) | Labour: minimum wages, premiums, holidays | Labour / HR lead |
| [G5](G5.md) | Filing export schemas certified | Compliance |
| [G6](G6.md) | My Number security and redaction | Security lead |
| [G7](G7.md) | Parallel cycles accepted | Payroll operations |
| [G8](G8.md) | Product, compliance and engineering sign-off | CTO |

The live state is `GET /api/payroll/japan/readiness` (organisation) or the Super Admin Japan page's Readiness tab.

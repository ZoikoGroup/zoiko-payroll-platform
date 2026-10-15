# Hong Kong sign-off packets: order and dependencies

Prepared by engineering on 2026-10-14. One file per person or role. Each packet says what to do, what to check, how long it should take, and which evidence it relies on (path + SHA-256). All sign-off lines are blank, and nobody has signed anything.

## Recommended completion order

| Step | Packet | Who | Can start now? | Blocked by |
|---|---|---|---|---|
| 1 | `02_QA_lead_G4.md` | QA lead | **Yes** | — |
| 1 | `01_HK_specialist.md` | HK payroll / statutory specialist | **Yes**, once engaged | Engaging a specialist (or the owner's optional exception in packet 06) |
| 1 | `03_Security_lead_G5.md` | Security / Privacy lead | **Yes** | F-10 needs the mail administrator |
| 1 | `04_Legal_counsel_retention.md` | Legal / privacy counsel | **Yes** | — |
| 1 | `05_Payroll_Ops_G6.md` | Payroll Operations lead | **Yes** | — |
| 2 | `06_Owner_D1_to_D14.md` | Product owner | Partly | D-2 / D-3 / D-9 wait for 04; D-4 / D-5 / D-10 wait for 03; the rest can be decided now |
| 2 | `09_SuperAdmin_upload_and_review.md` (upload drafts) | Super Admin A | After the deploy | `../ops/HK_DEPLOY_RUNBOOK.md` (which needs the 03 / 05 production items) |
| 3 | `07_Engineering_G2_G3_plan.md` | Engineering lead | Requests now; tests later | G2: D-1 (06) plus IRD / eMPF credentials. G3: thresholds (05), the deploy, and where parallel runs happen (owner + Security) |
| 4 | `09_SuperAdmin_upload_and_review.md` (review B) | Super Admin B | As signed versions arrive | Each gate's packet signed (01–07) |
| 5 | `08_G7_launch_signers.md` | Six signers | **No** | G1–G6 ACCEPTED, D-1 to D-11 recorded, production verification uploaded |

## Dependency map

```
01 Specialist ─────────────┐
02 QA ─────────────────────┤
03 Security ──┬─> 06 Owner (D-4, D-5, D-10) ─┐
04 Counsel ───┴─> 06 Owner (D-2, D-3, D-9) ──┼─> 09 B reviews ─> 08 G7 signers
05 Payroll Ops ─┬──────────────────────────────┤
                └─> 07 G3 thresholds ─┐       │
06 Owner D-1 ─────> 07 G2 credentials ┴─> G2/G3 results ┘
deploy (HK_DEPLOY_RUNBOOK) ─> 09 A uploads drafts
```

## Packets

* `01_HK_specialist.md` — SHA-256 `146c2b3dba0e47684ec4322dc3f7c1136d3da451a094f25408aad9f17554ef35`
* `02_QA_lead_G4.md` — SHA-256 `239c19df7ce31fa46b9e228358d5bee00e71cfb3b4dfcbf356c734d9ea34e91d`
* `03_Security_lead_G5.md` — SHA-256 `542949bdc7d02823ce94ab64d0abb964cb71fb57b5afe2644967b8fa9d346318`
* `04_Legal_counsel_retention.md` — SHA-256 `4172eacf6477822d3512d1c1547a43e289f3a100eda0d69f3933b815c27c4b4b`
* `05_Payroll_Ops_G6.md` — SHA-256 `9043f63defc7cdde11f0b8fdaecec4beacade28336ede31dca0414609a1c118c`
* `06_Owner_D1_to_D14.md` — SHA-256 `3d4bd70db81ad62550756e1bd8dbc046512196d551c599b0d32d4eb51eb69a22`
* `07_Engineering_G2_G3_plan.md` — SHA-256 `3a0964bc4cf648d0a14877425691bd849dd5a4c4be5eee1ea46e0a0f2803bc39`
* `08_G7_launch_signers.md` — SHA-256 `de7cff9ce6f6f8adce7abbb915416c41b70a30d8ab583f38404763505355bbd3`
* `09_SuperAdmin_upload_and_review.md` — SHA-256 `8833ca945dee2703c8ef0e168dafa5ec20971d11eae7b9fd4bfe335a22f1715c`

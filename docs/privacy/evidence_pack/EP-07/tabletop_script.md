# Tabletop script: suspected support-operator access to tenant PII (F04 / HP-08)

Status: awaiting Security lead proof (HP-08). Not yet run.
Duration: 75 minutes (60-90). Format: discussion with an optional live drill on staging.
Use only synthetic tenants: PRIVA (tenant A) and PRIVB (tenant B) as defined in
`backend/tests/privacy/conftest.py`, or tenants created by `backend/scripts/generate_synthetic_data.py`
(codes `SYN001`...). Never use production data, production tenant names or real people.

## Participants

| Role | Person (fill in) |
|---|---|
| Facilitator | |
| Incident commander (Security lead) | |
| Evidence lead (platform_security) | |
| Engineering on-call | |
| DPO / counsel | |
| Customer Success | |
| Observer / note taker | |

## Synthetic cast

| Persona | Description |
|---|---|
| SP | support_operator `sp@platform.example` |
| APP / PS2 | platform_security officers `app@platform.example`, `ps2@platform.example` |
| TA | org_admin of PRIVA `ta@tenant-a.example` |
| TB | org_admin of PRIVB `tb@tenant-b.example` |
| A1, A2, B1 | synthetic workers |

## Timeline and injects

| Time | Inject | Expected discussion / actions | Playbook section |
|---|---|---|---|
| 00:00 | Brief: rules, synthetic only, objectives (detect, preserve, contain, assess, communicate) | | |
| 00:05 | **Inject 1.** 02:14Z: alert `unscheduled_elevation` for a support grant on PRIVA, requested by SP, approved by TA. | Is a night-time grant legitimate? Who checks the ticket reference? Open INC record. | 1, 2 |
| 00:15 | **Inject 2.** 02:21Z: alert `employee_enumeration`: the temporary login touched 31 distinct employee ids in 9 minutes; grant scope was 3 employees. Security events show 28 `PDP_DENY OBJECT_NOT_IN_SCOPE` and 3 `PRIVILEGED_READ`. | Severity? Were data returned beyond scope? How to prove from `result=allow` rows. | 2 |
| 00:25 | **Inject 3.** IC asks for containment. | Revoke grant (platform_security route, reason). Who deactivates SP? Run JML reconciliation. Verify the old token is refused (T08 behaviour). | 4 |
| 00:35 | **Inject 4.** Evidence lead calls `GET /api/super-admin/security-events/verify` and it returns `ok: false, broken_at: <id>`. | Tampering or a concurrent-write fork (finding N6)? Compare with the external anchor. Preserve everything; nobody touches audit tables. | 3 |
| 00:45 | **Inject 5.** TA emails: "Our employee A1 says a Zoiko person called and knew her bank details." | Now S1. DPO joins. Facts for counsel: which field classes were readable under the grant? Awareness time (Z). | 5 |
| 00:55 | **Inject 6.** A second alert: `large_export` for a payroll_admin of PRIVB at 02:30Z. | Related or separate? Tenant-side user acting within its own tenant: whose incident? Customer is controller. | 2, 5 |
| 01:05 | **Inject 7.** Counsel asks for draft customer notice for PRIVA. | Draft without worker data. Who approves? Update cadence. | 6 |
| 01:10 | Hot wash: what worked, what failed, actions with owners | | 7 |
| 01:15 | Close | | |

## Optional live drill (staging only)

1. `POST /api/super-admin/alert-rules/unscheduled_elevation/test-fire` (drill alert, `is_drill=true`).
2. Confirm the alert appears on the Alerts page and in the configured mailbox.
3. Acknowledge it: `POST /api/super-admin/alert-events/{alert_id}/acknowledge`.
4. Run `GET /api/super-admin/security-events/verify` and record the result.
5. Record ids and UTC times in the record template.

## Facilitator questions bank

- Who could have approved this grant, and could the requester have approved it (C02)?
- If `SECURITY_ALERT_EMAILS` is empty, who sees the alert at 02:14Z (DEC-10 single channel)?
- Which logs outside the app would show a DBA reading the same rows (HP-01)?
- How long are anchors retained and who can delete them (HP-04)?

Record the exercise in `tabletop_record_template.md`.

# Report templates: four-eyes rules

> **Maker-checker change. Requires ZP-PRIV review (Rugvedh) before merge.**
> Introduced 2026-11-18 (migration `d7a3f1c9e5b2`, `service.report_template_four_eyes_refusal`).

These rules apply to the shared report-template lifecycle (Draft → Review → Approved → Published → Active → Superseded) in every country. Each country's own activation gate (`template_activation_refusal` hook) is unchanged.

At Active, the checks run in this order:
1. R1 and R2.
2. The country hook. Its own rule and message win.
3. R3.

## Who counts as the content editor

`payroll_report_templates.content_editor_id` records the last Super Admin who changed the template's **content**: its metadata, components or fields.

- Status changes (including Published) and Approve never change it.
- When the seed or a system process writes the content, the content editor is none.
- `updated_by_id` still records the last actor of *any* change, but no rule reads it any more.

**Why this changed:** the rules used to read `updated_by_id`. Every status change overwrote it, so an approver who also clicked Published became the "editor". Approver and editor were then the same person, and Active was refused for everyone (the "Published trap").

## The rules

| # | Rule | Where it is checked | Countries |
|---|---|---|---|
| R1 | No self-approval: the approver must not be the last content editor | Published and Active in every country; also at Approve for `_SELF_APPROVAL_REFUSED_COUNTRIES` (elsewhere a self-approval is recorded but refused at Published, as before) | all |
| R2 | Published needs a recorded approver | Published, Active | all (unchanged) |
| R3 | The approver may not activate | Active | `_APPROVER_NOT_ACTIVATOR_COUNTRIES`, the same opt-in list as packs |

**R3 is not applied everywhere.** Outside the opt-in list, the approver may still activate. That keeps the owner decision of 2026-09-28 ("checker approves and activates"). To apply R3 everywhere, a reviewer must widen it on purpose.

**Unchanged:** the HK/MX rule that *any* editor of a version may not approve it (`_ANY_EDITOR_APPROVAL_REFUSED_COUNTRIES`).

Every refusal names the rule that failed and who may take the next step.

## Recovering stuck templates

Templates stuck in Published because their approver also clicked Published are recovered by the migration's backfill. No manual data edits are needed.

**The backfill uses the audit log only, never `updated_by_id`.** For each template it takes the actor of the latest content-change row. If that row was written by the seed, or if there is no content-change row, the content editor is none.

**After deploying:**
- A template whose approver did not edit its content can be activated by another Super Admin.
- In countries outside the R3 list, the approver can also activate it.
- Statuses are never changed automatically: activation stays a manual, four-eyes step.

**Before and after deploying, run the read-only dry run:** `python -m scripts.report_stuck_published_templates` (from `backend/`). It lists each stuck template with the content editor the backfill gives it and who may activate it, in three groups:
- **A.** Can be activated after the fix.
- **B.** Still blocked by the country's own activation gate. This fix doesn't change that, and the hook's own reason is shown.
- **C.** Still blocked by four-eyes, because the approver is also the content editor. To recover: make a new version, have a different Super Admin approve it, publish and activate it, then supersede the old one.

# Singapore — Release Checklist

For the release owner and deploy owner. Tick in order. A step marked *(external)* can't be completed by engineering.
The detailed steps are in `SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md`; the evidence owners and criteria are in `SINGAPORE_EXTERNAL_EVIDENCE_HANDOFF.md`.

## 1. Code review and merge

- [ ] Review the staged Singapore change set (`scratchpad/stage_list.txt`, 65 files). Review the shared files hunk by hunk (`SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md` §B).
- [ ] Confirm the excluded files are **not** staged (`scratchpad/excluded_list.txt`): Germany files and DOCX, CORS, unrelated accessibility, `SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md`.
- [ ] CI is green, meaning the full backend `pytest tests/` passes (reference: 3,308 passed, 7 skipped).
- [ ] Frontend `vite build` passes.
- [ ] `alembic heads` returns exactly `445abd6a9083`.
- [ ] Commit, push and merge (release owner).

## 2. Deployment *(deploy owner)*

- [ ] Review the `scripts/deploy_migrate.sh` safety fix.
- [ ] Take a backup, then complete the restore rehearsal (runbook §B–C).
- [ ] Identify the database's revision read-only. If it isn't `998877665544` or `445abd6a9083`, **stop**. Never `alembic stamp`.
- [ ] Migrate (runbook §D).
- [ ] Readiness → Database is `PASS`.
- [ ] Readiness → Migration is `PASS`.
- [ ] Run both seed commands **twice** (runbook §E). The second run's audit shows `rowChanges` 0 / 0.
- [ ] The SG registry is still `PLANNED`.
- [ ] Record the golden-vector run (runbook §F): 37/37.

## 3. Evidence and decisions *(external)*

- [ ] Record D1, D2 and D3 in the product (option plus reason), upload each signed memo, and have a second Super Admin accept it. Each shows `DECISION_RECORDED`.
- [ ] Gather G1–G8 evidence: each artifact uploaded and accepted by a second Super Admin. Each gate shows `PASS`, with no `EXPIRED` or `REJECTED` left.
- [ ] Close or formally scope out the MOM data items (handoff §4).
- [ ] If D1 is not EXPORT_ONLY: complete the AIS-API 2.0 onboarding.

## 4. Activation *(release owner, maker-checker)*

- [ ] Pack approved by Super Admin B, then activated by Super Admin C (runbook §G–H).
- [ ] All 11 templates promoted to Active (runbook §I).
- [ ] Test tenant scenario and audit check (runbook §J–K).
- [ ] Readiness dashboard: every category is `PASS` except the registry-dependent production-activation row.
- [ ] Switch the registry to `AVAILABLE` (runbook §L). This is the **only** step that opens onboarding.
- [ ] Monitor the first two payroll cycles (runbook §M). The rollback plan (§N) is understood by the on-call owner.

## Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Release owner | | | |
| Deploy owner | | | |
| Statutory compliance owner | | | |
| DPO | | | |
| Product owner | | | |

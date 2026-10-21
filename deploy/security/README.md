# deploy/security

Status: **templates - awaiting Infrastructure owner, not applied.** Nothing in this folder has been run
against any GCP project. Review, adapt the placeholder values, run `terraform plan` in a scratch project,
then apply under change control.

| File | Purpose | Control / proof |
|---|---|---|
| `iam_roles.tf` | Service accounts for the application runtime and CI deployer (least privilege, no keys); PAM entitlements (max 30 min, independent approver) for DBA break-glass, cloud console admin and production shell; fallback time-bound IAM condition; project audit logging | D01 / HP-01 |
| `backup_iam.tf` | Backup / snapshot bucket: uniform bucket-level access, public access prevention, CMEK placeholder, retention policy, writer = create-only SA, readers = restore operators only, data-access audit logs | D02 / HP-02 |
| `anchor_bucket.tf` | Security-event anchor bucket with a LOCKED 7-year retention policy (DEC-7, irreversible), versioning, create-only writer (`GcsRetentionSink`); output feeds `SECURITY_ANCHOR_BUCKET` | E02 / HP-04 |
| `pam_runbook.md` | JIT privileged access flow with session recording, approval, 30-minute maximum, reviews, proof record | D01 / HP-01 |

Related:
- `deploy/scripts/restore_drill.sh` - restore drill proving RLS and tenant segregation after restore (HP-02).
- `docs/privacy/rls_runbook.md` - NOBYPASSRLS application role and migration owner role (HP-03).

Usage:

```sh
cd deploy/security
terraform init
terraform plan -var project_id=<project> -out plan.bin   # review with Security lead
# apply only under an approved change
```

The three `.tf` files form one module (shared `project_id`, `app_runtime` service account). Notes:
- If the database is Neon, provider-native backups and roles are managed in Neon; `backup_iam.tf` then
  covers logical dumps and drill artefacts only. Record the Neon settings in the HP-02 proof.
- The application currently documents `roles/storage.objectAdmin` on the uploads bucket
  (`GCP_DEPLOYMENT.md`); narrow it to `objectCreator` + `objectViewer` on that bucket when applying.
- Nothing in the application schedules the anchor job yet; HP-04 needs both the bucket and the job.

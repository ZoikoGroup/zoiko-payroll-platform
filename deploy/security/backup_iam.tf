# deploy/security/backup_iam.tf
# -----------------------------------------------------------------------------
# TEMPLATE - awaiting Infrastructure owner. NOT APPLIED. Review every value.
# ZP-PRIV-VERIFY-001 control D02 / proof HP-02.
#
# Bucket for logical backups (pg_dump), snapshot exports and restore-drill
# artefacts. Provider-native backups (Neon PITR / branches, Cloud SQL backups)
# are configured in the provider and must have equivalent restrictions:
# document them in the HP-02 proof record.
#
#   * uniform bucket-level access, public access prevention enforced
#   * CMEK (placeholder key) in the tenant data region
#   * retention policy (not locked here; lock after the first review)
#   * readers: restore-operator group only; writer: backup service account only
#   * data-access audit logs on
# -----------------------------------------------------------------------------

variable "backup_bucket_name" {
  type        = string
  description = "Globally unique bucket name (placeholder)."
  default     = "zp-payroll-backups-eu-example"
}

variable "backup_location" {
  type        = string
  description = "Bucket location; must equal the tenant data region (region_policy.md)."
  default     = "EUROPE-WEST1"
}

variable "backup_kms_key" {
  type        = string
  description = "CMEK: projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k> (placeholder)."
  default     = "projects/PROJECT/locations/europe-west1/keyRings/zp-backups/cryptoKeys/zp-backups"
}

variable "backup_retention_days" {
  type        = number
  description = "Minimum retention of backup objects."
  default     = 35
}

variable "restore_operators_group" {
  type    = string
  default = "group:zp-restore-operators@example.com"
}

resource "google_service_account" "backup_writer" {
  project      = var.project_id
  account_id   = "zp-backup-writer"
  display_name = "Writes database backups (no read, no delete)"
}

resource "google_storage_bucket" "backups" {
  project                     = var.project_id
  name                        = var.backup_bucket_name
  location                    = var.backup_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  encryption {
    default_kms_key_name = var.backup_kms_key
  }

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = var.backup_retention_days * 86400
    is_locked        = false # lock only after HP-02 review
  }

  lifecycle_rule {
    condition {
      age = 400
    }
    action {
      type = "Delete"
    }
  }

  logging {
    log_bucket = "${var.backup_bucket_name}-access-logs"
  }

  labels = {
    data_class = "worker"
    control    = "zp-priv-d02"
  }
}

# Writer: create objects only.
resource "google_storage_bucket_iam_member" "backup_writer_create" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.backup_writer.email}"
}

# Readers: restore operators only. Recommended: grant this through a PAM
# entitlement (pam_runbook.md) rather than a standing binding.
resource "google_storage_bucket_iam_member" "restore_operators_read" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectViewer"
  member = var.restore_operators_group
}

# The application runtime gets nothing on this bucket.

# KMS: the bucket's service agent may use the key; nobody else gets decrypt.
data "google_storage_project_service_account" "gcs_agent" {
  project = var.project_id
}

resource "google_kms_crypto_key_iam_member" "backup_key_gcs_agent" {
  crypto_key_id = var.backup_kms_key
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs_agent.email_address}"
}

# Data-access audit logging for Cloud Storage (who read which backup).
resource "google_project_iam_audit_config" "storage_data_access" {
  project = var.project_id
  service = "storage.googleapis.com"
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

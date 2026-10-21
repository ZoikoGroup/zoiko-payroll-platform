# deploy/security/anchor_bucket.tf
# -----------------------------------------------------------------------------
# TEMPLATE - awaiting Infrastructure owner. NOT APPLIED. Review every value.
# ZP-PRIV-VERIFY-001 control E02 / proof HP-04.
#
# External anchor store for the security_events hash chain
# (app/modules/security/events.py: GcsRetentionSink writes
# security-anchors/anchor-<id>-<hash16>.json with if_generation_match=0).
# The application reads SECURITY_ANCHOR_BUCKET.
#
# WARNING: a LOCKED retention policy cannot be shortened or removed, and the
# bucket cannot be deleted until every object has aged out (7 years, DEC-7).
# Apply is irreversible. Test with is_locked = false in a scratch project first.
#
# Note: at time of writing nothing in the code base schedules anchor();
# HP-04 also needs that job to be added (see indirect_paths_audit.md, N7).
# -----------------------------------------------------------------------------

variable "anchor_bucket_name" {
  type    = string
  default = "zp-security-anchors-eu-example"
}

variable "anchor_location" {
  type    = string
  default = "EUROPE-WEST1"
}

variable "anchor_retention_years" {
  type    = number
  default = 7 # DEC-7
}

variable "anchor_lock_retention" {
  type        = bool
  description = "true = LOCKED (irreversible). Set only after review."
  default     = true
}

resource "google_service_account" "anchor_writer" {
  project      = var.project_id
  account_id   = "zp-anchor-writer"
  display_name = "Writes security-event anchors (create only)"
}

resource "google_storage_bucket" "anchors" {
  project                     = var.project_id
  name                        = var.anchor_bucket_name
  location                    = var.anchor_location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = var.anchor_retention_years * 365 * 86400
    is_locked        = var.anchor_lock_retention
  }

  logging {
    log_bucket = "${var.anchor_bucket_name}-access-logs"
  }

  labels = {
    data_class = "security"
    control    = "zp-priv-e02"
  }
}

# Writer: objectCreator only - no overwrite, no delete, no read.
resource "google_storage_bucket_iam_member" "anchor_writer_create" {
  bucket = google_storage_bucket.anchors.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.anchor_writer.email}"
}

# GcsRetentionSink uses Application Default Credentials. Either run the anchor
# job as zp-anchor-writer (impersonation below), or set
# anchor_writer_is_app_runtime = true to give the runtime SA the same
# create-only role. Never grant objectAdmin / objectUser here.
variable "anchor_writer_is_app_runtime" {
  type    = bool
  default = false
}

resource "google_service_account_iam_member" "runtime_impersonates_anchor_writer" {
  count              = var.anchor_writer_is_app_runtime ? 0 : 1
  service_account_id = google_service_account.anchor_writer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.app_runtime.email}"
}

resource "google_storage_bucket_iam_member" "runtime_anchor_create" {
  count  = var.anchor_writer_is_app_runtime ? 1 : 0
  bucket = google_storage_bucket.anchors.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.app_runtime.email}"
}

# Readers: platform security (verification during incidents and reviews).
variable "anchor_readers_group" {
  type    = string
  default = "group:zp-platform-security@example.com"
}

resource "google_storage_bucket_iam_member" "anchor_readers" {
  bucket = google_storage_bucket.anchors.name
  role   = "roles/storage.objectViewer"
  member = var.anchor_readers_group
}

output "security_anchor_bucket" {
  description = "Value for SECURITY_ANCHOR_BUCKET."
  value       = google_storage_bucket.anchors.name
}

output "anchor_writer_service_account" {
  value = google_service_account.anchor_writer.email
}

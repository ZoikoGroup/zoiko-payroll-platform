# deploy/security/iam_roles.tf
# -----------------------------------------------------------------------------
# TEMPLATE - awaiting Infrastructure owner. NOT APPLIED. Review every value.
# ZP-PRIV-VERIFY-001 control D01 / proof HP-01.
#
# Separates privileged infrastructure access from the application:
#   * DBA break-glass, cloud console admin and production shell are GROUPS whose
#     members get NO standing binding: access is granted just-in-time through
#     GCP Privileged Access Manager (PAM) entitlements (max 30 minutes) or, where
#     PAM is not available, through time-bound IAM conditions added by the
#     approval workflow (see pam_runbook.md).
#   * CI deployer and application runtime are SERVICE ACCOUNTS with least
#     privilege and no human keys.
# -----------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.30"
    }
  }
}

variable "project_id" {
  type        = string
  description = "Production GCP project id."
}

variable "region" {
  type        = string
  description = "Home region of this deployment (matches settings.DATA_REGION)."
  default     = "europe-west1"
}

variable "org_domain" {
  type        = string
  description = "Google Workspace / Cloud Identity domain for groups (placeholder)."
  default     = "example.com"
}

variable "jit_window_start" {
  type        = string
  description = "RFC3339 UTC start of a pre-approved time-bound grant (only when PAM is unavailable)."
  default     = "2026-01-01T00:00:00Z"
}

variable "jit_window_end" {
  type        = string
  description = "RFC3339 UTC end; must be <= start + 30 minutes."
  default     = "2026-01-01T00:30:00Z"
}

locals {
  groups = {
    dba_breakglass = "group:zp-dba-breakglass@${var.org_domain}"
    console_admin  = "group:zp-cloud-console-admin@${var.org_domain}"
    prod_shell     = "group:zp-prod-shell@${var.org_domain}"
    pam_approvers  = "group:zp-platform-security@${var.org_domain}"
    restore_ops    = "group:zp-restore-operators@${var.org_domain}"
  }
}

# ── Service accounts ─────────────────────────────────────────────────────────

resource "google_service_account" "app_runtime" {
  project      = var.project_id
  account_id   = "zp-app-runtime"
  display_name = "Zoiko Payroll application runtime (VM / workers)"
}

resource "google_service_account" "ci_deployer" {
  project      = var.project_id
  account_id   = "zp-ci-deployer"
  display_name = "Zoiko Payroll CI deployer (GitHub OIDC, no keys)"
}

# Application runtime: only what the app needs. Bucket-level grants for the
# uploads bucket and the anchor bucket live next to those buckets
# (anchor_bucket.tf grants objectCreator only). No project-wide storage role.
resource "google_project_iam_member" "app_runtime_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.app_runtime.email}"
}

resource "google_project_iam_member" "app_runtime_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.app_runtime.email}"
  condition {
    title       = "zoiko-payroll-secrets-only"
    description = "Only secrets named zoiko-payroll-*"
    expression  = "resource.name.startsWith(\"projects/${var.project_id}/secrets/zoiko-payroll-\")"
  }
}

# CI deployer: may reach the VM through IAP with OS Login as a non-admin user.
# It cannot read databases, buckets or secrets.
resource "google_project_iam_member" "ci_iap_tunnel" {
  project = var.project_id
  role    = "roles/iap.tunnelResourceAccessor"
  member  = "serviceAccount:${google_service_account.ci_deployer.email}"
}

resource "google_project_iam_member" "ci_os_login" {
  project = var.project_id
  role    = "roles/compute.osLogin"
  member  = "serviceAccount:${google_service_account.ci_deployer.email}"
}

# ── Privileged human access: JIT through PAM (preferred) ─────────────────────
# Requires the Privileged Access Manager API. Max duration 30 minutes,
# approval by a platform_security member other than the requester,
# justification required.

resource "google_privileged_access_manager_entitlement" "prod_shell" {
  provider             = google
  entitlement_id       = "zp-prod-shell"
  location             = "global"
  parent               = "projects/${var.project_id}"
  max_request_duration = "1800s"

  eligible_users {
    principals = [local.groups.prod_shell]
  }

  privileged_access {
    gcp_iam_access {
      resource_type = "cloudresourcemanager.googleapis.com/Project"
      resource      = "//cloudresourcemanager.googleapis.com/projects/${var.project_id}"
      role_bindings {
        role = "roles/compute.osAdminLogin"
      }
      role_bindings {
        role = "roles/iap.tunnelResourceAccessor"
      }
    }
  }

  requester_justification_config {
    unstructured {}
  }

  approval_workflow {
    manual_approvals {
      require_approver_justification = true
      steps {
        approvals_needed = 1
        approvers {
          principals = [local.groups.pam_approvers]
        }
      }
    }
  }
}

resource "google_privileged_access_manager_entitlement" "console_admin" {
  provider             = google
  entitlement_id       = "zp-console-admin"
  location             = "global"
  parent               = "projects/${var.project_id}"
  max_request_duration = "1800s"

  eligible_users {
    principals = [local.groups.console_admin]
  }

  privileged_access {
    gcp_iam_access {
      resource_type = "cloudresourcemanager.googleapis.com/Project"
      resource      = "//cloudresourcemanager.googleapis.com/projects/${var.project_id}"
      role_bindings {
        role = "roles/editor" # review: narrow to the roles actually needed
      }
    }
  }

  requester_justification_config {
    unstructured {}
  }

  approval_workflow {
    manual_approvals {
      require_approver_justification = true
      steps {
        approvals_needed = 1
        approvers {
          principals = [local.groups.pam_approvers]
        }
      }
    }
  }
}

# DBA break-glass: for Cloud SQL use roles/cloudsql.client + a DB login that is
# itself NOT the application role; for Neon, the DBA credential is held in
# Secret Manager and only readable while this entitlement is active.
resource "google_privileged_access_manager_entitlement" "dba_breakglass" {
  provider             = google
  entitlement_id       = "zp-dba-breakglass"
  location             = "global"
  parent               = "projects/${var.project_id}"
  max_request_duration = "1800s"

  eligible_users {
    principals = [local.groups.dba_breakglass]
  }

  privileged_access {
    gcp_iam_access {
      resource_type = "cloudresourcemanager.googleapis.com/Project"
      resource      = "//cloudresourcemanager.googleapis.com/projects/${var.project_id}"
      role_bindings {
        role                 = "roles/secretmanager.secretAccessor"
        condition_expression = "resource.name.startsWith(\"projects/${var.project_id}/secrets/zoiko-payroll-dba-\")"
      }
      role_bindings {
        role = "roles/cloudsql.client"
      }
    }
  }

  requester_justification_config {
    unstructured {}
  }

  approval_workflow {
    manual_approvals {
      require_approver_justification = true
      steps {
        approvals_needed = 1
        approvers {
          principals = [local.groups.pam_approvers]
        }
      }
    }
  }
}

# ── Fallback: time-bound IAM condition (only when PAM cannot be used) ────────
# Created by the approval workflow for one window, then removed. Disabled by
# default (count = 0).
variable "enable_fallback_timebound_shell" {
  type    = bool
  default = false
}

variable "fallback_member" {
  type        = string
  description = "user:<engineer>@example.com for one approved window."
  default     = "user:engineer@example.com"
}

resource "google_project_iam_member" "fallback_timebound_shell" {
  count   = var.enable_fallback_timebound_shell ? 1 : 0
  project = var.project_id
  role    = "roles/compute.osAdminLogin"
  member  = var.fallback_member
  condition {
    title       = "jit-window"
    description = "Approved JIT window (max 30 minutes)"
    expression  = "request.time >= timestamp(\"${var.jit_window_start}\") && request.time < timestamp(\"${var.jit_window_end}\")"
  }
}

# ── Audit logging for privileged activity ────────────────────────────────────
resource "google_project_iam_audit_config" "all_services" {
  project = var.project_id
  service = "allServices"
  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

output "app_runtime_service_account" {
  value = google_service_account.app_runtime.email
}

output "ci_deployer_service_account" {
  value = google_service_account.ci_deployer.email
}

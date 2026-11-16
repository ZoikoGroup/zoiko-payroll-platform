"""What the Mexico CFDI lifecycle migration b5e1c7d9a3f2 adds, as the deploy
drift filter (scripts/drift_pending_filter.pending_objects) reports it — shared
by the earlier migrations' "explains every pending object" tests."""

MX_LIFECYCLE_TABLES = {"payroll_mx_document_access_events"}
MX_LIFECYCLE_COLUMNS = {
    "payroll_mx_cfdi_documents": {"event_key", "document_subtype", "state_code", "snapshot_hash", "ruleset_version",
                                  "issuing_cert_token", "document_locale", "published_at", "delivery_status",
                                  "cancel_outcome", "employer_profile_id"},
    "payroll_mx_cfdi_schema_releases": {"effective_from", "effective_to"},
}

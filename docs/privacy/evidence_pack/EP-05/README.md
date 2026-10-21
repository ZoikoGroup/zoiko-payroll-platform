# EP-05 - Audit samples, alert drill and immutability configuration

Generated 2026-10-19T10:05:20Z. Status: awaiting independent review.

- alert_drill.json comes from python -m scripts.alert_drill (synthetic database).
- A live drill (--live) on the deployment is a human proof.

Files (sha256 in manifest.json):

- `alert_drill.json`
- `alert_rules.json`
- `audit_samples/E02_tamper_detected.json`
- `audit_samples/PG_security_events_tamper.json`
- `audit_samples/T12_attribution_and_drill.json`
- `immutability_configuration.json`
- `redaction_samples/D03_log_sample_payroll_run.txt`
- `redaction_samples/D04_sentry_sample.json`

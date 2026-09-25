"""
modules/communications
----------------------
Shared outbound-communication infrastructure used by every module that sends
email (auth, organizations, billing, payroll, super_admin, assist).

One audit table (communication_events), one dispatch entry point
(service.dispatch_email) and one scheduler (service.queue_email). Modules
must route every send through here rather than re-implementing their own
audit/idempotency/retry handling.
"""

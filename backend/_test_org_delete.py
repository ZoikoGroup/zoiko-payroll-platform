import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "test_delete.sqlite3")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import Base, engine, SessionLocal
import app.modules.auth.models
import app.modules.organizations.models
import app.modules.super_admin.models
import app.modules.payroll.models
import app.modules.payroll.policy.models
import app.modules.payroll.enterprise.models
import app.modules.payroll.mail.models

Base.metadata.create_all(bind=engine)
db = SessionLocal()

Q = lambda sql, **kw: db.execute(text(sql), kw)  # noqa: E731

OID = Q("INSERT INTO organizations (organization_code, organization_name, is_active, created_at, updated_at) "
        "VALUES (:c,:n,:a,:t,:t) RETURNING id",
        c="TST", n="Test Org", a=1, t="2026-01-01 00:00:00").scalar()

Q("INSERT INTO users (email, hashed_password, role, organization_id, first_name, last_name, phone, is_active, is_verified, created_at, updated_at) "
  "VALUES (:e,:p,:r,:o,:f,:l,:ph,:a,:v,:t,:t)",
  e="admin@tst.com", p="x", r="org_admin", o=OID, f="A", l="B", ph="", a=1, v=1, t="2026-01-01 00:00:00")
Q("INSERT INTO security_action_tokens (email, organization_id, purpose, token_hash, expires_at, created_at) "
  "VALUES (:e,:o,:p,:t,:x,:c)",
  e="admin@tst.com", o=OID, p="password_reset", t="tok", x="2099-01-01 00:00:00", c="2026-01-01 00:00:00")

EID = Q("INSERT INTO payroll_employees (organization_id, employee_code, name, email, status, employment_type) "
        "VALUES (:o,:c,:n,:e,:s,:et) RETURNING id",
        o=OID, c="E1", n="Employee One", e="e@tst.com", s="active", et="full_time").scalar()

Q("INSERT INTO payroll_company_compliance (organization_id) VALUES (:o)", o=OID)
Q("INSERT INTO payroll_contribution_rates (organization_id, jurisdiction_country, component_key, label, employee_share, employer_share, total, employee_rate_pct, employer_rate_pct) "
  "VALUES (:o,:j,:k,:l,:es,:er,:t,:ep,:rp)",
  o=OID, j="IN", k="pf", l="Provident Fund", es="12%", er="12%", t="24%", ep=0.12, rp=0.12)
Q("INSERT INTO payroll_tax_slabs (organization_id, jurisdiction_country, min_amount, max_amount, rate_pct, rate_label, tax_formula) "
  "VALUES (:o,:j,:mi,:mx,:r,:l,:f)",
  o=OID, j="IN", mi=0, mx=250000, r=0, l="Nil", f="Nil")
Q("INSERT INTO payroll_holidays (organization_id, country, date, name) VALUES (:o,:c,:d,:n)",
  o=OID, c="IN", d="2026-01-26", n="Republic Day")
Q("INSERT INTO payroll_leave_allocations (organization_id, employee_id, leave_balances) VALUES (:o,:e,:b)",
  o=OID, e=EID, b="{}")
Q("INSERT INTO payroll_leave_requests (organization_id, employee_id, leave_type, start_date, end_date, days, status, source) "
  "VALUES (:o,:e,:t,:s,:ed,:d,:st,:src)",
  o=OID, e=EID, t="paid", s="2026-01-01", ed="2026-01-01", d=1, st="pending", src="manual")
Q("INSERT INTO payroll_compliance_documents (organization_id, title, document_type, category, file_path, file_name, country, status) "
  "VALUES (:o,:ti,:t,:c,:fp,:fn,:co,:s)",
  o=OID, ti="Aadhaar", t="aadhaar", c="other", fp="/tmp/a", fn="a.pdf", co="IN", s="processed")
Q("INSERT INTO payroll_activity_log (organization_id, description, status) VALUES (:o,:d,:s)",
  o=OID, d="seeded", s="success")
Q("INSERT INTO payroll_custom_field_definitions (organization_id, field_key, label, field_type) VALUES (:o,:k,:l,:t)",
  o=OID, k="blood_group", l="Blood Group", t="text")
Q("INSERT INTO payroll_enterprise_jurisdictions (organization_id, country_code, status) VALUES (:o,:c,:s)",
  o=OID, c="IN", s="verified")

PID = Q("INSERT INTO payroll_policies (organization_id, name, status, effective_date, is_default, calculation_mode, bank_export_format, enterprise_status) "
        "VALUES (:o,:n,:s,:e,:d,:m,:b,:es) RETURNING id",
        o=OID, n="Default", s="active", e="2026-01-01", d=1, m="standard", b="csv", es="not_configured").scalar()
Q("INSERT INTO payroll_policy_employee_categories (policy_id, category, working_days, weekly_off, expected_hours, minimum_hours, paid_leave_eligible, grace_time_minutes) "
  "VALUES (:p,:c,:w,:wo,:e,:m,:pl,:g)", p=PID, c="STAFF", w=5, wo="[]", e=8, m=4, pl=1, g=10)
Q("INSERT INTO payroll_policy_leave_rules (policy_id, rule_type, config) VALUES (:p,:t,:c)", p=PID, t="accrual", c="{}")
Q("INSERT INTO payroll_policy_overtime_rules (policy_id, enabled, minimum_overtime_minutes, approval_required) VALUES (:p,:e,:m,:a)",
  p=PID, e=1, m=30, a=1)
Q("INSERT INTO payroll_policy_integrations (policy_id, category, provider_key, enabled) VALUES (:p,:c,:k,:e)",
  p=PID, c="attendance", k="zoiko_time", e=1)

Q("INSERT INTO payroll_email_settings (organization_id, from_email, notify_payslip_ready, notify_run_approved, use_custom_smtp) "
  "VALUES (:o,:e,:n1,:n2,:u)", o=OID, e="noreply@tst.com", n1=1, n2=1, u=0)

RID = Q("INSERT INTO payroll_runs (organization_id, period_label, period_start, period_end, pay_date, status, total_net, employee_count) "
        "VALUES (:o,:l,:s,:e,:p,:st,:n,:ec) RETURNING id",
        o=OID, l="Jan 1-31, 2026", s="2026-01-01", e="2026-01-31", p="2026-01-31", st="draft", n=0, ec=1).scalar()
Q("INSERT INTO payslip_items (organization_id, payroll_run_id, employee_id, employee_name, basic_salary, status) "
  "VALUES (:o,:r,:e,:en,:b,:s)", o=OID, r=RID, e=EID, en="Employee One", b=1000, s="pending")

Q("INSERT INTO payroll_attendance_records (organization_id, employee_id, date, status, is_half_day) VALUES (:o,:e,:d,:s,:h)",
  o=OID, e=EID, d="2026-01-15", s="present", h=0)

db.commit()

TABLES = ["organizations", "users", "security_action_tokens",
          "payroll_employees", "payroll_runs", "payslip_items", "payroll_attendance_records",
          "payroll_holidays", "payroll_contribution_rates", "payroll_tax_slabs",
          "payroll_company_compliance", "payroll_compliance_documents", "payroll_leave_allocations",
          "payroll_leave_requests", "payroll_activity_log", "payroll_custom_field_definitions",
          "payroll_enterprise_jurisdictions", "payroll_policies", "payroll_policy_employee_categories",
          "payroll_policy_leave_rules", "payroll_policy_overtime_rules", "payroll_policy_integrations",
          "payroll_email_settings"]

before = {t: db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in TABLES}
print("BEFORE:", before)
assert all(v > 0 for v in before.values()), "seed failed"

# Replicate app/modules/organizations/router.py delete_organization order.
# Note: the live endpoint also cleans up payroll_inbound_messages/attachments
# (tables still physically present in the real DB from the now-removed IMAP
# feature). This test's schema is built fresh from the current models via
# create_all(), which no longer define those tables, so they're omitted here.
_org_direct = ["payroll_email_settings", "payroll_update_form_submissions",
    "payroll_update_form_sends", "payroll_update_forms", "payroll_custom_field_definitions",
    "payroll_activity_log", "payroll_leave_requests", "payroll_leave_allocations",
    "payroll_compliance_documents", "payroll_tax_slabs", "payroll_contribution_rates",
    "payroll_company_compliance", "payroll_holidays", "payroll_enterprise_jurisdictions",
    "payslip_items", "payroll_attendance_records", "payroll_runs", "payroll_employees"]
_org_via_parent = [("payroll_policy_integrations", "policy_id", "payroll_policies"),
    ("payroll_policy_overtime_rules", "policy_id", "payroll_policies"),
    ("payroll_policy_leave_rules", "policy_id", "payroll_policies"),
    ("payroll_policy_employee_categories", "policy_id", "payroll_policies")]

for t, fk, p in _org_via_parent:
    db.execute(text(f'DELETE FROM "{t}" WHERE "{fk}" IN (SELECT id FROM "{p}" WHERE organization_id = :oid)'), {"oid": OID})
for t in _org_direct:
    db.execute(text(f'DELETE FROM "{t}" WHERE organization_id = :oid'), {"oid": OID})
db.execute(text('DELETE FROM "payroll_policies" WHERE organization_id = :oid'), {"oid": OID})
db.execute(text('DELETE FROM "security_action_tokens" WHERE organization_id = :oid'), {"oid": OID})
db.execute(text('DELETE FROM "users" WHERE organization_id = :oid'), {"oid": OID})
db.execute(text('DELETE FROM "organizations" WHERE id = :oid'), {"oid": OID})
db.commit()

after = {t: db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in TABLES}
print("AFTER:", after)

leftovers = {t: c for t, c in after.items() if c != 0}
print("RESULT:", "PASS" if not leftovers else f"FAIL - leftovers: {leftovers}")
db.close()
sys.exit(0 if not leftovers else 1)

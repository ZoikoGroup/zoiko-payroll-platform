"""Shared helpers for the Mexico Phase 3 employer-onboarding tests.

Not collected by pytest (no test_ prefix). Everything imports app.* lazily
inside the helpers (collection-order DB-binding hazard). Every statutory row
built here is SYNTHETIC — it proves the mechanics, never a Mexican value.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

ORG_BASE = "/api/payroll/mexico"
SA_BASE = "/api/super-admin/compliance/mexico"
GCP_REF = "gcp-sm://projects/zoiko-test-project/secrets/mx-csd-key/versions/1"


def principal(org_id, user_id=701, role="org_admin"):
    return SimpleNamespace(id=user_id, organization_id=org_id, role=role, is_active=True)


SUPER_ADMIN = SimpleNamespace(id=990, organization_id=None, role="super_admin", is_active=True)


def enable_mx_onboarding(monkeypatch):
    """Phase 4a: the Mexico organisation API is dormant unless the flag is on."""
    from app.config import settings

    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", True)


@contextmanager
def http(db, who):
    from tests.test_hong_kong_governance import _http as hk_http

    with hk_http(db, who) as client:
        yield client


def make_org(db, name="MX Test Org", code="MXTEST", admins=1, country="MX"):
    """An organisation plus `admins` real active org-admin users (the
    four-eyes readiness check counts real users). `country` sets its payroll
    jurisdiction (CompanyComplianceDetails) — MX by default, None for none —
    because the Phase 4a guard only admits Mexican organisations."""
    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import CompanyComplianceDetails

    org = Organization(organization_name=name, organization_code=code)
    db.add(org)
    db.flush()
    if country:
        db.add(CompanyComplianceDetails(organization_id=org.id, name=name, jurisdiction_country=country))
    users = []
    for i in range(admins):
        u = User(email=f"admin{i}.{code.lower()}@example.com", hashed_password="x", role=UserRole.ORG_ADMIN,
                 organization_id=org.id, first_name="Test", last_name=f"Admin{i}", is_active=True, is_verified=True)
        db.add(u)
        users.append(u)
    db.commit()
    return SimpleNamespace(org=org, users=users)


def employer_payload(**over):
    p = {"effectiveFrom": "2026-01-01", "taxpayerType": "MORAL", "rfc": "ABC010101AB1",
         "legalName": "Empresa Sintética SA de CV", "fiscalRegimeCode": "601", "fiscalPostalCode": "06600",
         "placeOfIssuePostalCode": "06600", "withholdingObligationActive": True}
    p.update(over)
    return p


def to_service(payload: dict) -> dict:
    import re

    out = {}
    for k, v in payload.items():
        key = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
        if isinstance(v, str) and key in ("effective_from", "effective_to", "period_from", "period_to"):
            v = date.fromisoformat(v)
        out[key] = v
    return out


def new_employer(db, org_id, actor=701, **over):
    from app.modules.payroll import mexico_employer_service as svc

    return svc.create_employer(db, org_id, to_service(employer_payload(**over)), actor)


def new_registration(db, org_id, employer_id, actor=701, rp="Y1234567101", eff="2026-01-01", **over):
    from app.modules.payroll import mexico_employer_service as svc

    data = {"registro_patronal": rp, "risk_class": "I", "fraction": "811", "effective_from": date.fromisoformat(eff)}
    data.update(over)
    return svc.create_registration(db, org_id, employer_id, data, actor)


def evidence_doc(db, org_id):
    from app.modules.payroll.models import ComplianceDocument

    doc = ComplianceDocument(organization_id=org_id, title="SYNTHETIC premium determination", file_path="x.pdf",
                             file_name="x.pdf", country="MX")
    db.add(doc)
    db.commit()
    return doc


def active_pack(db, *, start=date(2026, 1, 1), end=date(2026, 12, 31), scalars=None, workweek="48",
                vacation=((1, 1, "12"), (2, None, "14")), extra_workweek=None, pack_id="MX-PAYROLL-TEST"):
    """A test-only ACTIVE national pack inserted directly (the activation
    gates are tested elsewhere). SYNTHETIC values. `scalars` maps key ->
    (attr, value); None for the default floor set."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from app.modules.payroll.engine.countries import mexico_content as c

    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="MX", version="1.0", pack_type="tax",
                            status="Active", effective_from=start, effective_to=end, tax_year=str(start.year),
                            currency="MXN")
    db.add(pack)
    db.flush()
    if scalars is None:
        scalars = {"mx_aguinaldo_min_days": ("flat_amount", "15"), "mx_vacation_premium_min_pct": ("employee_rate_pct", "25"),
                   "mx_sunday_premium_min_pct": ("employee_rate_pct", "25"),
                   "mx_risk_premium_min_pct": ("employer_rate_pct", "0.5"),
                   "mx_risk_premium_max_pct": ("employer_rate_pct", "15")}
    for i, (key, (attr, value)) in enumerate(scalars.items()):
        db.add(ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", component_key=key,
                                label=key, employee_share="—", employer_share="—", total="—", sort_order=i,
                                **{attr: Decimal(value)}))
    if workweek is not None:
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", rule_type=c.MX_WORKWEEK_RULE,
                       filing_status="WEEKLY_MAX", min_amount=Decimal("0"), flat_amount=Decimal(workweek),
                       rate_pct=Decimal("0"), rate_label="SYNTHETIC", tax_formula="SYNTHETIC", effective_from=None, effective_to=None))
    if extra_workweek is not None:     # (from_date, hours) — a later workweek row inside the pack
        frm, hours = extra_workweek
        db.flush()                     # autoflush is off: the first row must exist before it is closed
        db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                 TaxSlab.rule_type == c.MX_WORKWEEK_RULE).update(
            {"effective_to": frm - timedelta(days=1)})
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", rule_type=c.MX_WORKWEEK_RULE,
                       filing_status="WEEKLY_MAX", min_amount=Decimal("0"), flat_amount=Decimal(hours),
                       rate_pct=Decimal("0"), rate_label="SYNTHETIC", tax_formula="SYNTHETIC", effective_from=frm, effective_to=None))
    for y_from, y_to, days in vacation:
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", rule_type=c.MX_VACATION_DAYS_RULE,
                       filing_status=f"YEAR_{y_from}", min_amount=Decimal(y_from),
                       max_amount=None if y_to is None else Decimal(y_to), flat_amount=Decimal(days),
                       rate_pct=Decimal("0"), rate_label="SYNTHETIC", tax_formula="SYNTHETIC"))
    db.commit()
    return pack


def policy_payload(**over):
    p = {"effectiveFrom": "2026-03-01", "ordinaryWeeklyHours": "48", "aguinaldoDays": "15",
         "vacationPolicy": [{"serviceYearFrom": 1, "serviceYearTo": 1, "days": "12"},
                            {"serviceYearFrom": 2, "serviceYearTo": None, "days": "14"}],
         "vacationPremiumPct": "25", "sundayPremiumPct": "25"}
    p.update(over)
    return p


def self_signed_cert(*, days=365, not_before=None, pem=False):
    """A throwaway certificate generated in memory at test time — never
    committed. Returns (bytes, cert)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SYNTHETIC CSD TEST")])
    start = not_before or datetime(2026, 1, 1, tzinfo=timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(0x1234ABCD).not_valid_before(start).not_valid_after(start + timedelta(days=days))
            .sign(key, hashes.SHA256()))
    enc = serialization.Encoding.PEM if pem else serialization.Encoding.DER
    return cert.public_bytes(enc), cert, key

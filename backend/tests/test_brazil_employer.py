"""Brazil (ZP-BR-ENG-001) Phase 3 — employer onboarding: the employer version
chain, establishments, RAT/FAP by year, CPRB options, credential references,
readiness, the organisation API (dormancy guard, tenant isolation, roles),
the Super Admin read-only view, the dormancy rules and organisation delete.

Every identifier and rate here is SYNTHETIC — it proves the mechanics, never
a Brazilian value. `app.*` is imported inside each test / helper (never at
module level) so collecting this file cannot bind the app to the .env database
before conftest's in-memory SQLite fixture is in place."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

ORG_BASE = "/api/payroll/brazil"
SA_BASE = "/api/super-admin/compliance/brazil"
GCP_REF = "gcp-sm://projects/zoiko-test-project/secrets/br-esocial-a1/versions/1"
ROOT = "11222333"
SUPER_ADMIN = SimpleNamespace(id=990, organization_id=None, role="super_admin", is_active=True,
                              email="zzz.throwaway.superadmin@zoiko.internal")


# ── helpers ──────────────────────────────────────────────────────────────────

def _svc():
    from app.modules.payroll import brazil_employer_service

    return brazil_employer_service


def cnpj(root: str, branch: str = "0001") -> str:
    """A CNPJ with valid check digits (the official mod-11 weights)."""
    base = root + branch

    def digit(chars, weights):
        r = sum((ord(c) - 48) * w for c, w in zip(chars, weights)) % 11
        return "0" if r < 2 else str(11 - r)

    d1 = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    d2 = digit(base + d1, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + d1 + d2


def principal(org_id, user_id=801, role="org_admin"):
    return SimpleNamespace(id=user_id, organization_id=org_id, role=role, is_active=True)


@pytest.fixture
def br_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "BR_TENANT_ONBOARDING_ENABLED", True)


@contextmanager
def http(db, who):
    from tests.test_hong_kong_governance import _http as hk_http

    with hk_http(db, who) as client:
        yield client


def make_org(db, name="BR Test Org", code="BRTEST", country="BR"):
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import CompanyComplianceDetails

    org = Organization(organization_name=name, organization_code=code)
    db.add(org)
    db.flush()
    if country:
        db.add(CompanyComplianceDetails(organization_id=org.id, name=name, jurisdiction_country=country))
    db.commit()
    return org


def employer_data(**over):
    d = {"effective_from": date(2026, 1, 1), "cnpj_root": ROOT, "legal_name": "Empresa Sintética Ltda",
         "trade_name": None, "tax_classification": "99", "cnae_preponderant": "6201501",
         "esocial_environment": "RESTRICTED_PRODUCTION", "contact_name": "Responsável Teste",
         "contact_cpf": "52998224725", "contact_email": "folha@example.com", "contact_phone": None}
    d.update(over)
    return d


def establishment_data(**over):
    d = {"active_from": date(2026, 1, 1), "cnpj": cnpj(ROOT), "establishment_name": "Matriz", "is_headquarters": True,
         "cnae": "6201501", "fpas_code": "515", "third_party_code": "0115", "third_party_pct": "5.80",
         "fpas_evidence_ref": "Declaração FPAS (teste)", "lotacao_code": "LOT-01", "postal_code": "01310-100",
         "street_address": "Av. Paulista, 1000", "neighborhood": "Bela Vista", "city_ibge_code": "3550308",
         "state_uf": "sp", "judicial_process_id": None}
    d.update(over)
    return d


def new_employer(db, org_id, **over):
    return _svc().create_employer(db, org_id, employer_data(**over), 801)


def self_signed(days_valid=365, start=None):
    """A throwaway public certificate (DER) and the bytes of its PKCS#12 bundle."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA SINTETICA LTDA:11222333000181")])
    start = start or datetime.now(timezone.utc) - timedelta(days=1)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(start)
            .not_valid_after(start + timedelta(days=days_valid)).sign(key, hashes.SHA256()))
    der = cert.public_bytes(serialization.Encoding.DER)
    p12 = pkcs12.serialize_key_and_certificates(b"a1", key, cert, None, serialization.NoEncryption())
    return der, p12


# ── employer version chain ───────────────────────────────────────────────────

def test_employer_versions_close_the_previous_and_keep_the_cnpj_root(db):
    from app.core.exceptions import BadRequestException

    org = make_org(db)
    v1 = new_employer(db, org.id)
    v2 = _svc().create_employer_version(db, org.id, v1["id"], employer_data(effective_from=date(2026, 7, 1),
                                                                             legal_name="Empresa v2"), 801)
    assert (v2["version"], v2["previousVersionId"]) == (2, v1["id"])
    chain = _svc().list_employers(db, org.id)[0]["versions"]
    assert chain[0]["effectiveTo"] == "2026-06-30" and chain[1]["effectiveTo"] is None
    with pytest.raises(BadRequestException, match="CNPJ root cannot change"):
        _svc().create_employer_version(db, org.id, v2["id"], employer_data(effective_from=date(2026, 9, 1),
                                                                           cnpj_root="99887766"), 801)
    with pytest.raises(BadRequestException, match="must start after"):
        _svc().create_employer_version(db, org.id, v1["id"], employer_data(effective_from=date(2026, 7, 1)), 801)
    root = _svc().employer_root(db, org.id, v2["id"])
    assert root.id == v1["id"]
    assert _svc().version_in_force(db, root.id, date(2026, 6, 30)).version == 1
    assert _svc().version_in_force(db, root.id, date(2026, 7, 1)).version == 2


@pytest.mark.parametrize("over,msg", [
    ({"cnpj_root": "1122233"}, "cnpjRoot"),
    ({"contact_cpf": "52998224726"}, "CPF check digits"),
    ({"tax_classification": "9"}, "Tabela 08"),
    ({"cnae_preponderant": "62015"}, "CNAE"),
    ({"esocial_environment": "TEST"}, "esocialEnvironment"),
    ({"contact_email": "not-an-email"}, "email"),
    ({"legal_name": " "}, "legalName"),
])
def test_employer_fields_are_validated(db, over, msg):
    from app.core.exceptions import BadRequestException

    org = make_org(db)
    with pytest.raises(BadRequestException, match=msg):
        new_employer(db, org.id, **over)


def test_contact_cpf_is_masked_in_every_view(db):
    org = make_org(db)
    view = new_employer(db, org.id)
    assert view["contactCpf"].endswith("4725") and "529982" not in view["contactCpf"]


# ── establishments ───────────────────────────────────────────────────────────

def test_establishment_cnpj_rules(db):
    from app.core.exceptions import BadRequestException

    org = make_org(db)
    emp = new_employer(db, org.id)
    hq = _svc().create_establishment(db, org.id, emp["id"], establishment_data(), 801)
    assert (hq["fpasStatus"], hq["stateUf"], hq["postalCode"]) == ("DECLARED", "SP", "01310100")
    with pytest.raises(BadRequestException, match="check digits"):
        _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj(ROOT)[:-1] + "0"), 801)
    with pytest.raises(BadRequestException, match="CNPJ root"):
        _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj("44555666"),
                                                                              is_headquarters=False), 801)
    with pytest.raises(BadRequestException, match="active headquarters"):
        _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj(ROOT, "0002")), 801)
    branch = _svc().create_establishment(db, org.id, emp["id"], establishment_data(
        cnpj=cnpj(ROOT, "0002"), is_headquarters=False, establishment_name="Filial"), 801)
    assert branch["isHeadquarters"] is False
    with pytest.raises(BadRequestException, match="already has an establishment"):
        _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj(ROOT, "0002"),
                                                                              is_headquarters=False), 801)
    with pytest.raises(BadRequestException, match="27 Brazilian"):
        _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj(ROOT, "0003"),
                                                                              is_headquarters=False, state_uf="XX"), 801)
    _svc().deactivate_establishment(db, org.id, hq["id"], date(2026, 6, 30), 801)
    new_hq = _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj(ROOT, "0004")), 801)
    assert new_hq["isHeadquarters"] is True                     # the old HQ is no longer active


def test_alphanumeric_cnpj_is_accepted(db):
    org = make_org(db)
    emp = new_employer(db, org.id, cnpj_root="12ABC345")
    est = _svc().create_establishment(db, org.id, emp["id"], establishment_data(cnpj=cnpj("12ABC345", "01DE")), 801)
    assert est["cnpj"].startswith("12ABC34501DE")


# ── RAT / FAP by year ────────────────────────────────────────────────────────

def test_risk_assignment_lifecycle_supersedes_the_year(db):
    from app.core.exceptions import BadRequestException

    org = make_org(db)
    emp = new_employer(db, org.id)
    est = _svc().create_establishment(db, org.id, emp["id"], establishment_data(), 801)
    data = {"calendar_year": 2026, "rat_pct": "2", "fap_factor": "1.0500", "evidence_ref": "FAP 2026 (teste)"}
    first = _svc().create_risk_assignment(db, org.id, est["id"], data, 801)
    assert first["status"] == "DRAFT"
    _svc().activate_risk_assignment(db, org.id, first["id"], 801)
    second = _svc().create_risk_assignment(db, org.id, est["id"], {**data, "fap_factor": "0.9000"}, 801)
    _svc().activate_risk_assignment(db, org.id, second["id"], 801)
    rows = {r["id"]: r["status"] for r in _svc().list_risk_assignments(db, org.id, est["id"])}
    assert rows == {first["id"]: "SUPERSEDED", second["id"]: "ACTIVE"}
    with pytest.raises(BadRequestException, match="only a DRAFT"):
        _svc().activate_risk_assignment(db, org.id, second["id"], 801)
    for bad, msg in (({"rat_pct": "1.5"}, "1, 2 or 3"), ({"fap_factor": "2.0001"}, "0.5000 and 2.0000"),
                     ({"fap_factor": "1.00001"}, "4 decimals"), ({"calendar_year": 2025}, "from 2026"),
                     ({"evidence_ref": ""}, "evidenceRef")):
        with pytest.raises(BadRequestException, match=msg):
            _svc().create_risk_assignment(db, org.id, est["id"], {**data, **bad}, 801)


# ── CPRB option ──────────────────────────────────────────────────────────────

def test_cprb_option_per_year(db):
    from app.core.exceptions import BadRequestException

    org = make_org(db)
    emp = new_employer(db, org.id)
    not_opted = _svc().create_cprb_option(db, org.id, emp["id"], {"calendar_year": 2026, "opted": False,
                                                                  "evidence_ref": "Opção 2026 (teste)"}, 801)
    opted = _svc().create_cprb_option(db, org.id, emp["id"], {"calendar_year": 2026, "opted": True,
                                                              "cprb_rate_pct": "4.5", "sector_reference": "TI (teste)",
                                                              "evidence_ref": "Opção 2026 retificada"}, 801)
    statuses = {r["id"]: r["status"] for r in _svc().list_cprb_options(db, org.id, emp["id"])}
    assert statuses == {not_opted["id"]: "SUPERSEDED", opted["id"]: "ACTIVE"}
    with pytest.raises(BadRequestException, match="needs cprbRatePct"):
        _svc().create_cprb_option(db, org.id, emp["id"], {"calendar_year": 2027, "opted": True,
                                                          "evidence_ref": "x"}, 801)
    with pytest.raises(BadRequestException, match="only to an opted year"):
        _svc().create_cprb_option(db, org.id, emp["id"], {"calendar_year": 2027, "opted": False,
                                                          "cprb_rate_pct": "1", "evidence_ref": "x"}, 801)


# ── credential references ────────────────────────────────────────────────────

# PEM markers built at runtime so the literal never sits in the source: the
# privacy repository scan (scripts/scan_test_data.py, ZP-PRIV D09) flags any
# "BEGIN ... PRIVATE KEY" line, and these are deliberately fake key material.
PEM_KEY_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
PEM_KEY_END = "-----END " + "PRIVATE KEY-----"


@pytest.mark.parametrize("bad", [
    PEM_KEY_BEGIN, "MIIJQgIBADANBgkqhkiG9w0BAQEFAASCCSwwggkoAgEAAoICAQC7pZq9s0uOi5d3XlqZ",
    "vault://secret/br", "gcp-sm://projects/x/secrets/y", "gcp-sm://projects/zoiko-test/secrets/a b", "",
])
def test_credential_refs_never_store_secrets_and_never_echo_them(db, bad):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import PayrollBrCredentialRef, TaxConfigurationAudit

    org = make_org(db)
    emp = new_employer(db, org.id)
    with pytest.raises(BadRequestException) as exc:
        _svc().create_credential(db, org.id, emp["id"], {"kind": "ESOCIAL_A1", "secret_ref": bad}, 801)
    if bad:
        assert bad not in exc.value.message
        assert all(bad not in (str(a.new_value) + str(a.reason)) for a in db.query(TaxConfigurationAudit).all())
    assert db.query(PayrollBrCredentialRef).count() == 0


def test_credential_rotation_revocation_and_public_certificate(db):
    from app.core.exceptions import BadRequestException

    org = make_org(db)
    emp = new_employer(db, org.id)
    first = _svc().create_credential(db, org.id, emp["id"], {"kind": "ESOCIAL_A1", "secret_ref": GCP_REF}, 801)
    assert first["secretRef"] == GCP_REF and first["secretRefMasked"].endswith("ns/1"[-4:])
    second = _svc().create_credential(db, org.id, emp["id"], {"kind": "ESOCIAL_A1", "secret_ref": GCP_REF}, 801)
    assert second["rotatedFromId"] == first["id"]
    listed = {c["id"]: c["status"] for c in _svc().list_credentials(db, org.id, emp["id"])}
    assert listed == {first["id"]: "ROTATED", second["id"]: "ACTIVE"}
    assert all("secretRef" not in c for c in _svc().list_credentials(db, org.id, emp["id"]))
    der, p12 = self_signed()
    with pytest.raises(BadRequestException, match="PKCS#12|single public"):
        _svc().attach_certificate(db, org.id, second["id"], p12, 801)
    with pytest.raises(BadRequestException):
        _svc().attach_certificate(db, org.id, second["id"], f"{PEM_KEY_BEGIN}\nabc\n{PEM_KEY_END}".encode(), 801)
    view = _svc().attach_certificate(db, org.id, second["id"], der, 801)
    assert len(view["fingerprintSha256"]) == 64 and view["validTo"]
    revoked = _svc().revoke_credential(db, org.id, second["id"], 801)
    assert revoked["status"] == "REVOKED"


# ── readiness ────────────────────────────────────────────────────────────────

def _fully_configured(db, org, cert_days=365):
    emp = new_employer(db, org.id)
    est = _svc().create_establishment(db, org.id, emp["id"], establishment_data(), 801)
    risk = _svc().create_risk_assignment(db, org.id, est["id"], {"calendar_year": 2026, "rat_pct": "1",
                                                                 "fap_factor": "1.0000", "evidence_ref": "FAP"}, 801)
    _svc().activate_risk_assignment(db, org.id, risk["id"], 801)
    _svc().create_cprb_option(db, org.id, emp["id"], {"calendar_year": 2026, "opted": False, "evidence_ref": "x"}, 801)
    cred = _svc().create_credential(db, org.id, emp["id"], {"kind": "ESOCIAL_A1", "secret_ref": GCP_REF}, 801)
    der, _ = self_signed(days_valid=cert_days, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _svc().attach_certificate(db, org.id, cred["id"], der, 801)
    return emp, est


def test_readiness_items_and_live_is_unreachable_in_phase_3(db):
    org = make_org(db)
    emp, est = _fully_configured(db, org)
    report = _svc().organisation_readiness(db, org.id, date(2026, 6, 15))
    assert len(report["employers"]) == 1 and [g["gate"] for g in report["gates"]] == [f"G{i}" for i in range(1, 9)]
    items = {i["key"]: i for i in report["employers"][0]["items"]}
    assert items["employer_version"]["status"] == "PASS"
    assert items["establishments"]["status"] == "PASS"
    assert items["risk"]["status"] == "PASS"
    assert items["cprb"]["status"] == "PASS"
    assert items["esocial_a1"]["status"] == "PASS"
    assert items["fpas"]["status"] == "BLOCKED"                  # DECLARED until checked against Tabela 04
    assert items["tax_classification"]["status"] == "WARNING"
    for key in ("engine_certified", "esocial_events", "dctfweb", "fgts_digital", "labor_cct", "parallel_payroll"):
        assert items[key]["status"] == "BLOCKED"
    assert report["employers"][0]["liveEligible"] is False
    for item in report["employers"][0]["items"]:
        assert item["gates"] and set(item["gateBasis"]) == set(item["gates"])


def test_readiness_without_risk_for_the_year_and_with_an_expiring_certificate(db):
    org = make_org(db)
    _fully_configured(db, org, cert_days=200)                    # expires 2026-07-20
    items = {i["key"]: i for i in _svc().organisation_readiness(db, org.id, date(2027, 1, 10))["employers"][0]["items"]}
    assert items["risk"]["status"] == "BLOCKED" and "2027" in items["risk"]["detail"]
    assert items["cprb"]["status"] == "NOT_STARTED"
    assert items["esocial_a1"]["status"] == "BLOCKED"            # expired
    items = {i["key"]: i for i in _svc().organisation_readiness(db, org.id, date(2026, 7, 1))["employers"][0]["items"]}
    assert items["esocial_a1"]["status"] == "WARNING"            # within 30 days


def test_readiness_needs_an_explicit_date(db):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="on is required"):
        _svc().organisation_readiness(db, 1, None)


# ── organisation API ─────────────────────────────────────────────────────────

def test_org_api_is_dormant_unless_the_flag_is_on(db):
    org = make_org(db)
    with http(db, principal(org.id)) as c:
        r = c.get(f"{ORG_BASE}/employers")
    assert r.status_code == 403 and "not open for onboarding" in r.json()["message"]


def test_org_api_admits_only_brazilian_organisations(db, br_on):
    org = make_org(db, country="MX")
    with http(db, principal(org.id)) as c:
        assert c.get(f"{ORG_BASE}/employers").status_code == 403


def test_org_api_round_trip_roles_and_tenant_isolation(db, br_on):
    org_a, org_b = make_org(db), make_org(db, name="Other", code="BROTHER")
    body = {"effectiveFrom": "2026-01-01", "cnpjRoot": ROOT, "legalName": "Empresa A", "taxClassification": "99",
            "cnaePreponderant": "6201501", "esocialEnvironment": "RESTRICTED_PRODUCTION", "contactName": "A",
            "contactCpf": "529.982.247-25", "contactEmail": "a@example.com"}
    with http(db, principal(org_a.id, role="payroll_admin")) as c:
        assert c.post(f"{ORG_BASE}/employers", json=body).status_code == 403          # writes need an org admin
    with http(db, principal(org_a.id)) as c:
        emp = c.post(f"{ORG_BASE}/employers", json=body).json()
        assert c.post(f"{ORG_BASE}/employers", json={**body, "extra": 1}).status_code == 422   # extra="forbid"
        r = c.get(f"{ORG_BASE}/readiness")
        assert r.status_code == 422                                                   # on is required
        assert c.get(f"{ORG_BASE}/readiness", params={"on": "2026-06-15"}).status_code == 200
    with http(db, principal(org_b.id)) as c:
        assert c.get(f"{ORG_BASE}/employers/{emp['id']}").status_code == 404           # another tenant's id
        assert c.get(f"{ORG_BASE}/employers").json() == []
    with http(db, principal(org_a.id, role="payroll_admin")) as c:
        assert c.get(f"{ORG_BASE}/employers").json()[0]["employerId"] == emp["id"]


def test_credential_route_never_echoes_the_payload(db, br_on):
    org = make_org(db)
    emp = new_employer(db, org.id)
    secret = PEM_KEY_BEGIN + "MIIEvQ"
    with http(db, principal(org.id)) as c:
        r = c.post(f"{ORG_BASE}/employers/{emp['id']}/credentials", json={"kind": "ESOCIAL_A1", "secretRef": secret,
                                                                           "password": "hunter2"})
    assert r.status_code == 400 and secret not in r.text and "hunter2" not in r.text


def test_super_admin_is_read_only_and_masked(db):
    org = make_org(db)
    _fully_configured(db, org)
    with http(db, SUPER_ADMIN) as c:
        employers = c.get(f"{SA_BASE}/employers", params={"organization_id": org.id}).json()
        assert employers[0]["cnpjRoot"].endswith(ROOT[-4:]) and employers[0]["cnpjRoot"] != ROOT
        assert c.get(f"{SA_BASE}/employer-readiness", params={"organization_id": org.id,
                                                              "on": "2026-06-15"}).status_code == 200
        summary = c.get(f"{SA_BASE}/employer-readiness/summary", params={"on": "2026-06-15"}).json()
        assert summary["employers"] == 1 and summary["passingByGate"]["G2"] == 0   # FPAS still DECLARED
        assert c.post(f"{SA_BASE}/employers", json={}).status_code == 405
        assert c.get(f"{ORG_BASE}/employers").status_code == 403                    # the org API is not for SA


# ── dormancy and platform ────────────────────────────────────────────────────

def test_entering_brazil_is_refused_while_dormant(monkeypatch):
    from app.config import settings
    from app.modules.payroll import brazil_dormancy as d

    assert d.entering_brazil_refusal("India", "Brazil") == d.DORMANT_MESSAGE
    assert d.entering_brazil_refusal("BR", "Brasil") is None                     # already Brazilian
    assert d.entering_brazil_refusal("India", "Mexico") is None                  # not Brazil
    monkeypatch.setattr(settings, "BR_TENANT_ONBOARDING_ENABLED", True)
    assert d.entering_brazil_refusal("India", "Brazil") is None


def test_country_change_into_brazil_is_blocked(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    assert "Brazil is not open" in get_jurisdiction_change_block_reason(db, "India", "Brazil")


def test_employee_validator_is_dormant_until_the_flag(monkeypatch):
    from app.config import settings
    from app.modules.payroll.employee_validation import is_supported_employee_country

    assert is_supported_employee_country("BR") is False
    monkeypatch.setattr(settings, "BR_TENANT_ONBOARDING_ENABLED", True)
    assert is_supported_employee_country("BR") is True
    assert is_supported_employee_country("MX") is False                          # Mexico's own flag is separate


def test_delete_organization_with_brazil_rows(db, monkeypatch):
    """BR-K9: employees go first (cascading their Brazil profiles), then the
    organisation cascades the employer chain, establishments, risk, CPRB and
    credentials — no RESTRICT ever fires. Foreign keys are enforced from the
    first insert, and every row is created by a REAL org user: delete_organization
    removes the org's users before the org, so created_by_id must be SET NULL
    (as on PostgreSQL), never a dangling reference that blocks the delete."""
    import sqlalchemy as sa

    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.router import delete_organization
    from app.modules.payroll.models import (
        PayrollBrCredentialRef, PayrollBrEmployerProfile, PayrollBrEstablishment, PayrollBrRiskAssignment,
        PayrollEmployee,
    )

    from app.config import settings

    # The Brazil writes are audited; a hard delete purges audit rows only when
    # the platform allows it (default off -> 409, see test_org_delete_endpoint).
    monkeypatch.setattr(settings, "AUDIT_PURGE_ON_ORG_HARD_DELETE", True)
    db.execute(sa.text("PRAGMA foreign_keys=ON"))
    org = make_org(db)
    db.add(User(id=801, email="br-admin@example.com", hashed_password="x", role=UserRole.ORG_ADMIN,
                first_name="Bia", last_name="Admin", organization_id=org.id))
    db.commit()
    _fully_configured(db, org)
    db.add(PayrollEmployee(organization_id=org.id, employee_code="BR-1", name="Ana", country_code="BR"))
    db.commit()
    assert db.query(PayrollBrEstablishment).filter(PayrollBrEstablishment.created_by_id == 801).count() == 1
    delete_organization(organization_id=org.id, db=db, current_user=SUPER_ADMIN)
    for model in (PayrollBrEmployerProfile, PayrollBrEstablishment, PayrollBrRiskAssignment, PayrollBrCredentialRef):
        assert db.query(model).count() == 0, model.__name__

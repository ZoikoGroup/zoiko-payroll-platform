"""Mexico CFDI lifecycle L1-L5 (docs/mexico/MEXICO_CFDI_LIFECYCLE_REPORT.md):
design-state mapping, the common envelope, the access log, the pay-event
idempotency key, the conflict checks that must REJECT, and the decision-table
scenarios not already covered elsewhere. SYNTHETIC worlds: the 11b ready world
(real builder), the mock PAC, synthetic signer."""

import json
from datetime import timedelta

import pytest


def _L():
    from app.modules.payroll import mexico_cfdi_lifecycle

    return mexico_cfdi_lifecycle


def _ready(db, monkeypatch, tmp_path, code):
    from tests import _mx_run_helpers as rh
    from tests.test_mexico_cfdi_builder import _ready_world

    w = _ready_world(db, monkeypatch, tmp_path, code)
    (item,) = rh.mx_items(db, w.run)
    return w, item


def _stamp(db, monkeypatch, w, **script):
    from app.modules.payroll import mexico_cfdi_service as S
    from tests import _mx_cfdi_helpers as ch

    ch.mock(monkeypatch, **script)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    db.refresh(doc)
    return doc


def _refusal(call):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    with pytest.raises(MXBlock) as exc:
        call()
    return exc.value.key


# ── L1 + decision table: normal payment ──────────────────────────────────────

def test_normal_payment_walks_every_design_state_and_keeps_payment_apart(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_preview, mexico_run_service

    L = _L()
    w, item = _ready(db, monkeypatch, tmp_path, "MXLC01")
    assert L.design_state(db, item)["state"] == "DRAFT"
    out = mexico_cfdi_preview.validate_run(db, w.run, w.users[0].id)                 # map + validate
    assert out["valid"] == 1
    assert L.design_state(db, item)["state"] == "VALIDATED_LOCAL"
    doc = _stamp(db, monkeypatch, w)                                                  # sign + PAC + stamp
    assert doc.status == "STAMPED" and L.design_state(db, item, doc)["state"] == "STAMPED"
    assert L.funding_state(db, w.run)["state"] == "NOT_FUNDED"                        # stamped is NOT paid
    assert mexico_run_service.run_status(db, w.run)["bank"]["status"] == "HELD"
    pub = L.publish(db, w.org.id, doc.id, w.users[0].id)                              # employee view from the XML
    assert pub["state"] == "PUBLISHED" and pub["uuid"] == doc.uuid
    L.record_delivery(db, w.org.id, doc.id, "DELIVERED", "PORTAL", "SYN-PROOF-1", w.users[0].id)
    assert L.design_state(db, item, doc)["state"] == "DELIVERED"
    events = [e["event"] for e in L.access_log(db, w.org.id, document_id=doc.id)]
    assert events == ["PUBLISHED", "DELIVERED"]
    assert L.run_states(db, w.run) == {"payroll": "APPROVED", "funding": {"state": "NOT_FUNDED",
                                                                          "detail": "no payment batch"}}


def test_validation_failed_is_a_design_state(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_preview

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC02")
    snap = dict(item.mx_calculation_snapshot)
    res = dict(snap["result"])
    res["concepts"] = [{**res["concepts"][0], "isr_exempt": "-1.00"}]               # SYNTHETIC negative bucket
    item.mx_calculation_snapshot = {**snap, "result": res}
    db.commit()
    out = mexico_cfdi_preview.validate_run(db, w.run, w.users[0].id)
    assert out["refused"] == 1 and out["codes"] == {"MX_CFDI_NEGATIVE_BUCKET": 1}     # conflict: negative bucket
    assert _L().design_state(db, item)["state"] == "VALIDATION_FAILED"


def test_every_repo_status_has_a_design_state():
    from app.modules.payroll import mexico_cfdi_service

    assert set(_L().DOCUMENT_STATE_MAP) == set(mexico_cfdi_service.STATUSES)
    assert _L().DOCUMENT_STATE_MAP["UNKNOWN"] == "UNKNOWN"                           # kept: stricter than the design


# ── decision table: PAC unreachable ──────────────────────────────────────────

def test_pac_unreachable_invents_nothing_and_surfaces_for_tax_ops(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_service as S
    from app.modules.payroll import mexico_payslip_service

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC03")
    doc = _stamp(db, monkeypatch, w, stamp=["timeout"])
    assert doc.status == "UNKNOWN" and doc.uuid is None
    assert _L().design_state(db, item, doc)["state"] == "UNKNOWN"
    view = mexico_payslip_service.recibo_view(db, item, w.run)
    assert view["fiscal"]["sat"]["uuid"] == "NO DISPONIBLE" and "BORRADOR / NO TIMBRADO" in view["ribbon"]
    assert [d["id"] for d in S.lifecycle_overview(db, w.org.id)["unknown"]] == [doc.id]    # the tax-ops alert list
    assert _refusal(lambda: _L().publish(db, w.org.id, doc.id, w.users[0].id)) == "MX_CFDI_NOT_CURRENT"


# ── L2: envelope ─────────────────────────────────────────────────────────────

ENVELOPE_FIELDS = {"tenant_id", "employer_legal_entity_id", "jurisdiction", "state_code", "employee_id",
                   "payroll_run_id", "pay_period_start", "pay_period_end", "actual_payment_date",
                   "payroll_snapshot_hash", "effective_ruleset_version", "sat_catalog_release", "cfdi_schema_release",
                   "issuing_cert_id", "pac_transaction_id", "cfdi_uuid", "xml_sha256", "renderer_version",
                   "document_locale", "issue_status", "delivery_proof_id", "retention_policy_id", "supersedes_uuid"}


def test_envelope_has_every_field_and_no_identifier(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_service as S
    from tests.test_mexico_cfdi_builder import GOOD_IDS

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC04")
    doc = _stamp(db, monkeypatch, w)
    env = _L().envelope(db, w.org.id, doc.id)
    assert ENVELOPE_FIELDS <= set(env)
    assert env["jurisdiction"] == "MX" and env["cfdi_uuid"] == doc.uuid and env["xml_sha256"]
    assert env["payroll_snapshot_hash"] == item.mx_calculation_snapshot["inputHash"]
    assert env["document_locale"] == "es-MX" and env["issue_status"] == "STAMPED"
    assert env["derived_fields"] == []                                       # generated after L2: every fact stored
    version, _root, _cred = S._employer_for(db, item, w.run.pay_date)
    blob = json.dumps(env)
    assert all(v not in blob for v in (*GOOD_IDS.values(), version.rfc))


def test_envelope_of_a_pre_lifecycle_row_is_derived(db, monkeypatch, tmp_path):
    w, item = _ready(db, monkeypatch, tmp_path, "MXLC05")
    doc = _stamp(db, monkeypatch, w)
    for col in ("employer_profile_id", "state_code", "snapshot_hash", "ruleset_version", "issuing_cert_token"):
        setattr(doc, col, None)                                              # SYNTHETIC: a row from before L2
    db.commit()
    env = _L().envelope(db, w.org.id, doc.id)
    assert env["payroll_snapshot_hash"] == item.mx_calculation_snapshot["inputHash"] and env["issuing_cert_id"]
    assert set(env["derived_fields"]) == {"employer_legal_entity_id", "state_code", "payroll_snapshot_hash",
                                          "effective_ruleset_version", "issuing_cert_id"}


# ── L3: access log ───────────────────────────────────────────────────────────

def test_access_log_is_append_only_and_identifier_free(db, monkeypatch, tmp_path):
    from app.modules.payroll.models import PayrollMxDocumentAccessEvent as A

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC06")
    row = _L().record_access(db, w.org.id, "VIEWED", "RECIBO_VIEW", "UI", w.users[0].id, item_id=item.id,
                             employee_id=item.employee_id)
    row.channel = "API"
    with pytest.raises(ValueError, match="append-only"):
        db.commit()
    db.rollback()
    with pytest.raises(ValueError, match="append-only"):
        db.delete(db.get(A, row.id))
        db.commit()
    db.rollback()
    cols = {c.name for c in A.__table__.columns}
    assert not ({"rfc", "curp", "nss", "clabe", "postal_code", "content"} & cols)


def test_routes_log_every_view_and_download(db, monkeypatch, tmp_path):
    from tests._mx_employer_helpers import http, principal

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC07")
    doc = _stamp(db, monkeypatch, w)
    base = "/api/payroll/mexico"
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        assert c.get(f"{base}/payslips/{item.id}/recibo").status_code == 200
        assert c.get(f"{base}/payslips/{item.id}/recibo/duplicate").status_code == 200
        assert c.get(f"/api/payroll/payslips/{item.id}/download").status_code == 200
        xml = c.get(f"{base}/cfdi/documents/{doc.id}/xml")
        assert xml.status_code == 200 and doc.uuid.encode() in xml.content and xml.headers["cache-control"] == "no-store"
        env = c.get(f"{base}/cfdi/documents/{doc.id}/envelope")
        assert env.status_code == 200 and env.json()["cfdi_uuid"] == doc.uuid
        log = c.get(f"{base}/cfdi/documents/{doc.id}/access-log").json()
        lc = c.get(f"{base}/payslips/{item.id}/lifecycle").json()
    got = [(e["event"], e["artifact"]) for e in log]
    assert got == [("VIEWED", "RECIBO_VIEW"), ("DOWNLOADED", "DUPLICATE_PDF"), ("DOWNLOADED", "RECIBO_PDF"),
                   ("DOWNLOADED", "STAMPED_XML"), ("VIEWED", "ENVELOPE")]
    assert all(e["actorId"] == w.users[0].id for e in log) and lc["document"]["state"] == "STAMPED"


def test_the_stamped_xml_is_for_org_admins_only(db, monkeypatch, tmp_path):
    from tests._mx_employer_helpers import http, principal

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC08")
    doc = _stamp(db, monkeypatch, w)
    with http(db, principal(w.org.id, 702, role="payroll_admin")) as c:
        assert c.get(f"/api/payroll/mexico/cfdi/documents/{doc.id}/xml").status_code == 403
        assert c.post(f"/api/payroll/mexico/cfdi/documents/{doc.id}/publish").status_code == 403


# ── L4: the pay-event idempotency key ────────────────────────────────────────

def test_event_key_follows_the_formula_without_storing_rfcs(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_service as S
    from app.modules.payroll.models import PayrollEmployee

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC09")
    doc = _stamp(db, monkeypatch, w)
    version, _root, _cred = S._employer_for(db, item, w.run.pay_date)
    rfc = db.get(PayrollEmployee, item.employee_id).compliance_fields["rfc"]
    expected = _L().event_key(w.org.id, version.rfc, rfc, w.run.id, item.id, "ORDINARY",
                              item.mx_calculation_snapshot["inputHash"])
    assert doc.event_key == expected and doc.document_subtype == "ORDINARY"
    assert rfc not in doc.event_key and version.rfc not in doc.event_key and len(doc.event_key) == 64


def test_a_duplicate_payroll_event_is_refused_twice(db, monkeypatch, tmp_path):                        # conflict 4
    import sqlalchemy as sa

    from app.modules.payroll import mexico_cfdi_service as S
    from app.modules.payroll.models import PayrollMxCfdiDocument as Doc

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC10")
    doc_id = _stamp(db, monkeypatch, w).id
    S.generate(db, w.run, w.users[0].id)                                     # a second generate: nothing new
    assert db.query(Doc).filter(Doc.payslip_item_id == item.id).count() == 1
    db.expunge_all()
    twin = {c.name: getattr(db.get(Doc, doc_id), c.name) for c in Doc.__table__.columns if c.name != "id"}
    twin.update(idempotency_key="SYN-TWIN", folio="SYN-TWIN", uuid=None, payslip_item_id=item.id)
    db.add(Doc(**twin))
    with pytest.raises(sa.exc.IntegrityError):                                # the DB guard, same event key
        db.commit()
    db.rollback()


# ── L5: conflict checks that must REJECT ─────────────────────────────────────

def test_cross_tenant_uuid_linking_is_refused(db, monkeypatch, tmp_path):                              # conflict 1
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_cfdi_service as S
    from tests import _mx_cfdi_helpers as ch

    a = ch.committed_world(db, monkeypatch, tmp_path, code="MXLC11A")
    b = ch.committed_world(db, monkeypatch, tmp_path, code="MXLC11B")
    ch.mock(monkeypatch)
    for w in (a, b):
        S.generate(db, w.run, w.users[0].id)
        ch.process(db, w)
    (doc_a,), (doc_b,) = ch.docs(db, a.run), ch.docs(db, b.run)
    with pytest.raises(BadRequestException, match="STAMPED replacement"):
        S.cancel(db, a.org.id, doc_a.id, "SYN1", doc_b.uuid, a.users[0].id)  # B's UUID as A's replacement
    with pytest.raises(Exception):
        _L().envelope(db, a.org.id, doc_b.id)                                # nor read across tenants


def test_net_pay_mismatch_between_snapshot_xml_and_receipt_refuses(db, monkeypatch, tmp_path):        # conflict 3
    from decimal import Decimal as D

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC12")
    doc = _stamp(db, monkeypatch, w)
    item.net_pay, item.total_deductions = item.net_pay - D("1.00"), item.total_deductions + D("1.00")   # SYNTHETIC
    db.commit()
    assert _refusal(lambda: _L().publish(db, w.org.id, doc.id, w.users[0].id)) == "MX_CFDI_NET_MISMATCH"
    assert doc.published_at is None


def test_a_stale_catalog_after_its_effective_date_refuses(db, monkeypatch, tmp_path):                 # conflict 5
    from app.modules.payroll import mexico_cfdi_preview
    from app.modules.payroll import mexico_cfdi_service as S

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC13")
    release = S._active_release(db)
    release.effective_to = w.run.pay_date - timedelta(days=1)                # SYNTHETIC window
    db.commit()
    assert "MX_CFDI_CATALOG_STALE" in [r["code"] for r in S.preflight(db, w.run)["reasons"]]
    assert _refusal(lambda: mexico_cfdi_preview.validate_run(db, w.run, w.users[0].id)) == "MX_CFDI_CATALOG_STALE"
    release.effective_to, release.effective_from = None, w.run.pay_date + timedelta(days=1)
    db.commit()
    assert "MX_CFDI_CATALOG_STALE" in [r["code"] for r in S.preflight(db, w.run)["reasons"]]


def test_receiver_identity_mismatch_refuses_without_naming_the_value(db, monkeypatch, tmp_path):       # conflict 6
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollEmployee

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC14")
    doc = _stamp(db, monkeypatch, w)
    emp = db.get(PayrollEmployee, item.employee_id)
    emp.compliance_fields = {**emp.compliance_fields, "rfc": "XAXX010101000"}    # SYNTHETIC change after stamping
    db.commit()
    with pytest.raises(MXBlock) as exc:
        _L().publish(db, w.org.id, doc.id, w.users[0].id)
    assert exc.value.key == "MX_CFDI_IDENTITY_MISMATCH" and "RFC" in str(exc.value)
    assert "XAXX010101000" not in str(exc.value) and "LOAV" not in str(exc.value)


def test_unsigned_or_unstamped_xml_is_never_issued(db, monkeypatch, tmp_path):                         # conflict 7
    from app.modules.payroll import mexico_payslip_service

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC15")
    doc = _stamp(db, monkeypatch, w)
    monkeypatch.setattr("app.modules.payroll.mexico_cfdi_service.stamped_xml_ref", lambda db, d: None)
    assert _refusal(lambda: _L().publish(db, w.org.id, doc.id, w.users[0].id)) == "MX_CFDI_NOT_STAMPED_XML"
    view = mexico_payslip_service.recibo_view(db, item, w.run)
    assert view["fiscal"]["label"] == "NO VERIFICABLE" and "CFDI TIMBRADO" not in view["ribbon"]


def test_a_cancelled_uuid_is_never_presented_as_current(db, monkeypatch, tmp_path):                   # conflict 8
    w, item = _ready(db, monkeypatch, tmp_path, "MXLC16")
    doc = _stamp(db, monkeypatch, w)
    doc.status = "CANCELLED"                                                # SYNTHETIC
    db.commit()
    assert _refusal(lambda: _L().publish(db, w.org.id, doc.id, w.users[0].id)) == "MX_CFDI_NOT_CURRENT"
    assert _L().envelope(db, w.org.id, doc.id)["issue_status"] == "CANCEL_ACCEPTED"


def test_cancel_outcomes_are_recorded(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_service as S
    from tests import _mx_cfdi_helpers as ch

    w = ch.committed_world(db, monkeypatch, tmp_path, code="MXLC17")
    ch.mock(monkeypatch, cancel=["reject"])
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    S.cancel(db, w.org.id, doc.id, "SYN2", None, w.users[0].id)
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "STAMPED" and doc.cancel_outcome == "CANCEL_REJECTED"
    ch.mock(monkeypatch, cancel=["accept"])
    S.cancel(db, w.org.id, doc.id, "SYN2", None, w.users[0].id)
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "CANCELLED" and doc.cancel_outcome == "CANCEL_ACCEPTED"


def test_delivery_needs_a_published_document_and_a_proof(db, monkeypatch, tmp_path):
    from app.core.exceptions import BadRequestException

    w, item = _ready(db, monkeypatch, tmp_path, "MXLC18")
    doc = _stamp(db, monkeypatch, w)
    assert _refusal(lambda: _L().record_delivery(db, w.org.id, doc.id, "DELIVERED", "PORTAL", "P", 1)) == \
        "MX_CFDI_NOT_PUBLISHED"
    _L().publish(db, w.org.id, doc.id, w.users[0].id)
    with pytest.raises(BadRequestException):
        _L().record_delivery(db, w.org.id, doc.id, "DELIVERED", "PORTAL", "", 1)
    out = _L().record_delivery(db, w.org.id, doc.id, "DELIVERY_FAILED", "EMAIL", None, w.users[0].id)
    assert out["deliveryStatus"] == "DELIVERY_FAILED"
    assert _L().design_state(db, item, doc)["state"] == "DELIVERY_FAILED"

"""Mexico Phase 11c — the validate-only CFDI preview (MEXICO_PHASE_11_PLAN.md
§4.7, D3 + D5): builds and validates in memory against an Approved release,
returns pass/fail + redacted findings + a payload hash, never the XML, and
stores only an audited summary. SYNTHETIC."""

import re

import pytest

from tests.test_mexico_cfdi_builder import BAD_CURP, GOOD_IDS, _ready_world


def _P():
    from app.modules.payroll import mexico_cfdi_preview

    return mexico_cfdi_preview


def _nothing_written(db, w):
    from app.modules.payroll.models import PayrollMxCfdiDocument, PayrollMxCfdiOutboxItem

    assert db.query(PayrollMxCfdiDocument).filter(PayrollMxCfdiDocument.payroll_run_id == w.run.id).count() == 0
    assert db.query(PayrollMxCfdiOutboxItem).count() == 0


def test_until_the_sdi_source_is_decided_every_receipt_shows_that_refusal(db, monkeypatch, tmp_path):
    w = _ready_world(db, monkeypatch, tmp_path, "MXPV1", sdi=False)
    out = _P().validate_run(db, w.run, w.users[0].id)
    assert out["payslips"] >= 1 and out["valid"] == 0 and out["refused"] == out["payslips"]
    assert {r["code"] for r in out["results"]} == {"MX_CFDI_INPUT_MISSING"}
    assert out["awaitingG1Decision"] is True
    assert any("SalarioDiarioIntegrado" in m and "G1 decision" in m for m in out["awaitingDecisions"])
    assert all(r["payloadSha256"] is None for r in out["results"])
    _nothing_written(db, w)


def test_a_receipt_that_builds_returns_its_hash_and_never_its_xml(db, monkeypatch, tmp_path):
    from app.modules.payroll.models import TaxConfigurationAudit as A

    uploads = tmp_path / "uploads"
    w = _ready_world(db, monkeypatch, tmp_path, "MXPV2")
    out = _P().validate_run(db, w.run, w.users[0].id)
    assert out["valid"] == out["payslips"] >= 1 and out["refused"] == 0, out["results"]
    (r,) = out["results"]
    assert re.fullmatch(r"[0-9a-f]{64}", r["payloadSha256"]) and r["findings"] == []
    assert "<cfdi" not in repr(out) and "Comprobante" not in repr(out) and GOOD_IDS["curp"] not in repr(out)
    _nothing_written(db, w)
    assert not uploads.exists() or not any(uploads.rglob("*.xml"))             # nothing stored
    audit = db.query(A).filter(A.entity_type == "mx_cfdi_validation").one()
    assert audit.new_value["valid"] == 1 and audit.new_value["payloadHashes"] == [r["payloadSha256"]]
    assert "employeeName" not in repr(audit.new_value) and GOOD_IDS["rfc"] not in repr(audit.new_value)


def test_an_approved_release_is_enough_and_preconditions_refuse(db, monkeypatch, tmp_path):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxCfdiSchemaRelease as Rel

    w = _ready_world(db, monkeypatch, tmp_path, "MXPV3")
    for rel in db.query(Rel).all():
        rel.status = "Approved"                                                  # D3: not Active
    db.commit()
    assert _P().validate_run(db, w.run, w.users[0].id)["releaseStatus"] == "Approved"
    for rel in db.query(Rel).all():
        rel.status = "Draft"
    db.commit()
    with pytest.raises(MXBlock) as exc:
        _P().validate_run(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CFDI_NO_APPROVED_RELEASE"
    w.run.status = "Draft"
    db.commit()
    with pytest.raises(MXBlock) as exc:
        _P().validate_run(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CFDI_RUN_NOT_COMMITTED"


def test_preview_routes_and_the_super_admin_summary_carry_no_worker_data(db, monkeypatch, tmp_path):
    from tests import test_mexico_pilot as tp
    from tests._mx_employer_helpers import http

    w = _ready_world(db, monkeypatch, tmp_path, "MXPV4", ids={**GOOD_IDS, "curp": BAD_CURP})
    with http(db, w.users[0]) as c:
        r = c.post(f"/api/payroll/mexico/runs/{w.run.id}/cfdi/validate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] == 1 and body["results"][0]["code"] == "MX_CFDI_XSD_INVALID"
    assert body["results"][0]["findings"] == [{"rule": "MX_CFDI_XSD_INVALID",
                                               "message": "Receptor@Curp: SCHEMAV_CVC_PATTERN_VALID"}]
    assert BAD_CURP not in r.text and BAD_CURP[4:16] not in r.text and "<cfdi" not in r.text
    with http(db, tp.SA_A) as c:
        summaries = c.get("/api/super-admin/compliance/mexico/cfdi/validations",
                          params={"organization_id": w.org.id}).json()
    assert [s["refused"] for s in summaries] == [1] and summaries[0]["codes"] == {"MX_CFDI_XSD_INVALID": 1}
    assert "employeeName" not in repr(summaries) and BAD_CURP not in repr(summaries)
    _nothing_written(db, w)

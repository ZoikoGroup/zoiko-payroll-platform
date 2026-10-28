"""Mexico final mile X3 — the eight reports the spec calls for that the catalog
lacked (spec §7, §10, §13, §14, §20): run variance, preflight exceptions, SBC
movements, work-risk premium history, INFONAVIT notices, labour compliance,
the payment worklist and the identifier-access audit. Built from Mexico's own
service views, immutable with supersession, refused by the generic generator,
gated at activation, and free of full identifiers. SYNTHETIC worlds only."""

import json

import pytest

from tests.test_mexico_report_generators import _R, _active, _seed, _world

X3 = {"MX-RUN-VARIANCE": "MX_RUN_VARIANCE", "MX-PREFLIGHT-EXCEPTIONS": "MX_PREFLIGHT",
      "MX-SBC-MOVEMENTS": "MX_SBC_MOVEMENTS", "MX-WORK-RISK-ANNUAL": "MX_WORK_RISK",
      "MX-INFONAVIT-NOTICES": "MX_INFONAVIT_NOTICES", "MX-LABOR-COMPLIANCE": "MX_LABOR_COMPLIANCE",
      "MX-PAYMENT-WORKLIST": "MX_PAYMENT_WORKLIST", "MX-IDENTIFIER-ACCESS-AUDIT": "MX_ID_ACCESS_AUDIT"}
RUN_SCOPED = ("MX-RUN-VARIANCE", "MX-PREFLIGHT-EXCEPTIONS", "MX-LABOR-COMPLIANCE", "MX-PAYMENT-WORKLIST")


def _generate(db, w, templates, key, **params):
    if key in RUN_SCOPED:
        params.setdefault("run_id", w.run.id)
    return _R().mx_report_generate(db, w.org.id, _active(db, templates[key]).id, params, w.users[0].id)


def test_the_catalog_now_has_every_x3_template_and_the_generic_generator_refuses_them(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from tests import _mx_authority_helpers as ah

    w = ah.committed_world(db, monkeypatch, code="MXX3A")
    templates = _seed(db)
    assert set(X3) <= set(templates) and all(templates[k].status == "Draft" for k in X3)
    assert set(service.MX_DEDICATED_GENERATOR_REPORT_TYPES) >= set(X3.values())
    for key in X3:
        assert templates[key].description.startswith("No components:")
        with pytest.raises(BadRequestException, match="dedicated Mexico generator"):
            service.generate_report_from_template(db, w.org.id, _active(db, templates[key]).id, w.run.id,
                                                  reporting_period="x", actor_id=None)


def test_each_x3_report_is_built_from_the_service_views_with_no_full_identifier(db, monkeypatch):
    w = _world(db, monkeypatch, "MXX3B")
    templates = _seed(db)
    ids = [v for k, v in (w.employee.compliance_fields or {}).items() if k in ("rfc", "curp", "nss", "clabe") and v]
    assert ids
    for key, rtype in X3.items():
        out = _generate(db, w, templates, key)
        assert out["reportType"] == rtype and out["status"] == "Generated", key
        blob = json.dumps(out["renderedData"], default=str)
        assert not any(i in blob for i in ids), key                                  # MX-061
    sbc = _generate(db, w, templates, "MX-SBC-MOVEMENTS")["renderedData"]["data"]
    assert sbc["sbc"] and sbc["movements"]
    labor = _generate(db, w, templates, "MX-LABOR-COMPLIANCE")["renderedData"]["data"]
    assert labor["runId"] == w.run.id and labor["employees"][0]["employee"] == w.employee.employee_code
    risk = _generate(db, w, templates, "MX-WORK-RISK-ANNUAL")
    assert "NOT AN OFFICIAL FILE" in risk["officialLayout"] and risk["renderedData"]["data"]["reviewYearCases"] is None


def test_run_variance_flags_nothing_until_d24_is_approved(db, monkeypatch):
    from decimal import Decimal as D

    from app.modules.payroll import mexico_decision_service as S
    from app.modules.payroll.models import PayrollMxDecision as M
    from tests import _mx_authority_helpers as ah

    w = _world(db, monkeypatch, "MXX3C")
    second = ah.commit(db, w, ah.new_run(db, w))
    templates = _seed(db)
    first = _generate(db, w, templates, "MX-RUN-VARIANCE", run_id=second.id)["renderedData"]["data"]
    assert first["priorRunId"] == w.run.id and first["threshold"]["value"] is None and "D-24" in first["threshold"]["note"]
    emp = first["employees"][0]
    assert emp["status"] == "BOTH" and emp["highValue"] is None and emp["lines"]["net"]["delta"] is not None
    S.seed_decisions(db)
    db.commit()
    did = db.query(M).filter(M.code == "D-24").one().id
    with pytest.raises(Exception):
        S.propose_mx_decision(db, did, {"chosen_option": "a lot", "rationale": "SYNTHETIC", "cited_sources": ["spec §13"]},
                              w.users[0].id)
    S.propose_mx_decision(db, did, {"chosen_option": "0", "rationale": "SYNTHETIC", "cited_sources": ["spec §13"]},
                          w.users[0].id)
    S.approve_mx_decision(db, did, w.users[1].id)
    flagged = _generate(db, w, templates, "MX-RUN-VARIANCE", run_id=second.id)["renderedData"]["data"]
    assert flagged["threshold"]["value"] == "0" and flagged["employees"][0]["highValue"] is True
    assert D(flagged["employees"][0]["lines"]["net"]["current"]) >= 0


def test_variance_needs_a_committed_run_of_the_organisation(db, monkeypatch):
    from app.core.exceptions import BadRequestException, NotFoundException
    from tests import _mx_authority_helpers as ah

    w = _world(db, monkeypatch, "MXX3D")
    templates = _seed(db)
    draft = ah.new_run(db, w)
    with pytest.raises(BadRequestException, match="not committed"):
        _generate(db, w, templates, "MX-RUN-VARIANCE", run_id=draft.id)
    with pytest.raises(NotFoundException):
        _generate(db, w, templates, "MX-PREFLIGHT-EXCEPTIONS", run_id=999999)
    with pytest.raises(BadRequestException, match="run_id"):
        _R().mx_report_generate(db, w.org.id, _active(db, templates["MX-LABOR-COMPLIANCE"]).id, {}, w.users[0].id)


def test_receipt_renders_are_audited_and_reported_without_identifiers(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_receipt
    from tests.test_mexico_cfdi_receipt import _stamped

    w, doc = _stamped(db, monkeypatch, tmp_path, "MXX3E")
    mexico_cfdi_receipt.mx_cfdi_receipt_pdf(db, w.org.id, doc.id)
    mexico_cfdi_receipt.record_render(db, w.org.id, doc.id, w.users[0].id)
    mexico_cfdi_receipt.record_render(db, w.org.id + 999, doc.id, w.users[0].id)            # another tenant: nothing
    templates = _seed(db)
    out = _R().mx_report_generate(db, w.org.id, _active(db, templates["MX-IDENTIFIER-ACCESS-AUDIT"]).id, {},
                                  w.users[0].id)
    (row,) = out["renderedData"]["data"]["renders"]
    assert (row["documentId"], row["actorId"]) == (doc.id, w.users[0].id)
    blob = json.dumps(out["renderedData"], default=str)
    assert not any(v and v in blob for k, v in (w.employee.compliance_fields or {}).items()
                   if k in ("rfc", "curp", "nss"))


def test_the_activation_gate_covers_every_x3_type(db, monkeypatch):
    from tests import _mx_authority_helpers as ah

    ah.committed_world(db, monkeypatch, code="MXX3F")
    templates = _seed(db)
    for key in X3:
        refusal = _R().mx_report_activation_refusal(db, templates[key])
        assert refusal and "not SIGNED" in refusal and "is not a Mexico report type" not in refusal, key


# ── X3b: the template library tools ──────────────────────────────────────────

@pytest.fixture()
def library(db):
    from app.modules.payroll import mexico_decision_service
    from scripts.seed_mexico_canonical_packs import seed_mexico as seed_packs

    seed_packs(db)
    mexico_decision_service.seed_decisions(db)
    templates = _seed(db)
    db.commit()
    return templates


def test_coverage_lists_every_template_with_its_build_kind_and_catalog_check(db, library):
    rows = {r["templateKey"]: r for r in _R().mx_template_coverage(db)}
    assert set(library) == set(rows)
    assert rows["MX-PAYROLL-REGISTER"]["kind"] == "TEMPLATE_ENGINE"
    assert "catalogued" in rows["MX-PAYROLL-REGISTER"]["fieldProof"]
    assert rows["MX-RUN-VARIANCE"]["kind"] == "DEDICATED" and rows["MX-RUN-VARIANCE"]["gates"] == ["G1", "G8"]
    assert rows["MX-CFDI-NOMINA-RECEIPT"]["kind"] == "RECEIPT"


def test_compare_two_templates(db, library):
    a, b = library["MX-PAYROLL-REGISTER"], library["MX-EMPLOYER-COST"]
    same = _R().mx_compare_templates(db, a.id, a.id)
    assert same["identical"] is True and same["from"]["contentHash"] == same["to"]["contentHash"]
    diff = _R().mx_compare_templates(db, a.id, b.id)
    assert diff["identical"] is False and (diff["added"] or diff["removed"]) and "template_key" in diff["metadata"]


def test_sandbox_preview_is_watermarked_and_only_for_snapshot_templates(db, library):
    from app.core.exceptions import BadRequestException

    R = _R()
    reg = library["MX-PAYROLL-REGISTER"].id
    blocked = R.mx_template_sandbox_preview(db, reg, {"payDate": "2026-06-15", "dailySalary": "600"})
    assert blocked["outcome"] == "BLOCKED" and blocked["block"]["code"] == "MX_ROUNDING_RULE_MISSING"
    out = R.mx_template_sandbox_preview(db, reg, {
        "payDate": "2026-06-15", "periodStart": "2026-06-01", "periodEnd": "2026-06-15", "dailySalary": "600",
        "candidates": [{"decision": "D-01", "value": "HALF_UP:0.01"}, {"decision": "D-03", "value": "GENERAL"}]})
    assert out["outcome"] == "CALCULATED"
    assert {"CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR", R.SANDBOX_PREVIEW_MARK} <= set(out["watermarks"])
    gross = [f for f in out["fields"] if f["source"] == "mx_calculation_snapshot.result.gross"]
    assert gross and gross[0]["value"] == "9000.0000"
    with pytest.raises(BadRequestException, match="no payslip preview"):
        R.mx_template_sandbox_preview(db, library["MX-RUN-VARIANCE"].id, {"payDate": "2026-06-15", "dailySalary": "1"})


def test_the_library_routes_are_super_admin_only(db, library):
    from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, _http

    reg = library["MX-PAYROLL-REGISTER"].id
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/report-templates/coverage").status_code == 403
        assert c.get(f"{BASE}/report-templates/compare", params={"from": reg, "to": reg}).status_code == 403
        assert c.post(f"{BASE}/report-templates/{reg}/sandbox-preview", json={}).status_code == 403
    with _http(db, SA_A) as c:
        assert c.get(f"{BASE}/report-templates/coverage").status_code == 200
        assert c.get(f"{BASE}/report-templates/compare", params={"from": reg, "to": reg}).json()["identical"] is True

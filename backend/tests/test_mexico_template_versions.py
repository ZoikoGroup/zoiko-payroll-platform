"""Mexico report-template versions: every version of every Mexico template with
its activation-gate answer and content hash, and "new version" — a Draft copy
of the CHOSEN version (metadata, components and fields), the rollback path. The
copy stays behind the activation gate. The real Draft templates seeded by the
deployment script; SYNTHETIC edits only where a test says so."""

import pytest

from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, _http


@pytest.fixture()
def templates(db):
    from tests.test_mexico_report_generators import _seed

    return _seed(db)


def _R():
    from app.modules.payroll import mexico_report_service

    return mexico_report_service


def test_versions_list_every_template_with_its_gate_answer(db, templates):
    out = {g["templateKey"]: g for g in _R().mx_template_versions(db)}
    assert set(templates) <= set(out)
    reg = out["MX-PAYROLL-REGISTER"]
    (v,) = reg["versions"]
    assert v["status"] == "Draft" and v["fields"] > 0 and len(v["contentHash"]) == 64
    assert v["activationRefusal"]                                  # no gate signed, no Active content: refused
    assert out["MX-RUN-VARIANCE"]["kind"] == "DEDICATED"


def test_a_new_version_copies_the_chosen_version_not_the_latest(db, templates):
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent, ReportTemplateComponentField

    v1 = templates["MX-PAYROLL-REGISTER"]
    v2 = _R().mx_template_new_version(db, v1.id, "2.0", "SYNTHETIC: start a field correction", SA_A.id)
    assert v2["status"] == "Draft" and v2["fields"] == len(_R()._mx_report_fields(db, v1)) > 0
    assert _R().mx_compare_templates(db, v1.id, v2["id"])["changed"] == []
    # A correction on v2.0 (SYNTHETIC label edit).
    comp = db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == v2["id"]).first()
    field = db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == comp.id).first()
    field.label = "SYNTHETIC corrected label"
    db.commit()
    assert _R().mx_compare_templates(db, v1.id, v2["id"])["changed"]
    # Rollback: a copy of v1 (not of the latest, v2.0) has v1's content.
    v3 = _R().mx_template_new_version(db, v1.id, "3.0", "SYNTHETIC: roll back to v1", SA_A.id)
    same = _R().mx_compare_templates(db, v1.id, v3["id"])
    assert same["added"] == [] and same["removed"] == [] and same["changed"] == []
    assert _R().mx_compare_templates(db, v2["id"], v3["id"])["changed"]
    row = db.get(ReportTemplate, v3["id"])
    assert (row.status, row.approved_by_id, row.previous_version_id) == ("Draft", None, v1.id)
    assert row.report_type == v1.report_type and "roll back to v1" in row.change_summary
    assert _R().mx_report_activation_refusal(db, row)                  # the copy is still behind the gate


def test_a_new_version_needs_a_reason_and_a_unique_version_and_is_audited(db, templates):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll.models import ReportTemplate, TaxConfigurationAudit as A

    v1 = templates["MX-RUN-VARIANCE"]                                  # a dedicated (no-field) template too
    with pytest.raises(BadRequestException, match="reason"):
        _R().mx_template_new_version(db, v1.id, "2.0", " ", SA_A.id)
    made = _R().mx_template_new_version(db, v1.id, "2.0", "SYNTHETIC", SA_A.id)
    assert made["fields"] == 0
    with pytest.raises(BadRequestException, match="already exists"):
        _R().mx_template_new_version(db, v1.id, "2.0", "SYNTHETIC", SA_A.id)
    assert db.query(A).filter(A.entity_type == "report_template", A.action == "new_version",
                              A.entity_id == made["id"]).one().actor_id == SA_A.id
    other = ReportTemplate(template_key="US-TV-TEST", name="x", report_type="W2", jurisdiction_country="US",
                           reporting_year="2026", version="1.0", status="Draft")
    db.add(other)
    db.commit()
    with pytest.raises(NotFoundException):
        _R().mx_template_new_version(db, other.id, "2.0", "x", SA_A.id)


def test_the_template_version_routes_are_super_admin_only(db, templates):
    v1 = templates["MX-EMPLOYER-COST"]
    with _http(db, SA_A) as c:
        assert c.get(f"{BASE}/report-templates/versions").status_code == 200
        made = c.post(f"{BASE}/report-templates/{v1.id}/new-version", json={"version": "2.0", "reason": "SYNTHETIC"})
        assert made.status_code == 200 and made.json()["status"] == "Draft"
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/report-templates/versions").status_code in (401, 403)
        assert c.post(f"{BASE}/report-templates/{v1.id}/new-version",
                      json={"version": "3.0", "reason": "x"}).status_code in (401, 403)

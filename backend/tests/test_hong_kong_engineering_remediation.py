"""
tests/test_hong_kong_engineering_remediation.py
-----------------------------------------------
Hong Kong final engineering remediation (2026-10-05) — one regression block
per verified audit gap:

* Gap 1 evidence integrity: HK decision / production-verification evidence is
  reviewed only once a document exists; reviewed HK evidence and hash-pinned
  HK sources are never replaced in place; an upload must match the registered
  SHA-256; a download re-verifies the stored bytes; HK evidence changes only by
  supersession (old row kept, replacement counts only once reviewed by another
  Super Admin). Singapore and untagged (other-country) artifacts unchanged.

Every artifact here is TEST-ONLY data — never production evidence.
"""

import hashlib

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk  # noqa: F401


def _art(db, form_number=None, *, checksum=None, file_path=None, created_by=MAKER.id, agency="Zoiko test"):
    from app.modules.payroll.models import SourceArtifact

    a = SourceArtifact(agency=agency, title=f"TEST {form_number or 'source'}", form_number=form_number,
                       checksum_sha256=checksum, file_path=file_path, created_by_id=created_by)
    db.add(a)
    db.commit()
    return a


@pytest.fixture()
def storage(monkeypatch):
    """In-memory object storage (no files written)."""
    from app.core import object_storage

    blobs = {}

    def save_upload(*, subdir, filename, data):
        ref = f"mem://{subdir}/{filename}"
        blobs[ref] = data
        return ref

    monkeypatch.setattr(object_storage, "save_upload", save_upload)
    monkeypatch.setattr(object_storage, "read_bytes", lambda ref: blobs[ref])
    monkeypatch.setattr(object_storage, "delete_ref", lambda ref: blobs.pop(ref, None))
    return blobs


def _hk_cited_source(db, content: bytes):
    """A source cited by a canonical HK rate row, registered with `content`'s SHA-256."""
    from app.modules.payroll.models import ContributionRate

    src = _art(db, checksum=hashlib.sha256(content).hexdigest(), agency="Inland Revenue Department")
    rate = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_country == "HK",
                                              ContributionRate.organization_id.is_(None)).first())
    rate.source_document_id = src.id
    db.commit()
    return src


# ── Gap 1: evidence integrity ───────────────────────────────────────────

@pytest.mark.parametrize("tag", ["HK-DECISION-D-1", "HK-PRODUCTION-VERIFICATION", "HK-GATE-G3"])
def test_hk_evidence_of_every_kind_needs_an_uploaded_document_before_review(db, tag):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    art = _art(db, tag)
    with pytest.raises(BadRequestException, match="uploaded document"):
        service.mark_source_artifact_reviewed(db, art.id, CHECKER.id)
    db.refresh(art)
    assert art.reviewer_id is None


def test_a_reviewed_hk_evidence_file_cannot_be_replaced_in_place(db, storage):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service, service

    art = _art(db, "HK-DECISION-D-2")
    service.upload_source_artifact_file(db, art.id, "d2.pdf", "application/pdf", b"signed D-2", actor_id=MAKER.id)
    # Before review a mistaken upload may still be corrected.
    service.upload_source_artifact_file(db, art.id, "d2.pdf", "application/pdf", b"signed D-2 v2", actor_id=MAKER.id)
    service.mark_source_artifact_reviewed(db, art.id, CHECKER.id)
    reviewed_hash = art.checksum_sha256
    with pytest.raises(BadRequestException, match="cannot be replaced"):
        service.upload_source_artifact_file(db, art.id, "other.pdf", "application/pdf", b"different", actor_id=MAKER.id)
    db.refresh(art)
    assert art.checksum_sha256 == reviewed_hash == hashlib.sha256(b"signed D-2 v2").hexdigest()
    assert next(d for d in hong_kong_service.owner_decisions(db) if d["key"] == "D-2")["state"] == "RECORDED"


def test_a_hash_pinned_hk_source_accepts_only_the_document_that_was_hashed(db, hk, storage):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    official = b"official IRD PAM 61(e) bytes"
    src = _hk_cited_source(db, official)
    with pytest.raises(BadRequestException, match="does not match the hash registered"):
        service.upload_source_artifact_file(db, src.id, "pam.pdf", "application/pdf", b"a different file", actor_id=MAKER.id)
    db.refresh(src)
    assert src.file_path is None and src.checksum_sha256 == hashlib.sha256(official).hexdigest()
    refused = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "source_artifact",
                                                      TaxConfigurationAudit.entity_id == src.id,
                                                      TaxConfigurationAudit.action == "refused").all())
    assert len(refused) == 1
    stored = service.upload_source_artifact_file(db, src.id, "pam.pdf", "application/pdf", official, actor_id=MAKER.id)
    assert stored.file_path and stored.checksum_sha256 == hashlib.sha256(official).hexdigest()
    service.mark_source_artifact_reviewed(db, src.id, CHECKER.id)
    with pytest.raises(BadRequestException, match="cannot be replaced"):
        service.upload_source_artifact_file(db, src.id, "pam.pdf", "application/pdf", official, actor_id=MAKER.id)


def test_download_of_hk_evidence_detects_content_drift(db, hk, storage):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    official = b"official MPFA bytes"
    src = _hk_cited_source(db, official)
    service.upload_source_artifact_file(db, src.id, "mpf.pdf", "application/pdf", official, actor_id=MAKER.id)
    data, _ctype, _name = service.download_source_artifact_file(db, src.id)
    assert data == official
    storage[src.file_path] = b"tampered"
    with pytest.raises(BadRequestException, match="no longer matches"):
        service.download_source_artifact_file(db, src.id)


def test_hk_evidence_changes_only_by_supersession_and_the_replacement_needs_its_own_review(db, storage):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import TaxConfigurationAudit

    def state():
        return next(d for d in hong_kong_service.owner_decisions(db) if d["key"] == "D-3")

    old = _art(db, "HK-DECISION-D-3")
    service.upload_source_artifact_file(db, old.id, "d3.pdf", "application/pdf", b"D-3 decision", actor_id=MAKER.id)
    service.mark_source_artifact_reviewed(db, old.id, CHECKER.id)
    assert state()["state"] == "RECORDED" and state()["artifactId"] == old.id

    wrong_tag = _art(db, "HK-DECISION-D-4")
    with pytest.raises(BadRequestException, match="same evidence tag"):
        service.supersede_governed_evidence(db, old.id, wrong_tag.id, actor_id=MAKER.id)
    with pytest.raises(BadRequestException, match="itself"):
        service.supersede_governed_evidence(db, old.id, old.id, actor_id=MAKER.id)

    new = _art(db, "HK-DECISION-D-3")
    service.upload_source_artifact_file(db, new.id, "d3b.pdf", "application/pdf", b"D-3 revised", actor_id=MAKER.id)
    service.supersede_governed_evidence(db, old.id, new.id, actor_id=MAKER.id)
    db.refresh(old)
    assert old.superseded_by_id == new.id and old.file_path and old.reviewer_id == CHECKER.id   # kept, auditable
    assert state()["state"] == "SUBMITTED"            # withdrawing acceptance never grants it
    service.mark_source_artifact_reviewed(db, new.id, CHECKER.id)
    assert state()["state"] == "RECORDED" and state()["artifactId"] == new.id
    with pytest.raises(BadRequestException, match="already superseded"):
        service.supersede_governed_evidence(db, old.id, new.id, actor_id=MAKER.id)
    assert (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "source_artifact",
                                                   TaxConfigurationAudit.entity_id == old.id,
                                                   TaxConfigurationAudit.reason.like("%superseded by%")).count() == 1)


def test_hk_gate_state_follows_the_superseding_evidence_version(db, storage):
    from app.modules.payroll import hong_kong_service, service

    g1 = _art(db, "HK-GATE-G1")
    service.upload_source_artifact_file(db, g1.id, "g1.pdf", "application/pdf", b"G1 sign-off", actor_id=MAKER.id)
    service.mark_source_artifact_reviewed(db, g1.id, CHECKER.id)
    assert hong_kong_service.gate_state(db, "G1") == "PASS"
    g1b = _art(db, "HK-GATE-G1")
    service.supersede_governed_evidence(db, g1.id, g1b.id, actor_id=MAKER.id)
    assert hong_kong_service.gate_state(db, "G1") == "SUBMITTED"


def test_singapore_evidence_supersession_is_unchanged_through_the_dispatcher(db, storage):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    a = _art(db, "SG-GATE-G2")
    b = _art(db, "SG-GATE-G2")
    service.supersede_governed_evidence(db, a.id, b.id, actor_id=MAKER.id)
    db.refresh(a)
    assert a.superseded_by_id == b.id
    plain = _art(db, None)
    other = _art(db, None)
    with pytest.raises(BadRequestException, match="Only Singapore gate / decision evidence"):
        service.supersede_governed_evidence(db, plain.id, other.id, actor_id=MAKER.id)


def test_an_untagged_other_country_source_keeps_the_original_upload_behaviour(db, storage):
    """No hash pinning outside the opted-in countries: the upload's own hash
    replaces a hand-typed one, and a reviewed file may be re-uploaded."""
    from app.modules.payroll import service

    src = _art(db, None, checksum="f" * 64, agency="IRS")
    up = service.upload_source_artifact_file(db, src.id, "p15t.pdf", "application/pdf", b"pub 15-T", actor_id=MAKER.id)
    assert up.checksum_sha256 == hashlib.sha256(b"pub 15-T").hexdigest()
    service.mark_source_artifact_reviewed(db, src.id, CHECKER.id)
    again = service.upload_source_artifact_file(db, src.id, "p15t.pdf", "application/pdf", b"pub 15-T v2", actor_id=MAKER.id)
    assert again.checksum_sha256 == hashlib.sha256(b"pub 15-T v2").hexdigest()


# ── Gap 2: HK statutory-row editor identity ─────────────────────────────

def test_hk_row_edits_record_the_maker_and_no_editor_of_the_version_can_approve_it(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxConfigurationAudit

    A, B, C = 101, 202, 303
    src = _art(db, "HK-SOURCE-TEST")
    draft = hong_kong_service.new_version(db, hk.packs[1].id, "1.1", "TEST change", A)
    rate = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == draft.id,
                                              ContributionRate.component_key == "mpf_employee_rate").one())
    hong_kong_service.update_row(db, "rate", rate.id, {"employeeRatePct": "0.06", "reason": "TEST by B",
                                                      "sourceDocumentId": src.id}, B)
    assert db.get(JurisdictionPack, draft.id).updated_by_id == B
    hong_kong_service.update_row(db, "rate", rate.id, {"employeeRatePct": "0.055", "reason": "TEST by C",
                                                      "sourceDocumentId": src.id}, C)
    assert db.get(JurisdictionPack, draft.id).updated_by_id == C
    assert hong_kong_service.statutory_editors(db, draft) == {B, C}
    for editor in (B, C):              # B is not the LAST editor, but made one of this version's edits
        with pytest.raises(BadRequestException, match="maker-checker"):
            service.set_jurisdiction_pack_approver(db, draft.id, actor_id=editor)
    refused = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                      TaxConfigurationAudit.entity_id == draft.id,
                                                      TaxConfigurationAudit.action == "refused").count())
    assert refused == 2
    approved = service.set_jurisdiction_pack_approver(db, draft.id, actor_id=A)
    assert approved.approved_by_id == A
    hong_kong_service.update_row(db, "rate", rate.id, {"employeeRatePct": "0.05", "reason": "TEST revert",
                                                      "sourceDocumentId": src.id}, B)
    assert db.get(JurisdictionPack, draft.id).approved_by_id is None          # the edit invalidated A's approval


# ── Gap 3: report-template component / field maker identity + audit ─────

def _draft_template(db, country="HK", report_type="HK_IR56B", key="HK-TEST-REMEDIATION", actor=101, year="2025/26"):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name="TEST template", reportType=report_type, jurisdictionCountry=country,
        reportingYear=year, documentScope="PER_EMPLOYEE", changeSummary="TEST"), actor_id=actor)
    allowed = service.get_available_report_components(report_type)
    comp = service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(
        componentKey=allowed[0]["key"], label="TEST component", sortOrder=0), actor_id=actor)
    return t, comp


def _field(db, comp, actor, label="TEST field"):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateFieldUpsert

    kind, cols = next(iter(service._REPORT_FIELD_ALLOWED_COLUMNS.items()))
    return service.upsert_report_field(db, comp.id, ReportTemplateFieldUpsert(
        fieldKey="test_field", label=label, fieldType="text", dataSourceKind=kind, sourceColumn=next(iter(cols)),
        sortOrder=0), actor_id=actor)


def test_hk_component_and_field_edits_record_the_maker_and_are_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    A, B, C = 101, 202, 303
    t, comp = _draft_template(db, actor=A)
    f = _field(db, comp, B)
    db.refresh(t)
    assert t.updated_by_id == B
    _field(db, comp, B, label="TEST field renamed")
    history = service.get_report_template_audit(db, t.id)
    upd = next(a for a in history if a.entity_type == "report_template_field" and a.action == "update")
    assert upd.actor_id == B and upd.old_value["label"] == "TEST field" and upd.new_value["label"] == "TEST field renamed"
    assert {a.entity_type for a in history} >= {"report_template", "report_template_component", "report_template_field"}
    assert service.report_template_editors(db, t) == {A, B}
    for editor in (A, B):             # A made the metadata + component; B the fields
        with pytest.raises(BadRequestException, match="maker-checker"):
            service.set_report_template_approver(db, t.id, actor_id=editor)
    assert service.set_report_template_approver(db, t.id, actor_id=C).approved_by_id == C
    service.delete_report_field(db, f.id, actor_id=B)              # an edit after approval clears it
    db.refresh(t)
    assert t.approved_by_id is None and t.status == "Draft" and t.updated_by_id == B
    assert any(a.action == "delete" and a.entity_type == "report_template_field"
               for a in service.get_report_template_audit(db, t.id))


def test_a_promoted_template_still_refuses_component_and_field_edits(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import TaxConfigurationAudit

    t, comp = _draft_template(db, actor=101)
    t.status = "Published"
    db.commit()
    before = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_id == t.id,
                                                    TaxConfigurationAudit.entity_type == "report_template_field").count()
    with pytest.raises(BadRequestException):
        _field(db, comp, 202)
    db.rollback()
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_id == t.id,
                                                  TaxConfigurationAudit.entity_type == "report_template_field").count() == before


def test_other_countries_now_record_the_structural_editor_so_publish_maker_checker_applies(db):
    """Shared fix: a US field editor who approves can no longer Publish their own
    edit (the Publish check compares the approver with updated_by_id, which a
    field edit previously never set). The any-editor approval refusal stays
    HK-only (_ANY_EDITOR_APPROVAL_REFUSED_COUNTRIES)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    X, Y = 101, 202
    t, comp = _draft_template(db, country="US", report_type="W2", key="US-TEST-REMEDIATION", actor=Y, year="2026")
    _field(db, comp, X)
    db.refresh(t)
    assert t.updated_by_id == X
    assert service.set_report_template_approver(db, t.id, actor_id=X).approved_by_id == X     # US: not refused here
    with pytest.raises(BadRequestException):
        service.set_report_template_status(db, t.id, "Published", actor_id=Y)


# ── Gap 4: supersession across template versions ─────────────────────────

def _decoy(db, org_id, template, scope_key, *, report_type, year, period="ANNUAL"):
    from app.modules.payroll.models import GeneratedReport

    r = GeneratedReport(organization_id=org_id, report_template_id=template.id, template_version=template.version,
                        report_type=report_type, scope_key=scope_key, jurisdiction_country="HK",
                        reporting_year=year, reporting_period=period, status="Generated", rendered_data={"TEST": True})
    db.add(r)
    db.commit()
    return r


def test_regenerating_with_a_new_template_version_supersedes_the_old_versions_report(db, hk):
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import ReportTemplate
    from tests.test_hong_kong_e2e import _month, _other_org
    from tests.test_hong_kong_reports import _seeded

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", None)
    v1 = _seeded(db, "HK-IR56B")
    t_e, t_f, t_g = (_seeded(db, k) for k in ("HK-IR56E", "HK-IR56F", "HK-IR56G"))   # distinct decoy template ids
    scope = f"EMPLOYEE:{hk.emp.id}:2025/26"
    other_org = _other_org(db, "HKREM4")
    decoys = [
        _decoy(db, other_org.id, v1, scope, report_type="HK_IR56B", year="2025/26"),                  # other org
        _decoy(db, hk.org.id, t_e, scope, report_type="HK_IR56B", year="2026/27"),                     # other year
        _decoy(db, hk.org.id, t_f, scope, report_type="HK_IR56B", year="2025/26", period="Q1-TEST"),   # other period
        _decoy(db, hk.org.id, t_g, scope, report_type="HK_MPF_CONTRIBUTION_RECORD", year="2025/26"),   # other type
    ]
    first = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, v1.id, hk.emp.id, "2025/26")
    snapshot = dict(first.rendered_data["templateSnapshot"])
    v2 = ReportTemplate(template_key="HK-IR56B", name=v1.name, report_type="HK_IR56B", jurisdiction_country="HK",
                        reporting_year="2025/26", version="1.1", status="Active", document_scope="PER_EMPLOYEE")
    db.add(v2)
    db.commit()
    second = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, v2.id, hk.emp.id, "2025/26")
    db.refresh(first)
    assert first.status == "Superseded" and second.status == "Generated"
    assert (first.template_version, first.report_template_id) == ("1.0", v1.id)          # lineage kept
    assert first.rendered_data["templateSnapshot"] == snapshot                             # immutable output
    assert second.template_version == "1.1" and second.rendered_data["supersedesReportIds"] == [first.id]
    assert second.rendered_data.get("configurationLineage") == first.rendered_data.get("configurationLineage")
    for d in decoys:
        db.refresh(d)
        assert d.status == "Generated", (d.organization_id, d.reporting_year, d.reporting_period, d.report_type)
    third = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, v2.id, hk.emp.id, "2025/26")   # same version again
    db.refresh(second)
    assert second.status == "Superseded" and third.rendered_data["supersedesReportIds"] == [second.id]
    live = [r for r in (first, second, third) if r.status == "Generated"]
    assert live == [third]


# ── Gap 7: HK report generators honour the read-only workspace ───────────

_HK_GENERATORS = ("bir56a", "ir56b", "ir56-notification", "empf-remittance", "mpf-contribution-record",
                  "termination-statement")


def _trial(monkeypatch, stage):
    """Make the caller's org a trial in `stage`, through the real per-request
    guard (entitlements.get_active_subscription is looked up on each request;
    the stage maths is the real resolve_trial_stage)."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.modules.billing import entitlements
    from app.modules.billing.models import SubscriptionStatus

    now = datetime.utcnow()
    end, grace = {"ACTIVE": (now + timedelta(days=10), None),
                  "GRACE_READONLY": (now - timedelta(days=1), now + timedelta(days=6)),
                  "CLOSED": (now - timedelta(days=15), now - timedelta(days=2))}[stage]
    sub = SimpleNamespace(status=SubscriptionStatus.TRIALING.value, current_period_end=end, grace_period_ends_at=grace)
    monkeypatch.setattr(entitlements, "get_active_subscription", lambda db, organization_id: sub)


def _operator(org_id):
    from types import SimpleNamespace

    return SimpleNamespace(id=101, organization_id=org_id, role="payroll_admin", is_active=True)


@pytest.mark.parametrize("stage", ["GRACE_READONLY", "CLOSED"])
@pytest.mark.parametrize("path", _HK_GENERATORS)
def test_hk_generators_refuse_a_read_only_workspace(db, hk, monkeypatch, path, stage):
    from app.modules.payroll.models import GeneratedReport
    from tests.test_hong_kong_governance import _http

    _trial(monkeypatch, stage)
    with _http(db, _operator(hk.org.id)) as client:
        r = client.post(f"/api/payroll/hong-kong/reports/{path}", json={})
    assert r.status_code == 403 and "read-only" in r.text
    assert db.query(GeneratedReport).count() == 0


def test_hk_generator_in_a_writeable_workspace_still_generates_for_the_callers_org(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service
    from tests.test_hong_kong_e2e import _month
    from tests.test_hong_kong_governance import _http
    from tests.test_hong_kong_reports import _seeded

    _trial(monkeypatch, "ACTIVE")
    for m in (1, 2, 3):
        _month(db, hk.org, m)
    hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", None)
    tmpl = _seeded(db, "HK-BIR56A")
    with _http(db, _operator(hk.org.id)) as client:
        r = client.post("/api/payroll/hong-kong/reports/bir56a",
                        json={"report_template_id": tmpl.id, "year_of_assessment": "2025/26"})
    assert r.status_code == 200, r.text
    with _http(db, None) as client:                                                       # no credentials
        assert client.post("/api/payroll/hong-kong/reports/bir56a", json={}).status_code in (401, 403)


# ── Gap 5: IRD amendment lifecycle (internal case states) ────────────────

def test_ird_amendment_required_until_the_replacement_is_filed_and_a_cancelled_replacement_restores_the_original(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase
    from tests.test_hong_kong_e2e import INTERNAL_FILING, _month

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    ar = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    case = db.get(HongKongIrdReportingCase, ar["employees"][0]["caseId"])
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-ORIG",
                                   submission=INTERNAL_FILING)                                    # 1 original filed
    filed_hash = case.payload_hash

    first = hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST late bonus", MAKER.id)     # 2 replacement draft
    db.refresh(case)
    assert case.status == "FILED" and hong_kong_service.xml_lifecycle_state(db, case) == "AMENDMENT_REQUIRED"   # 3
    assert hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST again", MAKER.id).id == first.id      # 8 idempotent
    assert db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.amends_case_id == case.id).count() == 1

    hong_kong_service.transition_ird_case(db, hk.org.id, first.id, "CANCELLED", MAKER.id)              # 4 cancelled
    db.refresh(case)
    assert case.status == "FILED" and hong_kong_service.xml_lifecycle_state(db, case) == "SUBMITTED_EXTERNALLY"  # 5 recoverable

    second = hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST late bonus (redo)", MAKER.id)
    assert second.id != first.id and second.amends_case_id == case.id
    hong_kong_service.transition_ird_case(db, hk.org.id, second.id, "VALIDATED", MAKER.id)
    with pytest.raises(BadRequestException, match="four-eyes"):
        hong_kong_service.transition_ird_case(db, hk.org.id, second.id, "FILED", MAKER.id, filing_reference="IRD-REPL",
                                       submission=INTERNAL_FILING)
    db.rollback()
    db.refresh(case)
    assert case.status == "FILED"                                  # a refused filing never supersedes the original
    hong_kong_service.transition_ird_case(db, hk.org.id, second.id, "FILED", CHECKER.id, filing_reference="IRD-REPL",
                                   submission=INTERNAL_FILING)                                  # 6 replacement filed
    db.refresh(case)
    db.refresh(second)
    assert case.status == "AMENDED" and hong_kong_service.xml_lifecycle_state(db, case) == "SUPERSEDED"         # 7 lineage
    assert case.payload_hash == filed_hash and case.filing_reference == "IRD-ORIG"           # filed evidence kept
    assert second.status == "FILED" and hong_kong_service.xml_lifecycle_state(db, second) == "SUBMITTED_EXTERNALLY"
    hist = hong_kong_service.ird_case_history(db, hk.org.id, case.id)
    assert hist[-1]["to"] == "AMENDED" and "replaced by case" in (hist[-1]["reason"] or "")
    with pytest.raises(BadRequestException, match="only a filed"):
        hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST", MAKER.id)                   # superseded: not amendable
    again = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    row = [e for e in again["employees"] if e["employeeId"] == hk.emp.id][0]
    assert row["caseId"] == second.id and row["status"] == "FILED"                            # 8 never regenerated


# ── Gap 6: the database refuses duplicate tenant workflow rows ───────────

def test_workflow_uniqueness_indexes_refuse_duplicates_in_the_database(db, hk):
    from datetime import date

    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll.models import HongKongEmpfSubmission, HongKongIrdReportingCase, HongKongTaxClearanceHold

    org, emp = hk.org.id, hk.emp.id

    def hold():
        return HongKongTaxClearanceHold(organization_id=org, employee_id=emp, state="IDENTIFIED",
                                   expected_departure_date=date(2026, 12, 31), identified_on=date(2026, 10, 5),
                                   filing_deadline=date(2026, 11, 30))

    def case(**kw):
        return HongKongIrdReportingCase(organization_id=org, year_of_assessment="2025/26", **kw)

    def batch():
        return HongKongEmpfSubmission(organization_id=org, contribution_period="2026-07", status="PREPARED", rows=[],
                                 totals={}, payload_hash="TEST")

    pairs = [
        (hold, hold),
        (lambda: case(employee_id=emp, form_type="IR56E", event_date=date(2026, 1, 16), status="DUE"),) * 2,
        (lambda: case(employee_id=emp, form_type="IR56B", status="PREPARED"),) * 2,
        (lambda: case(form_type="BIR56A", status="PREPARED"),) * 2,
        (batch, batch),
    ]
    for first, second in pairs:
        db.add(first())
        db.commit()
        db.add(second())
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    filed = case(employee_id=emp, form_type="IR56F", status="FILED")
    db.add(filed)
    db.commit()
    db.add(case(employee_id=emp, form_type="IR56F", status="PREPARED", amends_case_id=filed.id))
    db.commit()
    db.add(case(employee_id=emp, form_type="IR56F", status="PREPARED", amends_case_id=filed.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # closed / withdrawn rows never block a new one
    h = db.query(HongKongTaxClearanceHold).filter(HongKongTaxClearanceHold.employee_id == emp).one()
    h.state = "CASE_CLOSED"
    db.commit()
    db.add(hold())
    db.commit()


# ── Lesser A: overlapping Active HK packs fail closed ────────────────────

def test_two_overlapping_active_hk_packs_block_payroll_and_the_explanation(db, hk):
    from datetime import date

    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    on = date(2026, 5, 31)
    assert hong_kong_service.explain_resolution(db, on)["outcome"] == "SELECTED"
    twin = hong_kong_service.new_version(db, hk.packs[1].id, "1.1", "TEST overlap", 101)
    twin.status = "Active"                           # TEST-ONLY corruption: activation itself refuses the overlap
    db.commit()
    with pytest.raises(MissingComplianceConfigurationError, match="2 Active packs overlap"):
        service._resolve_effective_rate_inputs(db, hk.org.id, "HK", on, org_opted_in=True)
    out = hong_kong_service.explain_resolution(db, on)
    assert out["outcome"].startswith("BLOCKED") and "overlap" in out["blockReason"] and out["pack"] is None
    assert hong_kong_service.explain_resolution(db, date(2025, 6, 30))["outcome"] == "SELECTED"   # other year unaffected


# ── Lesser B: the explanation uses the payroll decision path ─────────────

def test_explanation_reports_the_block_payroll_would_raise(db, hk):
    from datetime import date

    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.models import ContributionRate

    on = date(2026, 5, 31)
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == hk.packs[1].id,
                                      ContributionRate.component_key == "mpf_employer_rate").delete()
    db.commit()
    with pytest.raises(MissingComplianceConfigurationError) as payroll_block:
        service._resolve_effective_rate_inputs(db, hk.org.id, "HK", on, org_opted_in=True)
    out = hong_kong_service.explain_resolution(db, on)
    assert out["outcome"].startswith("BLOCKED") and out["blockReason"] == str(payroll_block.value)


# ── Lesser C: one-off tax reduction ─────────────────────────────────────

def test_one_off_tax_reduction_is_explicit_and_a_half_configured_one_fails_closed(db, hk):
    from datetime import date
    from decimal import Decimal

    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    def run(on, ya, drop=None):
        rate_map, slabs, _pack = hong_kong_service.pack_inputs(db, on)
        rate_map = {k: v for k, v in rate_map.items() if k != drop}
        return salaries_tax.estimate(year_of_assessment=ya, rate_map=rate_map, slabs=slabs, income=Decimal("600000"),
                                     allowances={"basic": 1})

    y25 = run(date(2025, 6, 30), "2025/26")
    assert y25["taxReductionBasis"].startswith("PACK_ROWS") and Decimal(y25["taxReduction"]) > 0
    y26 = run(date(2026, 6, 30), "2026/27")
    assert y26["taxReduction"] == "0.00" and y26["taxReductionBasis"].startswith("NONE CONFIGURED")
    with pytest.raises(HongKongCalculationBlockedError, match="half-configured"):
        run(date(2025, 6, 30), "2025/26", drop="hk_tax_reduction_cap")


# ── Lesser D: eMPF member identifiers ───────────────────────────────────

def test_empf_rows_carry_the_recorded_member_identifiers_masked_and_marked_internal(db, hk):
    from app.modules.payroll import hong_kong_service, service
    from tests.test_hong_kong_e2e import _month
    from tests.test_hong_kong_reports import _seeded

    _month(db, hk.org, 4)
    sub = hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    row = sub.rows[0]
    assert row["memberAccount"] and row["memberAccount"] != "MB-HK1" and "MB-HK1" not in str(sub.rows)
    assert "mpfSchemeRef" in row
    report = hong_kong_service.generate_hong_kong_empf_remittance(db, hk.org.id, _seeded(db, "HK-EMPF-REMITTANCE").id, sub.id)
    member = report.rendered_data["employees"][0]
    assert member["memberAccount"] == row["memberAccount"] and "not archived" in member["memberIdentifierStatus"]


# ── Lesser E: regeneration keeps the pinned pack's period rows ───────────

def test_regenerating_a_payslip_uses_the_pinned_pack_not_the_currently_resolved_one(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import PayrollStatus
    from tests.test_hong_kong_e2e import _item, _month

    run = _month(db, hk.org, 5, status=PayrollStatus.DRAFT)
    item = _item(db, run, hk.emp)
    pinned = item.tax_policy_pack_id
    assert pinned == hk.packs[1].id
    newer = hong_kong_service.new_version(db, hk.packs[1].id, "1.1", "TEST newer version", 101)
    db.get(type(newer), pinned).status = "Superseded"           # TEST-ONLY: the newer version is now in force
    newer.status = "Active"
    db.commit()
    seen = []
    real = hong_kong_service.calc_inputs

    def spy(db_, run_, employee, resolved_pack):
        seen.append(resolved_pack[2].id if resolved_pack else None)
        return real(db_, run_, employee, resolved_pack)

    monkeypatch.setattr(hong_kong_service, "calc_inputs", spy)
    service.regenerate_employee_payslip(db, run.id, hk.emp.id, hk.org.id, actor_id=MAKER.id)
    assert seen and seen[-1] == pinned != newer.id


# ── Future statutory data (YA 2027/28) is visible, never fabricated ──────

def test_a_missing_next_year_pack_is_signalled_ahead_and_payroll_for_it_is_refused(db, hk):
    from datetime import date

    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import JurisdictionPack

    def signal(on):
        return next(s for s in hong_kong_service.monitoring_signals(db, on)["signals"] if s["key"] == "NEXT_YEAR_PACK_NOT_ACTIVE")

    assert signal(date(2026, 6, 1))["value"] == 0                  # 2027-04-01 is > 90 days away
    late = signal(date(2027, 1, 15))
    assert late["value"] == 1 and late["alert"] is True and "2027-04-01" in late["label"]
    assert signal(date(2026, 1, 15))["value"] == 0                 # 2026/27 IS covered by an Active pack
    out = hong_kong_service.explain_resolution(db, date(2027, 4, 1))
    assert out["outcome"].startswith("BLOCKED") and out["pack"] is None
    assert db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "HK",
                                             JurisdictionPack.tax_year == "2027/28").count() == 0   # nothing invented

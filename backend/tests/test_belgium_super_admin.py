"""Belgium (ZP-BE-ENG-001) Phase 3A: Draft seed, governed signing console,
four-eyes, activation refusal, the BE-guarded shared branches (Joint Committee
agreement codes, pack assignment) and end-to-end safety.

SYNTHETIC data, in-memory SQLite. Every number written by a test is synthetic,
never Belgian statutory content."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

EDITOR, SIGNER, APPROVER, ACTIVATOR = 501, 502, 503, 504


def _c():
    from app.modules.payroll.engine.countries import belgium_content

    return belgium_content


@pytest.fixture
def seeded(db):
    from scripts.seed_belgium_canonical_packs import seed_belgium

    out = seed_belgium(db)
    db.commit()
    return out["pack"]


def _rate(db, pack, key):
    from app.modules.payroll.models import ContributionRate

    return (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.component_key == key).one())


def _verified_source(db, uploader=900, reviewer=901):
    from app.modules.payroll.models import SourceArtifact

    src = SourceArtifact(agency="Synthetic authority", title="Synthetic archived source", form_number="SYN-1",
                         checksum_sha256="a" * 64, file_path="synthetic/source.pdf", created_by_id=uploader,
                         reviewer_id=reviewer)
    db.add(src)
    db.commit()
    return src


def _update(db, kind, row_id, actor, **data):
    from app.modules.payroll import be_super_admin

    out = be_super_admin.update_row(db, kind, row_id, data, actor)
    db.commit()
    return out


# ── seed ───────────────────────────────────────────────────────────────────
def test_seed_writes_every_key_pending_with_no_value_in_any_value_field(db, seeded):
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab

    c = _c()
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == seeded.id).all()
    assert sorted(r.component_key for r in rates) == sorted(c.KEYS)
    for r in rates:
        assert (r.employee_rate_pct, r.employer_rate_pct, r.flat_amount, r.text_value) == (None, None, None, None)
        assert c.PENDING_MARK in r.label and r.organization_id is None and r.jurisdiction_country == "BE"
        if r.component_key in c.SPEC_PROPOSED:
            assert f"spec-proposed: {c.SPEC_PROPOSED[r.component_key]}"[:60] in r.label
    classes = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == seeded.id,
                                       TaxSlab.rule_type == c.EARNING_CLASS_RULE).all()
    assert len(classes) == len(c.OBLIGATIONS) * len(c.COMPONENTS)
    assert {s.assessment_basis for s in classes} == {"REVIEW"}
    assert all(c.PENDING_MARK in s.rate_label for s in classes)
    sources = db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-BE-ENG-001 S%")).all()
    assert len(sources) == 24 and all(s.checksum_sha256 is None and s.file_path is None for s in sources)
    assert seeded.status == "Draft" and seeded.pack_id == "BE-PAYROLL-2026"


def test_seed_is_idempotent_creates_no_joint_committee_packs_and_keeps_the_registry_planned(db, seeded):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.models import CollectiveAgreement, ContributionRate, SourceArtifact, TaxSlab
    from scripts.seed_belgium_canonical_packs import seed_belgium

    def counts():
        return (db.query(ContributionRate).count(), db.query(TaxSlab).count(), db.query(SourceArtifact).count())

    before = counts()
    seed_belgium(db)
    db.commit()
    assert counts() == before
    assert db.query(CollectiveAgreement).filter(CollectiveAgreement.jurisdiction_country == "BE").count() == 0
    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BE").one()
    assert row.availability == "PLANNED"


def test_seed_never_overwrites_a_console_edit_and_refuses_a_non_draft_pack(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service

    row = _rate(db, seeded, "be_bssc_pending")
    row.text_value = "NOT_SUPPORTED"
    db.commit()
    belgium_service.seed_belgium_pack(db)
    db.commit()
    assert _rate(db, seeded, "be_bssc_pending").text_value == "NOT_SUPPORTED"
    seeded.status = "Approved"
    db.commit()
    with pytest.raises(BadRequestException, match="not Draft"):
        belgium_service.seed_belgium_pack(db)


def test_seed_draft_action_needs_a_reason_and_runs_only_once(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import be_super_admin

    with pytest.raises(BadRequestException, match="reason"):
        be_super_admin.seed_draft(db, {}, EDITOR)
    out = be_super_admin.seed_draft(db, {"reason": "Phase 3A seed"}, EDITOR)
    db.commit()
    assert out["availability"] == "PLANNED" and out["pack"][0]["status"] == "Draft"
    with pytest.raises(BadRequestException, match="already seeded"):
        be_super_admin.seed_draft(db, {"reason": "again"}, EDITOR)


# ── governed row update and signing ────────────────────────────────────────
def test_text_rows_use_the_key_vocabulary(db, seeded):
    from app.core.exceptions import BadRequestException

    src = _verified_source(db)
    row = _rate(db, seeded, "be_rounding_onss")
    with pytest.raises(BadRequestException, match="must be one of"):
        _update(db, "rate", row.id, EDITOR, textValue="BANKERS", reason="r", sourceDocumentId=src.id)
    _update(db, "rate", row.id, EDITOR, textValue="cent_half_up", reason="r", sourceDocumentId=src.id)
    assert _rate(db, seeded, "be_rounding_onss").text_value == "CENT_HALF_UP"
    freq = _rate(db, seeded, "be_supported_pay_frequencies")
    with pytest.raises(BadRequestException, match="unknown value"):
        _update(db, "rate", freq.id, EDITOR, textValue="MONTHLY,HOURLY", reason="r", sourceDocumentId=src.id)
    nov = _rate(db, seeded, "be_ot_threshold_rule")                 # no vocabulary yet
    with pytest.raises(BadRequestException, match="no signed vocabulary"):
        _update(db, "rate", nov.id, EDITOR, textValue="WEEKLY_38", reason="r", sourceDocumentId=src.id)
    _update(db, "rate", nov.id, EDITOR, textValue="NOT_SUPPORTED", reason="r", sourceDocumentId=src.id)


def test_value_slots_follow_the_key_kind(db, seeded):
    from app.core.exceptions import BadRequestException

    src = _verified_source(db)
    amount = _rate(db, seeded, "be_wage_rmmmg")
    with pytest.raises(BadRequestException, match="holds a amount value"):
        _update(db, "rate", amount.id, EDITOR, employeeRatePct="5", reason="r", sourceDocumentId=src.id)
    with pytest.raises(BadRequestException, match="holds a amount value, not text_value"):
        _update(db, "rate", amount.id, EDITOR, textValue="SOMETHING", reason="r", sourceDocumentId=src.id)
    _update(db, "rate", amount.id, EDITOR, textValue="NOT_SUPPORTED", reason="r", sourceDocumentId=src.id)
    band = _rate(db, seeded, "be_wht_annex3_regular_scale")
    with pytest.raises(BadRequestException, match="SLAB_ROWS"):
        _update(db, "rate", band.id, EDITOR, textValue="BANDS", reason="r", sourceDocumentId=src.id)
    dated = _rate(db, seeded, "be_onss_rate_file_quarter")
    with pytest.raises(BadRequestException, match="ISO date"):
        _update(db, "rate", dated.id, EDITOR, textValue="2026/3", reason="r", sourceDocumentId=src.id)
    with pytest.raises(BadRequestException, match="reason"):
        _update(db, "rate", amount.id, EDITOR, flatAmount="10", sourceDocumentId=src.id)
    with pytest.raises(BadRequestException, match="source document"):
        _update(db, "rate", amount.id, EDITOR, flatAmount="10", reason="r")
    with pytest.raises(BadRequestException, match="negative"):
        _update(db, "rate", amount.id, EDITOR, flatAmount="-1", reason="r", sourceDocumentId=src.id)


def test_signing_needs_a_reviewed_archived_source_and_a_value(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import SourceArtifact

    c = _c()
    row = _rate(db, seeded, "be_wage_rmmmg")
    seeded_source = db.query(SourceArtifact).filter(SourceArtifact.form_number == "ZP-BE-ENG-001 S8").one()
    with pytest.raises(BadRequestException, match="reviewed by a Super Admin"):
        _update(db, "rate", row.id, SIGNER, flatAmount="10", reason="r", sourceDocumentId=seeded_source.id,
                specialistVerified=True)                     # S1-S24 are not archived yet
    src = _verified_source(db)
    with pytest.raises(BadRequestException, match="has no value"):
        _update(db, "rate", row.id, SIGNER, reason="r", sourceDocumentId=src.id, specialistVerified=True)
    view = _update(db, "rate", row.id, SIGNER, flatAmount="10", reason="sign", sourceDocumentId=src.id,
                   specialistVerified=True)
    assert view["signed"] and c.PENDING_MARK not in _rate(db, seeded, "be_wage_rmmmg").label
    _update(db, "rate", row.id, EDITOR, flatAmount="11", reason="change", sourceDocumentId=src.id)
    assert c.PENDING_MARK in _rate(db, seeded, "be_wage_rmmmg").label          # re-marked pending


def test_onss_employer_rows_are_reference_only_in_every_view(db, seeded):
    from app.modules.payroll import be_super_admin

    c = _c()
    src = _verified_source(db)
    row = _rate(db, seeded, "be_onss_special_160")
    view = _update(db, "rate", row.id, EDITOR, employerRatePct="1", reason="r", sourceDocumentId=src.id)
    assert view["referenceOnly"] is True and view["referenceNote"] == c.REFERENCE_NOTE
    assert _rate(db, seeded, "be_onss_special_160").total == "REFERENCE ONLY"
    config = be_super_admin.configuration(db, seeded.id)
    for r in config["groups"]["onss_employer"]["rows"]:
        if c.is_reference_only(r["componentKey"]):
            assert r["referenceOnly"] and r["referenceNote"] == c.REFERENCE_NOTE
    assert not any(r["referenceOnly"] for r in config["groups"]["onss_employee"]["rows"])


def test_earning_class_treatment_only(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import TaxSlab

    src = _verified_source(db)
    cls = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == seeded.id,
                                   TaxSlab.rule_type == "BE_EARNING_CLASS").first()
    with pytest.raises(BadRequestException, match="not editable"):
        _update(db, "slab", cls.id, EDITOR, ratePct="5", reason="r", sourceDocumentId=src.id)
    with pytest.raises(BadRequestException, match="treatment"):
        _update(db, "slab", cls.id, EDITOR, treatment="MAYBE", reason="r", sourceDocumentId=src.id)
    view = _update(db, "slab", cls.id, SIGNER, treatment="INCLUDED", reason="r", sourceDocumentId=src.id,
                   specialistVerified=True)
    assert view["treatment"] == "INCLUDED" and view["signed"]


def test_signing_status_and_configuration(db, seeded):
    from app.modules.payroll import be_super_admin

    c = _c()
    status = be_super_admin.signing_status(db, seeded.id)
    assert sorted(status["pendingRates"]) == sorted(c.KEYS) == sorted(status["emptyValues"])
    assert status["reviewClasses"] == len(c.OBLIGATIONS) * len(c.COMPONENTS) and status["editors"] == []
    assert "cannot be activated" in status["activationRefusal"]
    config = be_super_admin.configuration(db, seeded.id)
    assert set(config["groups"]) == set(c.GROUPS)
    assert sum(len(g["rows"]) for g in config["groups"].values()) == len(c.KEYS)


# ── four-eyes ───────────────────────────────────────────────────────────────
def test_an_editor_or_signer_can_never_approve(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import jurisdiction_hooks, service

    src = _verified_source(db)
    _update(db, "rate", _rate(db, seeded, "be_bssc_pending").id, EDITOR, textValue="NOT_SUPPORTED",
            reason="r", sourceDocumentId=src.id)
    _update(db, "rate", _rate(db, seeded, "be_wage_rmmmg").id, SIGNER, flatAmount="10", reason="r",
            sourceDocumentId=src.id, specialistVerified=True)
    assert jurisdiction_hooks.call("BE", "statutory_editors", db, seeded) == {EDITOR, SIGNER}
    for actor in (EDITOR, SIGNER):
        with pytest.raises(BadRequestException):
            service.set_jurisdiction_pack_approver(db, seeded.id, actor_id=actor)
        db.rollback()
    db.refresh(seeded)
    assert seeded.approved_by_id is None


def test_the_same_person_cannot_sign_and_activate(db, seeded):
    from app.modules.payroll import belgium_service

    src = _verified_source(db)
    _update(db, "rate", _rate(db, seeded, "be_wage_rmmmg").id, SIGNER, flatAmount="10", reason="r",
            sourceDocumentId=src.id, specialistVerified=True)
    refusal = belgium_service.be_pack_activation_refusal(db, seeded, actor_id=SIGNER)
    assert "cannot also activate" in refusal
    assert "cannot also activate" not in belgium_service.be_pack_activation_refusal(db, seeded, actor_id=ACTIVATOR)


def test_activation_through_the_shared_path_is_refused_while_rows_are_pending(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException, match="cannot be activated"):
        service.set_jurisdiction_pack_status(db, seeded.id, "Active", actor_id=ACTIVATOR)
    db.rollback()
    db.refresh(seeded)
    assert seeded.status != "Active"


def _sign_everything(db, pack, source_id):
    """Simulate a fully decided pack: every key signed NOT_SUPPORTED with a
    source, every earning class signed (test setup — never statutory content)."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    c = _c()
    for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id):
        r.text_value, r.source_document_id = "NOT_SUPPORTED", source_id
        r.label = r.label.replace(c.PENDING_MARK, "").strip()
    for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        s.rate_label, s.assessment_basis = s.rate_label.replace(c.PENDING_MARK, "").strip(), "EXCLUDED"
    db.commit()


def test_activation_refusal_accepts_signed_not_supported_and_refuses_unsigned(db, seeded):
    from app.modules.payroll import belgium_service

    c = _c()
    src = _verified_source(db)
    _sign_everything(db, seeded, src.id)
    assert belgium_service.be_pack_activation_refusal(db, seeded, actor_id=ACTIVATOR) is None
    row = _rate(db, seeded, "be_wage_rmmmg")
    row.label = f"{row.label} {c.PENDING_MARK}"                     # one unsigned row
    db.commit()
    assert "be_wage_rmmmg (unsigned)" in belgium_service.be_pack_activation_refusal(db, seeded)
    row.label, row.source_document_id = row.label.replace(c.PENDING_MARK, "").strip(), None
    db.commit()
    assert "be_wage_rmmmg (unsourced)" in belgium_service.be_pack_activation_refusal(db, seeded)
    row.source_document_id, row.text_value = src.id, None             # signed but empty
    db.commit()
    assert "be_wage_rmmmg (empty)" in belgium_service.be_pack_activation_refusal(db, seeded)


def test_a_slab_rows_key_needs_signed_slab_rows(db, seeded):
    from app.modules.payroll import belgium_service

    src = _verified_source(db)
    _sign_everything(db, seeded, src.id)
    row = _rate(db, seeded, "be_public_holidays")
    row.text_value = "SLAB_ROWS"
    db.commit()
    assert "be_public_holidays (slab rows missing or unsigned)" in belgium_service.be_pack_activation_refusal(
        db, seeded)


# ── generic editor, assignment, Joint Committees ───────────────────────────
def test_the_generic_statutory_editor_is_refused_for_a_belgian_pack(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    with pytest.raises(BadRequestException, match="Compliance → Belgium"):
        service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
            jurisdictionPackId=seeded.id, jurisdictionCountry="BE", componentKey="be_wage_rmmmg",
            label="x"), actor_id=EDITOR)


def test_assignment_refuses_a_non_active_belgian_pack(db, seeded, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    for status in ("Draft", "Approved"):
        seeded.status = status
        db.commit()
        with pytest.raises(BadRequestException, match="only an Active Belgian pack"):
            service.assign_pack_to_organizations(db, seeded.id, [organization.id], actor_id=EDITOR)


def test_assignment_for_other_countries_is_unchanged(db, organization):
    """A Draft pack of another country is still assignable exactly as before."""
    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails, JurisdictionPack

    pack = JurisdictionPack(pack_id="IN-DRAFT-TEST", jurisdiction_country="IN", pack_type="tax", version="1.0",
                            status="Draft")
    db.add(pack)
    db.commit()
    out = service.assign_pack_to_organizations(db, pack.id, [organization.id], actor_id=EDITOR)
    assert out["updated"] == 1
    details = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization.id).one()
    assert details.active_pack_id == pack.id


def _agreement(code, **over):
    from app.modules.payroll.schemas import CollectiveAgreementUpsert

    fields = dict(jurisdictionCountry="BE", agreementCode=code, name="Synthetic Joint Committee",
                  agreementType="SECTOR", version="1.0", employeeGroup="synthetic group")
    fields.update(over)
    return CollectiveAgreementUpsert(**fields)


def test_belgian_agreement_codes_are_validated_and_employee_group_is_untouched(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException, match="BE-PC-<committee>"):
        service.upsert_collective_agreement(db, _agreement("PC200-2026"), actor_id=EDITOR)
    row = service.upsert_collective_agreement(db, _agreement("BE-PC-124-A-1.0"), actor_id=EDITOR)
    assert row.agreement_code == "BE-PC-124-A-1.0" and row.employee_group == "synthetic group"
    other = service.upsert_collective_agreement(db, _agreement("BE-PC-200-1.0", employeeGroup=None), actor_id=EDITOR)
    assert other.employee_group is None
    # Non-BE agreements are unchanged by the Belgian branch.
    se = service.upsert_collective_agreement(db, _agreement("SE-SECTOR-TEST-2026", jurisdictionCountry="SE"),
                                             actor_id=EDITOR)
    assert se.agreement_code == "SE-SECTOR-TEST-2026"


def test_belgian_agreement_approval_is_four_eyes(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    row = service.upsert_collective_agreement(db, _agreement("BE-PC-200-1.0"), actor_id=EDITOR)
    service.set_collective_agreement_status(db, row.id, "In Review", actor_id=EDITOR)
    with pytest.raises(BadRequestException, match="different Super Admin"):
        service.set_collective_agreement_status(db, row.id, "Approved", actor_id=EDITOR)


# ── owner decisions, summary, authority examples, routes ───────────────────
def test_owner_decisions_and_summary(db, seeded):
    from app.modules.payroll import belgium_service

    decisions = belgium_service.owner_decisions(db)
    assert {d["key"] for d in decisions} >= {"G-11", "G-16", "G-21"} and {d["state"] for d in decisions} == {"OPEN"}
    summary = belgium_service.statutory_summary(db)
    assert summary["status"] == "NOT_BUILT" and set(summary["gates"].values()) == {"NOT MET"}
    assert summary["packs"][0]["pendingRows"] == len(_c().KEYS)


def test_authority_examples_are_registered_only_with_a_reviewed_source(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import be_super_admin
    from app.modules.payroll.models import SourceArtifact

    unarchived = db.query(SourceArtifact).filter(SourceArtifact.form_number == "ZP-BE-ENG-001 S1").one()
    with pytest.raises(BadRequestException, match="reviewed by a Super Admin"):
        be_super_admin.add_authority_example(db, seeded.id, {"name": "EX1", "description": "case",
                                                             "sourceDocumentId": unarchived.id, "reason": "r"}, EDITOR)
    src = _verified_source(db)
    view = be_super_admin.add_authority_example(db, seeded.id, {"name": "EX1", "description": "synthetic case",
                                                                "sourceDocumentId": src.id, "reason": "r"}, EDITOR)
    db.commit()
    assert view["ruleType"] == "BE_AUTHORITY_EXAMPLE" and view["component"] == "EX1"
    with pytest.raises(BadRequestException, match="already has"):
        be_super_admin.add_authority_example(db, seeded.id, {"name": "EX1", "description": "again",
                                                             "sourceDocumentId": src.id, "reason": "r"}, EDITOR)


def test_belgium_console_routes_are_super_admin_only(db, seeded):
    from tests._mx_employer_helpers import SUPER_ADMIN, http, principal

    with http(db, SUPER_ADMIN) as c:
        assert c.get("/api/super-admin/compliance/belgium/packs").json()[0]["packId"] == "BE-PAYROLL-2026"
        assert c.get(f"/api/super-admin/compliance/belgium/packs/{seeded.id}/signing-status").status_code == 200
        assert c.get(f"/api/super-admin/compliance/belgium/packs/{seeded.id}/configuration").status_code == 200
        assert len(c.get("/api/super-admin/compliance/belgium/decisions").json()) == len(_c().OWNER_DECISIONS)
    with http(db, principal(1)) as c:
        assert c.get("/api/super-admin/compliance/belgium/packs").status_code == 403


# ── END-TO-END SAFETY ──────────────────────────────────────────────────────
def test_even_a_signed_active_assigned_pack_leaves_onboarding_refused_and_calculation_blocked(db, seeded,
                                                                                             organization):
    """Simulates the worst case: a fully signed Belgian pack that is ACTIVE and
    assigned. Onboarding still refuses (registry PLANNED, dormant) and the
    calculation still blocks (BE_ENGINE_NOT_BUILT)."""
    from app.modules.payroll import service
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.belgium import BECalculationBlockedError
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.engine.tax_resolver import (get_jurisdiction_change_block_reason,
                                                         get_jurisdiction_onboarding_block_reason)

    src = _verified_source(db)
    _sign_everything(db, seeded, src.id)
    seeded.status, seeded.approved_by_id = "Active", APPROVER
    db.commit()
    out = service.assign_pack_to_organizations(db, seeded.id, [organization.id], actor_id=ACTIVATOR)
    assert out["updated"] == 1
    assert get_jurisdiction_onboarding_block_reason(db, "Belgium")
    assert get_jurisdiction_change_block_reason(db, "India", "Belgium")
    for mode in ("standard", "enterprise"):
        with pytest.raises(BECalculationBlockedError, match="BE_ENGINE_NOT_BUILT"):
            calculate_payroll(PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country="BE"), mode)

"""New Zealand Super Admin signing console (ZP-NZ-ENG-001 Phase 7a, decision
Option 1; SQLite).

Super Admin-configured values drive the calculation only through governance:
a governed edit / sign (reason + source; signing needs a source reviewed by
another Super Admin), a distinct approver (editors refused), and activation,
which still refuses while anything is pending or empty. The end-to-end test
proves an activated, Super Admin-signed pack is what the engine computes with.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_super_admin as console
from app.modules.payroll import service
from app.modules.payroll.engine.countries import new_zealand as engine
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab
from tests._nz_engine_helpers import (
    build_pack, ctx, notice, sign_with_test_values, tax_profile,
)

MARK = "[PENDING G1]"


@pytest.fixture()
def admins(db):
    from app.modules.auth.models import User, UserRole

    def mk(email):
        user = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="S", last_name=email[:4],
                    is_active=True)
        db.add(user)
        db.commit()
        return user.id

    return mk("nz-sa-maker@zoikotest.example.com"), mk("nz-sa-checker@zoikotest.example.com"), \
        mk("nz-sa-third@zoikotest.example.com")


@pytest.fixture()
def pack(db):
    nzs.seed_nz_pack(db)
    db.commit()
    return db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == content.NZ_2026_27[0]).one()


@pytest.fixture()
def sources(db, admins):
    maker, checker, _third = admins

    def mk(title, reviewed=True):
        row = SourceArtifact(agency="Inland Revenue", title=title, retrieved_at=datetime(2026, 11, 1),
                             checksum_sha256="c" * 64, file_path=f"nz/{title}.pdf", created_by_id=maker,
                             reviewer_id=checker if reviewed else None)
        db.add(row)
        db.commit()
        return row.id

    return mk("TEST IRD source"), mk("TEST unreviewed source", reviewed=False)


def _rate(db, pack, key):
    return db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                             ContributionRate.component_key == key).one()


def _ask(source, **kw):
    return {"reason": "IRD specialist sign-off (TEST)", "sourceDocumentId": source, **kw}


# ── governed edit / sign ────────────────────────────────────────────────────
def test_edit_needs_reason_and_source(db, pack, sources, admins):
    row = _rate(db, pack, "nz_acc_earner_levy_rate")
    with pytest.raises(BadRequestException, match="reason"):
        console.update_row(db, "rate", row.id, {"sourceDocumentId": sources[0]}, admins[0])
    with pytest.raises(BadRequestException, match="source document"):
        console.update_row(db, "rate", row.id, {"reason": "x"}, admins[0])
    with pytest.raises(BadRequestException, match="not editable here"):
        console.update_row(db, "rate", row.id, _ask(sources[0], label="hack"), admins[0])


def test_signing_needs_a_source_reviewed_by_another_admin(db, pack, sources, admins):
    row = _rate(db, pack, "nz_acc_earner_levy_rate")
    with pytest.raises(BadRequestException, match="reviewed by a Super Admin"):
        console.update_row(db, "rate", row.id, _ask(sources[1], specialistVerified=True), admins[0])
    view = console.update_row(db, "rate", row.id, _ask(sources[0], specialistVerified=True), admins[0])
    assert view["signed"] is True and MARK not in row.label and row.flat_amount == Decimal("1.75")


def test_unverified_change_is_marked_pending_again(db, pack, sources, admins):
    row = _rate(db, pack, "nz_acc_earner_levy_rate")
    console.update_row(db, "rate", row.id, _ask(sources[0], specialistVerified=True), admins[0])
    view = console.update_row(db, "rate", row.id, _ask(sources[0], flatAmount="1.80"), admins[0])
    assert view["signed"] is False and row.label.endswith(MARK) and row.total == "1.80%"


def test_text_rows_use_the_engine_vocabulary(db, pack, sources, admins):
    rounding = _rate(db, pack, "nz_paye_rounding")
    with pytest.raises(BadRequestException, match="must be one of"):
        console.update_row(db, "rate", rounding.id, _ask(sources[0], textValue="round nicely"), admins[0])
    console.update_row(db, "rate", rounding.id, _ask(sources[0], textValue="nearest_cent_half_up"), admins[0])
    assert rounding.text_value == "NEAREST_CENT_HALF_UP"
    order = _rate(db, pack, "nz_deduction_precedence")
    with pytest.raises(BadRequestException, match="after PAYE"):
        console.update_row(db, "rate", order.id, _ask(
            sources[0], textValue="CHILD_SUPPORT,PAYE,ACC_LEVY,STUDENT_LOAN,KS_EMPLOYEE"), admins[0])
    with pytest.raises(BadRequestException, match="holds text"):
        console.update_row(db, "rate", rounding.id, _ask(sources[0], flatAmount="2"), admins[0])
    empty = _rate(db, pack, "nz_hol_awe_divisor_weeks")
    with pytest.raises(BadRequestException, match="fill it before signing"):
        console.update_row(db, "rate", empty.id, _ask(sources[0], specialistVerified=True), admins[0])


def test_earning_class_treatment_and_active_pack_refused(db, pack, sources, admins):
    slab = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == "NZ_EARNING_CLASS",
                                    TaxSlab.filing_status == "HOLIDAY_PAY", TaxSlab.tax_regime == "PAYE").one()
    with pytest.raises(BadRequestException, match="treatment"):
        console.update_row(db, "slab", slab.id, _ask(sources[0], treatment="MAYBE"), admins[0])
    console.update_row(db, "slab", slab.id, _ask(sources[0], treatment="included"), admins[0])
    assert slab.assessment_basis == "INCLUDED" and slab.rate_label.endswith(MARK)
    pack.status = "Active"
    db.commit()
    with pytest.raises(BadRequestException, match="no\\s+longer editable"):
        console.update_row(db, "slab", slab.id, _ask(sources[0], treatment="REVIEW"), admins[0])


# ── authority tables ────────────────────────────────────────────────────────
def test_authority_table_rows(db, pack, sources, admins):
    with pytest.raises(BadRequestException, match="authority tables"):
        console.add_table_row(db, pack.id, "NZ_PAYE_BAND", _ask(sources[0]), admins[0])
    with pytest.raises(BadRequestException, match="taxFormula must be"):
        console.add_table_row(db, pack.id, "NZ_PAYE_METHOD", _ask(
            sources[0], filingStatus="WEEKLY", flatAmount="52", taxFormula="GUESS"), admins[0])
    with pytest.raises(BadRequestException, match="region must be"):
        console.add_table_row(db, pack.id, "NZ_PUBLIC_HOLIDAY", _ask(
            sources[0], date="2027-01-25", name="TEST Wellington anniversary", region="XYZ"), admins[0])
    holiday = console.add_table_row(db, pack.id, "NZ_PUBLIC_HOLIDAY", _ask(
        sources[0], date="2027-01-25", name="TEST Wellington anniversary", region="NZ-WGN",
        specialistVerified=True), admins[0])
    assert (holiday["jurisdictionState"], holiday["effectiveFrom"], holiday["signed"]) == ("WGN", "2027-01-25", True)
    status = console.signing_status(db, pack.id)
    assert {t["ruleType"]: t["rows"] for t in status["authorityTables"]}["NZ_PUBLIC_HOLIDAY"] == 1
    console.delete_table_row(db, holiday["id"], {"reason": "entered on the wrong pack"}, admins[0])
    assert db.get(TaxSlab, holiday["id"]) is None


# ── maker-checker and the end-to-end proof ──────────────────────────────────
def _sign_everything(db, pack, source, actor):
    sign_with_test_values(db, pack, source, actor)


def test_editors_cannot_approve_and_activation_waits_for_everything(db, pack, sources, admins):
    maker, checker, third = admins
    row = _rate(db, pack, "nz_acc_earner_levy_rate")
    console.update_row(db, "rate", row.id, _ask(sources[0], specialistVerified=True), maker)
    db.commit()
    assert nzs._nz_statutory_editors(db, pack) == {maker}
    with pytest.raises(BadRequestException, match="maker-checker"):
        service.set_jurisdiction_pack_approver(db, pack.id, maker)
    assert "PENDING G1" in console.signing_status(db, pack.id)["activationRefusal"]
    service.set_jurisdiction_pack_approver(db, pack.id, checker)
    with pytest.raises(BadRequestException, match="PENDING G1"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=third)


def test_activated_super_admin_values_drive_the_calculation(db, pack, sources, admins):
    maker, checker, third = admins
    _sign_everything(db, pack, sources[0], maker)
    status = console.signing_status(db, pack.id)
    assert status["pendingRates"] == [] and status["pendingSlabsByRuleType"] == {}
    assert status["activationRefusal"] is None and status["editors"] == [maker]
    service.set_jurisdiction_pack_approver(db, pack.id, checker)
    service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=third)
    db.refresh(pack)
    assert pack.status == "Active"

    rate_map, slabs, resolved = nzs._nz_pack_in_force(db, date(2026, 4, 8))
    assert resolved.pack_id == content.NZ_2026_27[0]
    signed = engine.calculate(ctx(pack=(rate_map, slabs), nz_tax_profile=tax_profile(tax_code="M SL"),
                                  nz_authority_deductions=[notice()]))["nz_result"]
    fixture = engine.calculate(ctx(pack=build_pack(), nz_tax_profile=tax_profile(tax_code="M SL"),
                                   nz_authority_deductions=[notice()]))["nz_result"]
    assert signed["netPay"] == fixture["netPay"] == "1195.85"
    assert signed["obligations"] == fixture["obligations"]

    # the activated row is the Super Admin's signed value, and it is the one the engine used
    acc = _rate(db, pack, "nz_acc_earner_levy_rate")
    assert MARK not in acc.label and acc.source_document_id == sources[0]
    assert acc.flat_amount == Decimal("1.75") and signed["obligations"]["accLevy"] == "52.50"


def test_generic_canonical_editor_refuses_nz_rows(db, pack, admins):
    """NZ rows change only through the governed console: the generic
    canonical-row editor (no source, no signing) is refused."""
    rate = _rate(db, pack, "nz_acc_earner_levy_rate")
    slab = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).first()
    with pytest.raises(BadRequestException, match="New Zealand statutory rows"):
        service.delete_canonical_contribution_rate(db, rate.id, admins[0])
    with pytest.raises(BadRequestException, match="New Zealand statutory rows"):
        service.delete_canonical_tax_slab(db, slab.id, admins[0])
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    fields = CanonicalContributionRateUpsert.model_fields
    payload = {"jurisdictionPackId": pack.id, "jurisdictionCountry": "NZ", "componentKey": "nz_acc_earner_levy_rate",
               "label": "x", "flatAmount": "9", "id": rate.id}
    with pytest.raises(BadRequestException, match="New Zealand statutory rows"):
        service.upsert_canonical_contribution_rate(
            db, CanonicalContributionRateUpsert(**{k: v for k, v in payload.items() if k in fields}), admins[0])
    db.refresh(rate)
    assert rate.flat_amount == Decimal("1.75")

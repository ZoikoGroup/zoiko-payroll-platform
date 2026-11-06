"""Poland Super Admin signing console (ZP-PL-ENG-001 Phase 7a; spec §12 statutory
content console, gate G1): governed edit / sign with source + reason, engine
vocabulary, NOT_SUPPORTED for undefined policies, editors refused as approvers,
and end to end: a fully signed, activated DB pack reproduces the golden result."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from tests._pl_engine_helpers import TEST_AMOUNTS, TEST_TEXT


@pytest.fixture
def console(db):
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll import pl_super_admin as psa
    from app.modules.payroll.models import SourceArtifact

    users = []
    for i in range(3):
        u = User(email=f"sa{i}.pl@example.com", hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="S",
                 last_name=str(i), is_active=True, is_verified=True)
        db.add(u)
        users.append(u)
    db.flush()
    reviewed = SourceArtifact(agency="ZUS", title="2026 contribution indicators", checksum_sha256="a" * 64,
                              file_path="sources/zus-2026.pdf", created_by_id=users[1].id, reviewer_id=users[2].id)
    unreviewed = SourceArtifact(agency="ZUS", title="draft notes", created_by_id=users[1].id)
    db.add_all([reviewed, unreviewed])
    db.flush()
    out = psa.seed_draft(db, {"reason": "start Poland G1"}, users[0].id)
    db.commit()
    pack_id = out["pack"][0]["id"]
    return SimpleNamespace(db=db, psa=psa, editor=users[0].id, approver=users[1].id, source=reviewed.id,
                           draft_source=unreviewed.id, pack=pack_id)


def _rate(c, key):
    from app.modules.payroll.models import ContributionRate

    return c.db.query(ContributionRate).filter_by(jurisdiction_pack_id=c.pack, component_key=key,
                                                  organization_id=None).one()


def _edit(c, key, verify=True, source=None, **values):
    return c.psa.update_row(c.db, "rate", _rate(c, key).id,
                            {"reason": "G1 signature", "sourceDocumentId": source or c.source,
                             "specialistVerified": verify, **values}, c.editor)


def test_seed_draft_once_with_a_planned_registry_row(console):
    from app.modules.billing.models import JurisdictionServiceRegistry

    c = console
    assert c.db.query(JurisdictionServiceRegistry).filter_by(country="PL").one().availability == "PLANNED"
    with pytest.raises(BadRequestException, match="already seeded"):
        c.psa.seed_draft(c.db, {"reason": "again"}, c.editor)
    with pytest.raises(BadRequestException, match="reason"):
        c.psa.seed_draft(c.db, {}, c.editor)


def test_signing_needs_a_reviewed_source_and_marks_the_row(console):
    c = console
    assert _rate(c, "pl_rounding_pit").label.endswith("[PENDING G1]")
    with pytest.raises(BadRequestException, match="reviewed by a Super Admin"):
        _edit(c, "pl_rounding_pit", source=c.draft_source, textValue="FULL_PLN_HALF_UP")
    unsigned = _edit(c, "pl_rounding_pit", verify=False, source=c.draft_source, textValue="FULL_PLN_HALF_UP")
    assert unsigned["signed"] is False                                       # a value alone is not a signature
    signed = _edit(c, "pl_rounding_pit", textValue="FULL_PLN_HALF_UP")
    assert signed["signed"] is True and not _rate(c, "pl_rounding_pit").label.endswith("[PENDING G1]")
    changed = _edit(c, "pl_rounding_pit", verify=False, textValue="GROSZ_HALF_UP")
    assert changed["signed"] is False                                       # an unverified change re-marks it


@pytest.mark.parametrize("key, value, message", [
    ("pl_rounding_pit", "NEAREST", "must be one of"),
    ("pl_ppk_employer_pit_treatment", "MAYBE", "must be one of"),
    ("pl_overtime_premium_map", "DAILY=50", "every overtime event kind"),
    ("pl_sick_full_rate_cases", "FLU", "unknown value"),
    ("pl_night_supplement_basis", "MIN_WAGE_20PCT", "NOT_SUPPORTED"),
])
def test_text_must_be_engine_vocabulary(console, key, value, message):
    with pytest.raises(BadRequestException, match=message):
        _edit(console, key, textValue=value)


def test_undefined_policies_can_be_signed_not_supported_and_still_block(console):
    from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack
    from app.modules.payroll.engine.countries.poland import PLCalculationBlockedError

    c = console
    view = _edit(c, "pl_night_supplement_basis", textValue="not_supported")
    assert view["signed"] and view["textValue"] == "NOT_SUPPORTED"
    row = _rate(c, "pl_night_supplement_basis")
    pack = PlPack({"pl_night_supplement_basis": row}, [], 1, date(2026, 3, 31))
    from app.modules.payroll.engine.countries import poland_content as content

    with pytest.raises(PLCalculationBlockedError, match="not one of"):
        pack.text("pl_night_supplement_basis", content.NIGHT_SUPPLEMENT_RULES)


def test_values_go_into_the_slot_their_kind_names(console):
    c = console
    with pytest.raises(BadRequestException, match="holds a"):
        _edit(c, "pl_zus_annual_cap", textValue="282600")
    with pytest.raises(BadRequestException, match="holds a"):
        _edit(c, "pl_health", employerRatePct="9")                           # health is employee-funded
    with pytest.raises(BadRequestException, match="no value"):
        _edit(c, "pl_pit0_annual_limit")                                     # empty by design: fill first
    with pytest.raises(BadRequestException, match="still PENDING_G1"):
        _edit(c, "pl_health_limitation_rule")
    view = _edit(c, "pl_zus_emerytalne", employeeRatePct="9.76", employerRatePct="9.76")
    total = _rate(c, "pl_zus_emerytalne").total
    assert view["signed"] and total.count("9.76") == 2 and total.count("%") == 2


def test_earning_class_treatment_is_governed(console):
    from app.modules.payroll.models import TaxSlab

    c = console
    row = c.db.query(TaxSlab).filter_by(jurisdiction_pack_id=c.pack, rule_type="PL_EARNING_CLASS",
                                        tax_regime="PIT", filing_status="BONUS").one()
    view = c.psa.update_row(c.db, "slab", row.id, {"reason": "G1", "sourceDocumentId": c.source,
                                                   "specialistVerified": True, "treatment": "included"}, c.editor)
    assert view["treatment"] == "INCLUDED"
    with pytest.raises(BadRequestException, match="not editable"):
        c.psa.update_row(c.db, "slab", row.id, {"reason": "G1", "sourceDocumentId": c.source, "ratePct": "5"},
                         c.editor)


def test_editors_are_recorded_and_refused_as_approvers(console):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.models import JurisdictionPack

    c = console
    _edit(c, "pl_rounding_zus", textValue="GROSZ_HALF_UP")
    pack = c.db.get(JurisdictionPack, c.pack)
    assert jurisdiction_hooks.call("PL", "statutory_editors", c.db, pack) == {c.editor}
    status = c.psa.signing_status(c.db, c.pack)
    assert "pl_rounding_pit" in status["pendingRates"] and "pl_rounding_zus" not in status["pendingRates"]
    assert status["editors"] == [c.editor] and status["activationRefusal"]


def test_the_generic_editor_refuses_poland_rows():
    from app.modules.payroll import service

    with pytest.raises(BadRequestException, match="Compliance → Poland"):
        service._refuse_nz_generic_statutory_edit(SimpleNamespace(jurisdiction_country="PL"))


def _sign_everything(c):
    from app.modules.payroll.engine.countries import poland_content as content
    from app.modules.payroll.models import ContributionRate
    from tests._pl_engine_helpers import TEST_TEXT as TEXT

    for row in c.db.query(ContributionRate).filter_by(jurisdiction_pack_id=c.pack, organization_id=None).all():
        key, kind = row.component_key, content.POLAND_PARAMETER_KEYS[row.component_key]
        values = {}
        if key in TEXT:
            values["textValue"] = TEXT[key]
        elif key in TEST_AMOUNTS:
            values["flatAmount"] = TEST_AMOUNTS[key]
        elif key == "pl_overtime_premium_map":
            values["textValue"] = "DAILY=50,WEEKLY=100,NIGHT=100,SUNDAY_HOLIDAY=100,COMP_TIME_FAILED=50"
        elif key == "pl_leave_part_time_rounding":
            values["textValue"] = "ROUND_UP_FULL_DAY"
        elif kind == "text" and row.text_value == "PENDING_G1":
            values["textValue"] = "NOT_SUPPORTED"
        elif kind == "amount" and row.flat_amount is None:
            values["flatAmount"] = "1"                                       # TEST operational value
        _edit(c, key, **values)


def test_fully_signed_activated_pack_reproduces_the_golden_result(console):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll.models import JurisdictionPack
    from tests._pl_engine_helpers import ctx

    c = console
    _sign_everything(c)
    pack = c.db.get(JurisdictionPack, c.pack)
    assert pl.pl_pack_activation_refusal(c.db, pack) is None
    assert c.psa.signing_status(c.db, c.pack)["notSupported"]                 # undefined policies recorded
    pack.status = "Active"
    c.db.commit()
    rates, slabs, resolved = resolve_tax_configuration(c.db, "PL", payroll_date=date(2026, 3, 31))
    assert resolved.id == pack.id
    template = ctx()
    context = PayrollContext(**{**template.__dict__, "rate_map": {r.component_key: r for r in rates},
                                "slabs": list(slabs)})
    result = calculate_payroll(context, "standard")
    assert result.net_pay == Decimal("5608.91") and result.tds == Decimal("513.00")
    assert json.dumps(result.pl_result["hashes"])

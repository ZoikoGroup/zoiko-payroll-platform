"""Mexico final mile X8 — the Super Admin configuration re-audit's fixes:

1. a canonical row is checked against the pack it belongs to NOW, so a Mexico
   row is never moved out of its pack through another country's editable pack;
2. Mexico gate / decision evidence is governed: reviewed only with an uploaded
   document, and its file is never replaced after review (the gate would stay
   SIGNED on a file the reviewer never saw);
3. no editor of a Mexico report-template version may approve it;
4. a Super Admin who added CFDI catalog entries to a release may not approve it.

Other countries are unchanged (each is a Mexico entry in a per-country list or
a Mexico-only check). SYNTHETIC data only."""

from datetime import date
from decimal import Decimal

import pytest

from tests.test_mexico_router import SA_A


@pytest.fixture()
def mx_pack(db):
    from tests import _mx_run_helpers as rh

    return rh.national_pack(db)                                   # Active, synthetic rows


@pytest.fixture()
def other_draft(db):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="IN-X8-TEST", jurisdiction_country="IN", version="1.0", pack_type="tax",
                            status="Draft", effective_from=date(2026, 4, 1), effective_to=date(2027, 3, 31),
                            tax_year="2026", currency="INR")
    db.add(pack)
    db.commit()
    return pack


def test_a_mexico_row_cannot_be_moved_into_another_countrys_draft_pack(db, mx_pack, other_draft):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert, CanonicalTaxSlabUpsert

    rate = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == mx_pack.id).first()
    slab = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == mx_pack.id).first()
    before = (rate.employer_rate_pct, slab.rate_pct)
    refused = "Mexico statutory rows are not edited here"
    with pytest.raises(BadRequestException, match=refused):
        service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
            id=rate.id, jurisdictionPackId=other_draft.id, jurisdictionCountry="IN",
            componentKey=rate.component_key, label="moved", employerSharePct=Decimal("99")), actor_id=SA_A.id)
    with pytest.raises(BadRequestException, match=refused):
        service.upsert_canonical_tax_slab(db, CanonicalTaxSlabUpsert(
            id=slab.id, jurisdictionPackId=other_draft.id, jurisdictionCountry="IN", minAmount=Decimal("0"),
            ratePct=Decimal("99"), rateLabel="moved"), actor_id=SA_A.id)
    db.expire_all()
    rate, slab = db.get(ContributionRate, rate.id), db.get(TaxSlab, slab.id)
    assert (rate.jurisdiction_pack_id, slab.jurisdiction_pack_id) == (mx_pack.id, mx_pack.id)
    assert (rate.employer_rate_pct, slab.rate_pct) == before
    assert db.get(type(other_draft), other_draft.id).approved_by_id is None        # target pack untouched


def test_another_countrys_row_still_moves_within_its_own_editable_packs(db, other_draft):
    """Zero behaviour change elsewhere: the existing-pack check refuses Mexico only."""
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    row = service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
        jurisdictionPackId=other_draft.id, jurisdictionCountry="IN", componentKey="esi", label="ESI",
        employeeSharePct=Decimal("0.75")), actor_id=SA_A.id)
    again = service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
        id=row.id, jurisdictionPackId=other_draft.id, jurisdictionCountry="IN", componentKey="esi", label="ESI",
        employeeSharePct=Decimal("0.80")), actor_id=SA_A.id)
    assert again.employee_rate_pct == Decimal("0.80")


def _artifact(db, tag, created_by):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    return service.create_source_artifact(db, SourceArtifactCreate(
        agency="Zoiko release owner (SYNTHETIC)", title=f"SYNTHETIC {tag}", formNumber=tag, url=None), actor_id=created_by)


@pytest.mark.parametrize("tag", ["MX-GATE-G1", "MX-DECISION-Q9"])
def test_mexico_gate_evidence_is_reviewed_only_with_a_file_and_never_replaced_after(db, tag):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_service, service

    a = _artifact(db, tag, created_by=101)
    assert service.governed_evidence_country(a) == "MX"
    with pytest.raises(BadRequestException, match="no uploaded document"):
        service.mark_source_artifact_reviewed(db, a.id, reviewer_id=202)
    service.upload_source_artifact_file(db, a.id, "g1.pdf", "application/pdf", b"%PDF-1.4 SYNTHETIC v1", actor_id=101)
    service.mark_source_artifact_reviewed(db, a.id, reviewer_id=202)
    if tag == "MX-GATE-G1":
        assert next(g for g in mexico_service.gate_states(db) if g["gate"] == "G1")["state"] == "SIGNED"
    with pytest.raises(BadRequestException, match="cannot be replaced"):
        service.upload_source_artifact_file(db, a.id, "g1.pdf", "application/pdf", b"%PDF-1.4 SYNTHETIC v2",
                                            actor_id=101)


def test_an_ordinary_source_is_not_governed_evidence(db):
    from app.modules.payroll import service

    a = _artifact(db, "MX-SOURCE-S99", created_by=101)
    assert service.governed_evidence_country(a) is None


def test_no_editor_of_a_mexico_template_version_may_approve_it(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from tests.test_hong_kong_engineering_remediation import _draft_template, _field

    A, B, C = 101, 202, 303
    t, comp = _draft_template(db, country="MX", report_type="MX_REGISTER", key="MX-TEST-X8", actor=A, year="2026")
    _field(db, comp, B)
    with pytest.raises(BadRequestException, match="last edited"):                 # B: already refused (W2)
        service.set_report_template_approver(db, t.id, actor_id=B)
    with pytest.raises(BadRequestException, match="made none of its edits"):        # A: refused only since X8
        service.set_report_template_approver(db, t.id, actor_id=A)
    assert service.set_report_template_approver(db, t.id, actor_id=C).approved_by_id == C


def test_a_catalog_entry_author_cannot_approve_the_release(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_service as S

    A, B, C = 101, 202, 303
    rel = S.create_release(db, {"cfdi_version": "4.0", "complement_version": "1.2"}, A)
    S.add_catalog_entry(db, rel["id"], {"catalog_name": "c_SYNTHETIC", "code": "S1", "description": "SYNTHETIC"}, B)
    S.transition_release(db, rel["id"], "submit", A)
    with pytest.raises(BadRequestException, match="registered this release"):
        S.transition_release(db, rel["id"], "approve", A)
    with pytest.raises(BadRequestException, match="added catalog entries"):
        S.transition_release(db, rel["id"], "approve", B)
    assert S.transition_release(db, rel["id"], "approve", C)["status"] == "Approved"

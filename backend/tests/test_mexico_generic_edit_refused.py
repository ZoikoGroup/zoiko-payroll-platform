"""Completion W5-2: Mexico statutory rows are never edited through the generic
canonical-row editor (no source, no reason) — upsert and delete of a rate or a
slab are refused for an MX pack in every editable status, over HTTP too.
Other countries keep the generic editor. SYNTHETIC rows only."""

from datetime import date
from decimal import Decimal

import pytest

from tests.test_mexico_router import SA_A, _http


@pytest.fixture()
def mx_draft(db):
    from tests import _mx_run_helpers as rh

    pack = rh.national_pack(db)
    pack.status = "Draft"
    db.commit()
    return pack


def _rows(db, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).all()
    return rates, slabs


@pytest.mark.parametrize("status", ["Draft", "In Review", "QA", "Approved"])
def test_every_generic_write_is_refused_for_a_mexico_pack(db, mx_draft, status):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert, CanonicalTaxSlabUpsert

    mx_draft.status = status
    db.commit()
    rates, slabs = _rows(db, mx_draft)
    assert rates and slabs
    before = [(r.id, r.employee_rate_pct, r.employer_rate_pct, r.flat_amount) for r in rates]
    refused = "Mexico statutory rows are not edited here"
    with pytest.raises(BadRequestException, match=refused):
        service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
            id=rates[0].id, jurisdictionPackId=mx_draft.id, jurisdictionCountry="MX",
            componentKey=rates[0].component_key, label="x", employerSharePct=Decimal("99")), actor_id=SA_A.id)
    with pytest.raises(BadRequestException, match=refused):
        service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
            jurisdictionPackId=mx_draft.id, jurisdictionCountry="MX", componentKey="mx_new_row", label="x",
            flatAmount=Decimal("1")), actor_id=SA_A.id)
    with pytest.raises(BadRequestException, match=refused):
        service.upsert_canonical_tax_slab(db, CanonicalTaxSlabUpsert(
            id=slabs[0].id, jurisdictionPackId=mx_draft.id, jurisdictionCountry="MX", minAmount=Decimal("0"),
            ratePct=Decimal("99"), rateLabel="x"), actor_id=SA_A.id)
    with pytest.raises(BadRequestException, match=refused):
        service.delete_canonical_contribution_rate(db, rates[0].id, actor_id=SA_A.id)
    with pytest.raises(BadRequestException, match=refused):
        service.delete_canonical_tax_slab(db, slabs[0].id, actor_id=SA_A.id)
    db.expire_all()
    rates_after, slabs_after = _rows(db, mx_draft)
    assert [(r.id, r.employee_rate_pct, r.employer_rate_pct, r.flat_amount) for r in rates_after] == before
    assert len(slabs_after) == len(slabs)


def test_the_generic_routes_refuse_a_mexico_pack_over_http(db, mx_draft):
    rates, slabs = _rows(db, mx_draft)
    base = "/api/super-admin/compliance/tax-configuration"
    with _http(db, SA_A) as c:
        put = c.put(f"{base}/contribution-rates", json={
            "id": rates[0].id, "jurisdictionPackId": mx_draft.id, "jurisdictionCountry": "MX",
            "componentKey": rates[0].component_key, "label": "x", "employerSharePct": "99"})
        delete = c.delete(f"{base}/slabs/{slabs[0].id}")
    assert put.status_code == 400 and "Mexico statutory rows" in put.text
    assert delete.status_code == 400 and "Mexico statutory rows" in delete.text


def test_other_countries_keep_the_generic_editor(db):
    """Zero behaviour change: a Draft pack of another country is still edited
    through the generic editor."""
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    pack = JurisdictionPack(pack_id="IN-W5-2-TEST", jurisdiction_country="IN", version="1.0", pack_type="tax",
                            status="Draft", effective_from=date(2026, 4, 1), effective_to=date(2027, 3, 31),
                            tax_year="2026", currency="INR")
    db.add(pack)
    db.commit()
    row = service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
        jurisdictionPackId=pack.id, jurisdictionCountry="IN", componentKey="esi", label="ESI",
        employeeSharePct=Decimal("0.75")), actor_id=SA_A.id)
    service.delete_canonical_contribution_rate(db, row.id, actor_id=SA_A.id)

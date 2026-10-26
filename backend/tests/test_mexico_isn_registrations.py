"""Mexico Phase 3 — state ISN registrations (panel E, MX-045): in-scope
states only (CDMX), PENDING_PACK until the state pack is Active, the pack
resolved server-side, no typed return frequency."""

from datetime import date

import pytest

from tests._mx_employer_helpers import make_org, new_employer


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


@pytest.fixture()
def seeded(db):
    from scripts.seed_mexico_canonical_packs import load_manifest, seed_mexico

    out = seed_mexico(db, manifest=load_manifest())
    db.commit()
    return out


def _isn(db, org_id, emp_id, state="CDMX", **over):
    data = {"state_code": state, "local_account_number": "ISN-SYN-001", "effective_from": date(2026, 1, 1)}
    data.update(over)
    return _svc().create_isn_registration(db, org_id, emp_id, data, 701)


def test_cdmx_registers_as_pending_pack_while_the_pack_is_draft(db, seeded):
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    row = _isn(db, t.org.id, emp["id"])
    assert (row["state"], row["packId"], row["packStatus"]) == ("PENDING_PACK", "MX-ISN-CDMX-2026", "Draft")


def test_state_becomes_active_only_when_the_pack_is_active(db, seeded):
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    row = _isn(db, t.org.id, emp["id"])
    seeded["isn"]["CDMX"].status = "Active"          # test-only: activation gates are tested elsewhere
    db.commit()
    assert _svc().list_isn_registrations(db, t.org.id, emp["id"])[0]["state"] == "ACTIVE"
    assert row["id"]


def test_every_other_state_is_refused_and_audited(db, seeded):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.models import TaxConfigurationAudit

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    others = [code for code, _ in c.MX_FEDERAL_ENTITIES if code not in c.MX_ISN_STATES_IN_SCOPE]
    assert len(others) == 31
    for code in others:
        with pytest.raises(BadRequestException, match="MX-045"):
            _isn(db, t.org.id, emp["id"], state=code)
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.action == "refused").count() == 31


def test_return_frequency_cannot_be_typed_and_one_open_row_per_state(db, seeded):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    with pytest.raises(BadRequestException, match="returnFrequency comes from the state's filing content"):
        _isn(db, t.org.id, emp["id"], return_frequency="MONTHLY")
    first = _isn(db, t.org.id, emp["id"])
    with pytest.raises(BadRequestException, match="already has an open CDMX"):
        _isn(db, t.org.id, emp["id"])
    _svc().close_isn_registration(db, t.org.id, first["id"], date(2026, 6, 30), 701)
    assert _isn(db, t.org.id, emp["id"], effective_from=date(2026, 7, 1))["state"] == "PENDING_PACK"


def test_unseeded_pack_is_refused(db):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    with pytest.raises(BadRequestException, match="no ISN pack is seeded"):
        _isn(db, t.org.id, emp["id"])

"""Mexico Phase 3 — IMSS employer registrations (panel C), several per
employer (MX-002), INFONAVIT model (panel D), establishments and the
content-derived minimum-wage zone. SYNTHETIC identifiers."""

from datetime import date

import pytest

from tests._mx_employer_helpers import make_org, new_employer, new_registration


def _svc():
    from app.modules.payroll import mexico_employer_service

    return mexico_employer_service


def test_several_registrations_per_employer(db):
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    new_registration(db, t.org.id, emp["id"], rp="Y1234567101")
    new_registration(db, t.org.id, emp["id"], rp="Z7654321109", infonavit_operating_model="SIPARE")
    regs = _svc().list_registrations(db, t.org.id, emp["id"])
    assert [r["registroPatronal"] for r in regs] == ["Y1234567101", "Z7654321109"]
    assert regs[1]["infonavitOperatingModel"] == "SIPARE"


def test_overlapping_windows_for_one_registro_patronal_are_refused(db):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    reg = new_registration(db, t.org.id, emp["id"])
    with pytest.raises(BadRequestException, match="overlapping"):
        new_registration(db, t.org.id, emp["id"], eff="2026-06-01")
    _svc().close_registration(db, t.org.id, reg["id"], date(2026, 5, 31), 701)
    again = new_registration(db, t.org.id, emp["id"], eff="2026-06-01")
    assert again["status"] == "ACTIVE"


def test_risk_class_and_fraction_are_required_and_infonavit_model_is_enumerated(db):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    with pytest.raises(BadRequestException, match="riskClass and fraction"):
        new_registration(db, t.org.id, emp["id"], risk_class="")
    with pytest.raises(BadRequestException, match="SUA or SIPARE"):
        new_registration(db, t.org.id, emp["id"], infonavit_operating_model="OTHER")
    reg = new_registration(db, t.org.id, emp["id"])
    assert _svc().set_infonavit_model(db, t.org.id, reg["id"], "SUA", 701)["infonavitOperatingModel"] == "SUA"


def test_establishment_must_share_the_employer_of_its_registration(db):
    from app.core.exceptions import BadRequestException

    t = make_org(db)
    a = new_employer(db, t.org.id)
    b = new_employer(db, t.org.id, rfc="XYZ010101AB1")
    reg_b = new_registration(db, t.org.id, b["id"], rp="Z7654321109")
    with pytest.raises(BadRequestException, match="different legal employer"):
        _svc().create_establishment(db, t.org.id, a["id"], {"name": "Planta", "state_code": "CDMX",
                                                            "municipality": "Cuauhtémoc", "postal_code": "06600",
                                                            "imss_registration_id": reg_b["id"]}, 701)
    with pytest.raises(BadRequestException, match="federal-entity"):
        _svc().create_establishment(db, t.org.id, a["id"], {"name": "Planta", "state_code": "XX",
                                                            "municipality": "M", "postal_code": "06600"}, 701)


def test_min_wage_zone_is_unresolved_while_content_is_empty_and_derived_once_present(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    real = c.MX_ZLFN_MUNICIPALITIES
    monkeypatch.setattr(c, "MX_ZLFN_MUNICIPALITIES", ())             # empty content (Batch 2 transcribed S9)
    t = make_org(db)
    emp = new_employer(db, t.org.id)
    est = _svc().create_establishment(db, t.org.id, emp["id"], {"name": "Planta", "state_code": "BCN",
                                                                "municipality": "Tijuana", "postal_code": "22000"}, 701)
    assert est["minWageZone"]["zone"] == "UNRESOLVED"
    monkeypatch.setattr(c, "MX_ZLFN_MUNICIPALITIES", real)           # the transcribed S9 list
    assert _svc().min_wage_zone("BCN", "Tijuana")["zone"] == "ZLFN"
    assert "S9/" in _svc().min_wage_zone("BCN", "Tijuana")["detail"]
    assert _svc().min_wage_zone("JAL", "Guadalajara")["zone"] == "GENERAL"
    assert _svc().min_wage_zone("TAM", "Guerrero")["zone"] == "ZLFN"   # Guerrero, Tamaulipas
    monkeypatch.setattr(c, "MX_ZLFN_MUNICIPALITIES", (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),))
    assert _svc().min_wage_zone("BCN", "tijuana ")["zone"] == "ZLFN"
    assert _svc().min_wage_zone("CDMX", "Cuauhtémoc")["zone"] == "GENERAL"


def test_registration_partial_index_allows_one_open_row(db):
    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll.models import PayrollMxImssRegistration as R

    t = make_org(db)
    emp = new_employer(db, t.org.id)
    new_registration(db, t.org.id, emp["id"])
    db.add(R(organization_id=t.org.id, employer_profile_id=emp["id"], registro_patronal="Y1234567101",
             risk_class="I", fraction="1", effective_from=date(2027, 1, 1), status="ACTIVE"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

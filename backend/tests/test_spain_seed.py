"""Spain (ZP-ES-ENG-001, docs/spain) Phase 2: the canonical-pack seed.

Pins: every seeded value is one the spec states (§2, §4, §5) — no IRPF row and
no group 1–3 minimum base, because the spec gives none (gaps G-01 / G-02);
percentages are fractions; the seed lands Draft through ordinary rows,
re-runs idempotently and never touches a pack that has left Draft.
Synthetic database only; app modules are imported inside tests."""
from datetime import date
from decimal import Decimal

import pytest

SPEC_VALUES = {
    # key: (employee fraction, employer fraction, flat amount) — ZP-ES-ENG-001 §2 / §4 / §5
    "es_cc": ("0.047", "0.236", None),
    "es_mei": ("0.0015", "0.0075", None),
    "es_unemployment_general": ("0.0155", "0.055", None),
    "es_unemployment_temporary": ("0.016", "0.067", None),
    "es_fogasa": (None, "0.002", None),
    "es_training": ("0.001", "0.006", None),
    "es_overtime_force_majeure": ("0.02", "0.12", None),
    "es_overtime_other": ("0.047", "0.236", None),
    "es_solidarity_t1": ("0.0019", "0.0096", None),
    "es_solidarity_t1_upper": (None, None, "5611.32"),
    "es_solidarity_t2": ("0.0021", "0.0104", None),
    "es_solidarity_t2_upper": (None, None, "7651.80"),
    "es_solidarity_t3": ("0.0024", "0.0122", None),
    "es_base_max_monthly": (None, None, "5101.20"),
    "es_base_max_daily": (None, None, "170.04"),
    "es_base_min_group_4_7": (None, None, "1424.40"),
    "es_base_min_group_8_11": (None, None, "47.48"),
    "es_smi_monthly": (None, None, "1221"),
    "es_smi_daily": (None, None, "40.70"),
    "es_smi_annual": (None, None, "17094"),
    "es_short_contract_surcharge": (None, None, "33.62"),
    "es_short_contract_days": (None, None, "30"),
}


def _d(value):
    return None if value is None else Decimal(value)


def test_content_is_exactly_the_spec_values():
    from app.modules.payroll.engine.countries import spain_content as C

    assert (C.PACK_ID, C.CURRENCY, C.EFFECTIVE_FROM) == ("ES-PAYROLL-2026", "EUR", date(2026, 1, 1))
    rows = {r[0]: r for r in C.RATES}
    assert len(rows) == len(C.RATES)                                            # no duplicate keys
    assert set(rows) == set(SPEC_VALUES)
    for key, (employee, employer, flat) in SPEC_VALUES.items():
        _k, label, ee, er, fl, text, row_from, source = rows[key]
        assert (_d(ee), _d(er), _d(fl)) == (_d(employee), _d(employer), _d(flat)), key
        assert label and source and text is None and row_from is None, key


def test_spec_totals_and_solidarity_split_add_up():
    """§2 / §5 state both the total and the split; the seeded split must sum to it."""
    from app.modules.payroll.engine.countries import spain_content as C

    rows = {r[0]: r for r in C.RATES}
    total = lambda k: _d(rows[k][2] or "0") + _d(rows[k][3] or "0")  # noqa: E731
    expected = {"es_cc": "0.283", "es_mei": "0.009", "es_unemployment_general": "0.0705",
                "es_unemployment_temporary": "0.083", "es_training": "0.007", "es_overtime_force_majeure": "0.14",
                "es_overtime_other": "0.283", "es_solidarity_t1": "0.0115", "es_solidarity_t2": "0.0125",
                "es_solidarity_t3": "0.0146"}
    for key, value in expected.items():
        assert total(key) == Decimal(value), key


def test_no_invented_values_for_the_gaps():
    from app.modules.payroll.engine.countries import spain_content as C

    keys = {r[0] for r in C.RATES}
    assert not [k for k in keys if k.startswith("irpf")]                       # G-01: AEAT document only
    assert not keys & {"es_base_min_group_1", "es_base_min_group_2", "es_base_min_group_3"}   # G-02
    assert not [k for k in keys if "at_ep" in k]                               # G-03: employer fact


def test_seed_lands_draft_with_fraction_rates_and_readable_labels(db):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack
    from scripts.seed_spain_canonical_pack import seed_spain_pack

    pack = seed_spain_pack(db)
    db.commit()
    assert (pack.pack_id, pack.jurisdiction_country, pack.version, pack.status) == ("ES-PAYROLL-2026", "ES", "1.0",
                                                                                    "Draft")
    assert (pack.currency, pack.effective_from, pack.jurisdiction_state, pack.pack_type) == (
        "EUR", date(2026, 1, 1), None, "tax")
    rows = {r.component_key: r for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))}
    assert set(rows) == set(SPEC_VALUES)
    cc = rows["es_cc"]
    assert (cc.employee_rate_pct, cc.employer_rate_pct) == (Decimal("0.047"), Decimal("0.236"))
    assert (cc.employee_share, cc.employer_share, cc.total) == ("4.7%", "23.6%", "28.3%")
    assert rows["es_base_max_monthly"].flat_amount == Decimal("5101.20")
    assert rows["es_fogasa"].employee_share == "—" and rows["es_fogasa"].employer_share == "0.2%"
    assert db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "ES").count() == 1


def test_seed_reruns_idempotently_and_never_touches_a_live_pack(db):
    from app.modules.payroll.models import ContributionRate
    from scripts.seed_spain_canonical_pack import seed_spain_pack

    first = seed_spain_pack(db)
    db.commit()
    again = seed_spain_pack(db)
    db.commit()
    assert again.id == first.id
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == first.id).count() == len(
        SPEC_VALUES)
    first.status = "Active"
    db.commit()
    with pytest.raises(SystemExit):
        seed_spain_pack(db)


def test_seed_script_refuses_a_non_local_database():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "scripts" / "seed_spain_canonical_pack.py").read_text(
        encoding="utf-8")
    assert 'assert_local_database("seed_spain_canonical_pack")' in text

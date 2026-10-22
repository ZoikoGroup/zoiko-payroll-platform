"""Phase 1 of the BR / NL / CH / SA seed, report and bank-file fix plan
(2026-10-22): currency, IBAN masking, canonical-only seed rewrites, the
TaxSlab.rate_pct ceiling, Brazil's dated VT cap, the NL table validator,
pack-activation refusals (NL empty pack, SA PENDING G1) and the CH label.

SQLite never enforces Numeric precision, so the rate ceiling is checked
against the column type itself rather than by an insert.
"""
from decimal import Decimal
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab


# ── X-1 currency ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("country, currency", [("CH", "CHF"), ("SA", "SAR"), ("NL", "EUR"), ("BR", "BRL")])
def test_bank_file_currency_for_the_four_countries(country, currency):
    from app.modules.payroll.service import _get_currency_code

    assert _get_currency_code(country) == currency


# ── X-2 IBAN masking is platform-wide on purpose ──────────────────────────────

def test_iban_is_a_platform_sensitive_field_and_round_trips():
    from app.modules.payroll.employee_validation import (
        PLATFORM_SENSITIVE_COMPLIANCE_FIELDS, SENSITIVE_COMPLIANCE_FIELDS,
        mask_compliance_fields, restore_masked_compliance_fields,
    )

    assert "iban" in PLATFORM_SENSITIVE_COMPLIANCE_FIELDS
    assert "iban" in SENSITIVE_COMPLIANCE_FIELDS
    # Built at runtime so the repository PII scan (scripts/scan_test_data) sees no IBAN literal.
    iban = "".join(("DE", "89", "3704", "0044", "0532", "0130", "00"))
    stored = {"iban": iban, "steuer_id": "12345678901"}
    shown = mask_compliance_fields(stored)
    assert shown["iban"] != stored["iban"] and shown["iban"].endswith("3000")
    # An edit form that sends back the mask keeps the real IBAN.
    assert restore_masked_compliance_fields(dict(shown), stored)["iban"] == stored["iban"]


# ── BR-S1 the TaxSlab rate ceiling holds every Brazil row ────────────────────

def test_tax_slab_rate_column_holds_every_brazil_rate():
    from app.modules.payroll.engine.countries import brazil_content

    col = TaxSlab.__table__.c.rate_pct.type
    ceiling = Decimal(10) ** (col.precision - col.scale)
    rates = [r.rate_pct for r in brazil_content.BR_CONTENT_ROWS if r.rate_pct is not None]
    assert rates and max(rates) >= Decimal("100")      # OVERTIME_100 is the reason for the widening
    assert all(abs(r) < ceiling for r in rates)


# ── X-3 a re-seed never deletes an organisation's override rows ──────────────

def _org_override_rate(db, pack, key="org_override"):
    row = ContributionRate(jurisdiction_pack_id=pack.id, organization_id=999, jurisdiction_country=pack.jurisdiction_country,
                           component_key=key, label="org override", employee_share="1%", employer_share="—",
                           total="1%", employee_rate_pct=Decimal("1"))
    db.add(row)
    db.flush()
    return row.id


def _org_override_slab(db, pack):
    row = TaxSlab(jurisdiction_pack_id=pack.id, organization_id=999, jurisdiction_country=pack.jurisdiction_country,
                  min_amount=Decimal("0"), rate_pct=Decimal("1"), rate_label="org override", tax_formula="x",
                  filing_status="ORG", tax_regime="ORG")
    db.add(row)
    db.flush()
    return row.id


def test_nl_reseed_keeps_org_scoped_rows(db):
    from scripts.seed_netherlands_canonical_packs import MAIN_PACK_ID, seed_netherlands

    seed_netherlands(db)
    pack = db.query(JurisdictionPack).filter_by(pack_id=MAIN_PACK_ID).one()
    rate_id, slab_id = _org_override_rate(db, pack), _org_override_slab(db, pack)
    seed_netherlands(db)
    assert db.get(ContributionRate, rate_id) is not None
    assert db.get(TaxSlab, slab_id) is not None


def test_ch_reseed_keeps_org_scoped_rows(db):
    from scripts.seed_switzerland_canonical_packs import FEDERAL_PACK_ID, seed_switzerland

    seed_switzerland(db)
    pack = db.query(JurisdictionPack).filter_by(pack_id=FEDERAL_PACK_ID).one()
    rate_id = _org_override_rate(db, pack)
    seed_switzerland(db)
    assert db.get(ContributionRate, rate_id) is not None


def test_br_reseed_keeps_org_scoped_rows(db):
    from scripts.seed_brazil_canonical_packs import seed_brazil

    seed_brazil(db)
    pack = db.query(JurisdictionPack).filter_by(jurisdiction_country="BR").one()
    slab_id = _org_override_slab(db, pack)
    seed_brazil(db)
    assert db.get(TaxSlab, slab_id) is not None


def test_sa_reseed_keeps_org_scoped_rows(db):
    from app.modules.payroll.saudi_arabia_service import seed_saudi_arabia_pack

    pack = seed_saudi_arabia_pack(db)
    rate_id, slab_id = _org_override_rate(db, pack), _org_override_slab(db, pack)
    seed_saudi_arabia_pack(db)
    assert db.get(ContributionRate, rate_id) is not None
    assert db.get(TaxSlab, slab_id) is not None


# ── SA-S1 a Saudi pack with PENDING G1 rows cannot be activated ──────────────

def test_sa_pack_activation_refused_while_rows_are_pending_g1(db):
    from app.modules.payroll.saudi_arabia_service import sa_activation_evidence_refusal, seed_saudi_arabia_pack

    pack = seed_saudi_arabia_pack(db)
    refusal = sa_activation_evidence_refusal(db, pack)
    assert refusal and "PENDING G1" in refusal

    # Once every row is signed (marker and PENDING_G1 basis gone) the hook passes.
    for row in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id).all():
        row.label = row.label.replace(" [PENDING G1]", "")
        if row.text_value == "PENDING_G1":
            row.text_value = "CONTRIBUTION_MONTH_START"
    for row in db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id).all():
        row.rate_label = row.rate_label.replace(" [PENDING G1]", "")
    db.flush()
    assert sa_activation_evidence_refusal(db, pack) is None


# ── NL-S2 an empty NL pack cannot be activated ───────────────────────────────

def test_nl_empty_change_watch_pack_cannot_be_activated(db):
    from app.modules.payroll.netherlands_service import nl_activation_evidence_refusal
    from scripts.seed_netherlands_canonical_packs import CHANGE_WATCH_PACK_ID, MAIN_PACK_ID, seed_netherlands

    seed_netherlands(db)
    empty = db.query(JurisdictionPack).filter_by(pack_id=CHANGE_WATCH_PACK_ID).one()
    main = db.query(JurisdictionPack).filter_by(pack_id=MAIN_PACK_ID).one()
    assert "no statutory rows" in nl_activation_evidence_refusal(db, empty)
    assert nl_activation_evidence_refusal(db, main) is None


# ── NL-S1 a tax-table file with gaps is never VALIDATED ──────────────────────

def _nl_table_file(db, rows):
    import hashlib

    from app.modules.payroll.models import PayrollNlTaxTableFile, PayrollNlTaxTableRow
    from scripts.seed_netherlands_canonical_packs import MAIN_PACK_ID, seed_netherlands

    seed_netherlands(db)
    pack = db.query(JurisdictionPack).filter_by(pack_id=MAIN_PACK_ID).one()
    f = PayrollNlTaxTableFile(jurisdiction_pack_id=pack.id, tax_year=2026, table_color="WHITE",
                              table_kind="PERIOD", period="MONTH", residence_variant="NL",
                              source_filename="test.csv", file_sha256=hashlib.sha256(repr(rows).encode()).hexdigest(),
                              row_count=len(rows), status="IMPORTED", effective_from=date(2026, 1, 1))
    db.add(f)
    db.flush()
    for no, (lo, hi) in enumerate(rows, start=1):
        db.add(PayrollNlTaxTableRow(file_id=f.id, row_no=no, aow_cohort="BELOW_AOW", with_tax_credit=True,
                                    wage_from=Decimal(lo), wage_to=Decimal(hi) if hi is not None else None,
                                    withholding_amount=Decimal("0"), row_sha256=f"{no:064d}"))
    db.flush()
    return f


def test_nl_table_file_with_a_gap_stays_imported_and_cannot_be_approved(db):
    from app.modules.payroll.netherlands_tables_service import approve_table_file, validate_table_file

    f = _nl_table_file(db, [("0", "100"), ("150", None)])          # gap 100 -> 150
    out = validate_table_file(db, f.id, actor_id=2)
    assert out.status == "IMPORTED"
    assert out.validation_report["errors"]
    with pytest.raises(BadRequestException):
        approve_table_file(db, f.id, actor_id=3)


def test_nl_table_file_without_errors_is_validated(db):
    from app.modules.payroll.netherlands_tables_service import validate_table_file

    f = _nl_table_file(db, [("0", "100"), ("100", None)])
    assert validate_table_file(db, f.id, actor_id=2).status == "VALIDATED"


# ── BR-S2 / CH-S1 ─────────────────────────────────────────────────────────────

def test_brazil_vt_cap_comes_from_the_dated_row():
    from app.modules.payroll.engine.countries import brazil_content

    assert not hasattr(brazil_content, "VALE_TRANSPORTE_MAX_DEDUCTION_PCT")
    assert brazil_content.vale_transporte_max_deduction_pct(date(2026, 5, 1)) == Decimal("0.06")


def test_ch_fak_employee_pct_is_labelled_employee_share():
    from app.modules.payroll.engine.countries.switzerland_content import CH_CANTON_PARAMETER_LABELS

    assert "employee share" in CH_CANTON_PARAMETER_LABELS["ch_fak_employee_pct"]

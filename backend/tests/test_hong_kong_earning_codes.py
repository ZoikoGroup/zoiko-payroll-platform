"""Hong Kong earning-code catalogue (HK-006, gap audit STEP 3).

Each default HK earning code is mapped separately and effective-dated for EO
wages, MPF relevant income, SMW countable wages and the IR56B field; every
mapping cites an archived source (SHA-256) or is PENDING with the specialist's
question; the engine reads the catalogue from the pinned pack (no per-code
logic) and fails closed on anything it cannot resolve. TEST data only; app.*
imported inside the tests (collection-order hazard).
"""
from datetime import date
from decimal import Decimal as D

import pytest

from tests.test_hong_kong import _calc, packs  # noqa: F401  (packs is a fixture)
from tests.test_hong_kong_e2e import (  # noqa: F401  (hk is a fixture)
    CHECKER, MAKER, _employee, _item, _month, _profile, _spaced_codes, hk,
)

OBLIGATIONS = {"EO_WAGES", "MPF_RI", "SMW_WAGES", "IRD"}


def _line(result, obligation, source):
    return next(l for l in result.hk_calculation_trace["classification"][obligation]["lines"] if l["component"] == source)


def _source_id(db, url_part):
    from app.modules.payroll.models import SourceArtifact

    return db.query(SourceArtifact).filter(SourceArtifact.source_url.contains(url_part)).order_by(SourceArtifact.id.desc()).first().id


def _slab(db, pack, **kw):
    from app.modules.payroll.models import TaxSlab

    row = TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="HK", organization_id=None, min_amount=D("0"),
                  rate_pct=D("0"), rate_label="TEST row", tax_formula=kw.pop("tax_formula", "TEST"),
                  source_document_id=_source_id(db, "ConciseGuide/03"), **kw)
    db.add(row)
    db.commit()
    return row


# ── the catalogue itself ───────────────────────────────────────────────────────────────────────

def test_every_default_code_maps_each_obligation_to_a_hashed_source_with_a_status(db, packs):
    from app.modules.payroll import hong_kong_service

    cat = hong_kong_service.earning_code_catalogue(db, on=date(2026, 6, 30))
    assert cat["specialistVerified"] is False and len(cat["codes"]) == 18
    for code in cat["codes"]:
        assert set(code["mappings"]) == OBLIGATIONS, code["code"]
        for obligation, m in code["mappings"].items():
            where = (code["code"], obligation)
            assert len(m["source"]["sha256"] or "") == 64, where                # archived, hashed
            assert m["status"] in ("SOURCED", "PENDING"), where
            assert (m["basis"] if m["status"] == "SOURCED" else m["question"]), where   # a quote or a question
            assert m["treatment"] in ("INCLUDED", "EXCLUDED", "REVIEW"), where
    by_code = {c["code"]: c for c in cat["codes"]}
    assert (by_code["HK_COMMISSION"]["mappings"]["IRD"]["irdField"], by_code["HK_COMMISSION"]["mappings"]["IRD"]["irdItem"]) \
        == ("COMMISSION_FEES", "11(d)")
    assert by_code["HK_BONUS_DISC"]["mappings"]["IRD"]["irdItem"] == "11(e)"
    assert by_code["HK_SEVERANCE_LSP"]["mappings"]["MPF_RI"]["treatment"] == "EXCLUDED"     # MPFA: SP / LSP excluded
    assert all(b["knownCode"] for b in cat["bindings"])
    assert {b["source"] for b in cat["bindings"]} >= {"basic", "hra", "special_allowance", "overtime",
                                                     "named_allowances", "additional_compensation"}


def test_the_configuration_screen_lists_the_catalogue_with_status_and_source(db, packs):
    from app.modules.payroll import hong_kong_service

    out = hong_kong_service.domains(db, packs[1].id)
    assert out["unmapped"] == []
    [dom] = [d for d in out["domains"] if d["key"] == "earning_classification"]
    keys = {r["key"] for r in dom["rows"]}
    assert keys == {"HK_EARNING_CODE", "HK_EARNING_SOURCE"}
    statuses = {r["status"] for r in dom["rows"] if r["key"] == "HK_EARNING_CODE"}
    assert "PENDING — specialist question" in statuses and "SOURCED" not in statuses       # nothing pre-verified
    assert all(r["source"]["sha256"] for r in dom["rows"])


# ── the engine reads it ────────────────────────────────────────────────────────────────────────

def test_one_earning_is_included_in_one_base_and_excluded_from_another(db, packs):
    """A discretionary bonus: MPF relevant income (MPFA 'bonus at employer's discretion — Y') but
    not EO wages (Concise Guide ch.3 exclusion 6) nor SMW wages; IR56B item 11(e)."""
    r = _calc(db, "25000", basic=D("20000"), additional_compensation=D("5000"),
              hk_earning_sources={"attendance:bonus": "5000"})
    for obligation, treatment in (("MPF_RI", "INCLUDED"), ("EO_WAGES", "EXCLUDED"), ("SMW_WAGES", "EXCLUDED"),
                                  ("IRD", "INCLUDED")):
        line = _line(r, obligation, "attendance:bonus")
        assert (line["code"], line["treatment"], D(line["amount"])) == ("HK_BONUS_DISC", treatment, D("5000.00"))
    cls = r.hk_calculation_trace["classification"]
    assert D(cls["MPF_RI"]["included"]) == D("25000.00")
    assert (D(cls["EO_WAGES"]["included"]), D(cls["EO_WAGES"]["excluded"])) == (D("20000.00"), D("5000.00"))
    assert r.hk_calculation_trace["ird"]["reportable"]["BONUS"] == "5000.00"
    assert (r.employee_pension, r.employer_pension) == (D("1250.00"), D("1250.00"))       # 5% of 25,000


def test_unbound_named_allowance_falls_back_to_its_family_code(db, packs):
    r = _calc(db, "21000", basic=D("20000"), hk_earning_sources={"allowance:laundry": "1000"})
    line = _line(r, "EO_WAGES", "allowance:laundry")
    assert line["code"] == "HK_ALLOWANCE_UNSPEC" and line["treatment"] == "REVIEW"        # PENDING → REVIEW
    assert _line(r, "MPF_RI", "allowance:laundry")["treatment"] == "INCLUDED"


def test_an_unknown_code_fails_closed(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    _slab(db, packs[1], rule_type="HK_EARNING_SOURCE", filing_status="allowance:mystery", tax_regime="HK_NOT_A_CODE")
    with pytest.raises(HongKongCalculationBlockedError, match="HK_NOT_A_CODE"):
        _calc(db, "21000", basic=D("20000"), hk_earning_sources={"allowance:mystery": "1000"})


def test_a_source_with_no_binding_fails_closed(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError
    from app.modules.payroll.models import TaxSlab

    db.query(TaxSlab).filter(TaxSlab.rule_type == "HK_EARNING_SOURCE", TaxSlab.filing_status == "overtime").delete()
    db.commit()
    with pytest.raises(HongKongCalculationBlockedError, match="not bound"):
        _calc(db, "21000", basic=D("20000"), overtime=D("1000"))


def test_a_pending_mpf_mapping_blocks_and_a_pending_ird_mapping_stays_unmapped(db, packs):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import HongKongCalculationBlockedError

    _slab(db, packs[1], rule_type="HK_EARNING_SOURCE", filing_status="allowance:pilon", tax_regime="HK_PILON")
    with pytest.raises(HongKongCalculationBlockedError, match="pending specialist review"):   # MPFA lists no PILON example
        _calc(db, "21000", basic=D("20000"), hk_earning_sources={"allowance:pilon": "1000"})
    r = _calc(db, "21000", basic=D("20000"), overtime=D("1000"))      # overtime's IR56B item is PENDING
    ird = _line(r, "IRD", "overtime")
    assert (ird["irdField"], ird["proposedField"], ird["mappingStatus"]) == (
        "UNMAPPED_REQUIRES_CLASSIFICATION", "SALARY_WAGES", "PENDING")


# ── effective dating and the specialist's answer, through the governed path ────────────────────

def test_a_mapping_change_mid_year_applies_from_its_effective_date(db, hk, monkeypatch):
    """Split the cash-allowance IR56B mapping on 1 June 2026: May keeps item 11(k), June uses 11(a)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import TaxConfigurationAudit, TaxSlab

    p26 = hk.packs[1]
    row = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == p26.id, TaxSlab.rule_type == "HK_EARNING_CODE",
                                   TaxSlab.filing_status == "HK_CASH_ALLOWANCE", TaxSlab.tax_regime == "IRD").one()
    change = {"reason": "TEST mid-year reclassification", "sourceDocumentId": _source_id(db, "ir56b_notes"),
              "effectiveFrom": "2026-06-01", "irdField": "SALARY_WAGES"}
    with pytest.raises(BadRequestException):                         # an Active pack is never edited in place
        hong_kong_service.split_catalogue_row(db, row.id, change, MAKER.id)
    db.rollback()
    p26.status = "Draft"
    db.commit()
    out = hong_kong_service.split_catalogue_row(db, row.id, change, MAKER.id)
    assert (out["endedOn"], out["effectiveFrom"]) == ("2026-05-31", "2026-06-01")
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_id == row.id,
                                                  TaxConfigurationAudit.entity_type == "hk_statutory_slab").count() == 1
    p26.status = "Active"                                            # TEST-only, as the hk fixture does
    db.commit()
    may, june = _item(db, _month(db, hk.org, 5), hk.emp), _item(db, _month(db, hk.org, 6), hk.emp)
    special = D(_line(may, "IRD", "special_allowance")["amount"])
    assert special > 0
    assert _line(may, "IRD", "special_allowance")["irdField"] == "OTHER_REWARDS_ALLOWANCES"
    assert _line(june, "IRD", "special_allowance")["irdField"] == "SALARY_WAGES"
    assert sum(D(v) for v in june.hk_calculation_trace["ird"]["reportable"].values()) == D(str(june.gross_pay))


def test_the_specialists_answer_clears_a_pending_mapping_only_with_a_reviewed_source(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.engine.countries.hong_kong import code_meta
    from app.modules.payroll.models import SourceArtifact, TaxSlab

    p26 = hk.packs[1]
    p26.status = "Draft"
    db.commit()
    row = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == p26.id, TaxSlab.filing_status == "HK_OVERTIME_CONTRACT",
                                   TaxSlab.tax_regime == "IRD").one()
    assert code_meta(row)["status"] == "PENDING"
    with pytest.raises(BadRequestException, match="reviewed"):       # the seeded archive copy is not yet reviewed
        hong_kong_service.update_row(db, "slab", row.id, {"reason": "answer", "sourceDocumentId": row.source_document_id,
                                                          "specialistVerified": True}, MAKER.id)
    reviewed = SourceArtifact(agency="HK specialist (TEST)", title="TEST answer", checksum_sha256="2" * 64,
                              file_path="answer.pdf", created_by_id=MAKER.id, reviewer_id=CHECKER.id)
    db.add(reviewed)
    db.commit()
    out = hong_kong_service.update_row(db, "slab", row.id, {"reason": "TEST: overtime is item 11(a)",
                                                            "sourceDocumentId": reviewed.id, "specialistVerified": True},
                                       MAKER.id)
    db.refresh(row)
    meta = code_meta(row)
    assert meta["status"] == "SOURCED" and meta["question"] is None and meta["answeredQuestion"]
    assert "[PENDING]" not in row.rate_label and out["status"] == "SOURCED"

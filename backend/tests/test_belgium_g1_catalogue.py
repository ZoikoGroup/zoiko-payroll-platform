"""Gate G1 must fail on an empty or incomplete Belgian catalogue.

G1 is judged against the canonical Belgian pack (the Active one, else the one
with the latest effective date). An empty pack has no "[PENDING G1]" rows, so
"no_pending_rows" used to pass for it — e.g. an empty BE-PAYROLL-2027 Draft
shadowing the seeded 2026 pack. G1 now also requires every catalogue key to
have a row (catalogue_complete), and an empty pack never reads "every row
signed". This makes the gate stricter only. SYNTHETIC data only."""
from datetime import date


def _g1(db):
    from app.modules.payroll import belgium_readiness as r

    gate = next(g for g in r.be_readiness(db)["gates"] if g["gate"] == "G1")
    return gate, {c["key"]: c for c in gate["checks"]}


def _empty_pack(db, pack_id, start, end):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country="BE", pack_type="tax",
                            status="Draft", effective_from=start, effective_to=end, tax_year=str(start.year))
    db.add(pack)
    db.commit()
    return pack


def test_no_pack_fails_g1(db):
    gate, checks = _g1(db)
    assert not gate["passed"]
    assert checks["catalogue_complete"]["ok"] is False and checks["no_pending_rows"]["ok"] is False


def test_an_empty_pack_fails_g1(db):
    _empty_pack(db, "BE-EMPTY-TEST", date(2026, 1, 1), date(2026, 12, 31))
    gate, checks = _g1(db)
    assert not gate["passed"]
    assert checks["pack_seeded"]["ok"] is True                       # a pack exists ...
    assert checks["catalogue_complete"]["ok"] is False                # ... but holds none of the catalogue
    assert checks["no_pending_rows"]["ok"] is False and checks["no_pending_rows"]["detail"] == "no catalogue rows to sign"


def test_a_partly_seeded_pack_fails_g1(db):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import ContributionRate

    pack = be.seed_belgium_pack(db)
    db.commit()
    gone = list(content.KEYS)[:3]
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.component_key.in_(gone)).delete(synchronize_session=False)
    db.commit()
    _gate, checks = _g1(db)
    assert checks["catalogue_complete"]["ok"] is False
    assert checks["catalogue_complete"]["detail"].startswith(f"3 of {len(content.KEYS)} catalogue row(s) missing")


def test_the_seeded_catalogue_is_complete_but_still_unsigned(db):
    from app.modules.payroll import belgium_service as be

    be.seed_belgium_pack(db)
    db.commit()
    gate, checks = _g1(db)
    assert checks["catalogue_complete"]["ok"] is True
    assert checks["no_pending_rows"]["ok"] is False                   # seeded rows are PENDING G1
    assert not gate["passed"]


def test_an_empty_newer_pack_no_longer_passes_no_pending_rows(db):
    """The production case: BE-PAYROLL-2026 seeded, an empty BE-PAYROLL-2027 Draft created beside it."""
    from app.modules.payroll import belgium_service as be

    be.seed_belgium_pack(db)
    db.commit()
    _empty_pack(db, "BE-PAYROLL-2027", date(2027, 1, 1), date(2027, 12, 31))   # latest effective date -> judged
    gate, checks = _g1(db)
    assert checks["pack_seeded"]["detail"].startswith("BE-PAYROLL-2027")
    assert checks["catalogue_complete"]["ok"] is False
    assert checks["no_pending_rows"]["ok"] is False                   # used to read "every row signed"
    assert not gate["passed"]

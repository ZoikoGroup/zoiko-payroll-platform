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


def _on(monkeypatch, day):
    from app.modules.payroll import belgium_readiness as r

    monkeypatch.setattr(r, "_today", lambda: day)


def test_a_current_pack_is_judged_before_an_empty_future_pack(db, monkeypatch):
    """The production case: BE-PAYROLL-2026 seeded (in force), an empty BE-PAYROLL-2027 Draft beside it."""
    from app.modules.payroll import belgium_service as be

    be.seed_belgium_pack(db)
    db.commit()
    _empty_pack(db, "BE-PAYROLL-2027", date(2027, 1, 1), date(2027, 12, 31))
    _on(monkeypatch, date(2026, 11, 25))
    gate, checks = _g1(db)
    assert checks["pack_seeded"]["detail"] == "Judging BE-PAYROLL-2026 v1.0 (Draft): in force today"
    assert checks["catalogue_complete"]["ok"] is True
    assert checks["no_pending_rows"]["ok"] is False                   # still fails: every row unsigned
    assert not gate["passed"]


def test_an_empty_current_pack_is_judged_and_fails(db, monkeypatch):
    from app.modules.payroll import belgium_service as be

    _empty_pack(db, "BE-EMPTY-NOW", date(2026, 1, 1), date(2026, 12, 31))
    be.seed_belgium_pack(db)                                          # seeded 2026 window too
    db.commit()
    _empty_pack(db, "BE-FUTURE", date(2027, 1, 1), date(2027, 12, 31))
    _on(monkeypatch, date(2026, 6, 1))
    gate, checks = _g1(db)
    assert "in force today" in checks["pack_seeded"]["detail"] and "BE-FUTURE" not in checks["pack_seeded"]["detail"]
    assert not gate["passed"]


def test_only_a_future_pack_is_judged(db, monkeypatch):
    _empty_pack(db, "BE-PAYROLL-2027", date(2027, 1, 1), date(2027, 12, 31))
    _on(monkeypatch, date(2026, 11, 25))
    gate, checks = _g1(db)
    assert checks["pack_seeded"]["detail"] == ("Judging BE-PAYROLL-2027 v1.0 (Draft): no pack is in force today; "
                                               "the next upcoming pack (starts 2027-01-01)")
    assert checks["catalogue_complete"]["ok"] is False and not gate["passed"]          # empty: still fails


def test_the_earliest_upcoming_pack_is_judged(db, monkeypatch):
    from app.modules.payroll import belgium_readiness as r

    _empty_pack(db, "BE-PAYROLL-2028", date(2028, 1, 1), date(2028, 12, 31))
    _empty_pack(db, "BE-PAYROLL-2027", date(2027, 1, 1), date(2027, 12, 31))
    pack, why = r.be_g1_pack(db, today=date(2026, 11, 25))
    assert pack.pack_id == "BE-PAYROLL-2027" and why.startswith("no pack is in force today")


def test_an_active_pack_is_judged_first(db, monkeypatch):
    from app.modules.payroll import belgium_service as be

    pack = be.seed_belgium_pack(db)
    db.commit()
    _empty_pack(db, "BE-NEWER", date(2026, 6, 1), date(2026, 12, 31))   # also in force, later start
    pack.status = "Active"                                            # (set directly: activation is refused)
    db.commit()
    _on(monkeypatch, date(2026, 11, 25))
    gate, checks = _g1(db)
    assert checks["pack_seeded"]["detail"] == "Judging BE-PAYROLL-2026 v1.0 (Active): the Active pack (in force today)"
    assert checks["no_pending_rows"]["ok"] is False and not gate["passed"]   # Active but unsigned: still fails


def test_only_past_packs_judge_the_most_recent(db):
    from app.modules.payroll import belgium_readiness as r

    _empty_pack(db, "BE-PAYROLL-2024", date(2024, 1, 1), date(2024, 12, 31))
    _empty_pack(db, "BE-PAYROLL-2025", date(2025, 1, 1), date(2025, 12, 31))
    pack, why = r.be_g1_pack(db, today=date(2026, 11, 25))
    assert pack.pack_id == "BE-PAYROLL-2025" and why == "no pack is in force today or upcoming; the most recent pack"


def test_no_pack_at_all(db):
    from app.modules.payroll import belgium_readiness as r

    assert r.be_g1_pack(db, today=date(2026, 11, 25)) == (None, "no Belgian tax pack exists")


# ── Release Readiness: who acts on each check ────────────────────────────────
def test_every_readiness_check_names_who_acts(db):
    from app.modules.payroll import belgium_readiness as r

    gates = r.be_readiness(db)["gates"]
    checks = [c for g in gates for c in g["checks"]]
    assert checks and all(c["actor"] in r.ACTORS for c in checks)
    by_key = {c["key"]: c["actor"] for c in checks}
    assert by_key["transmission_adapter"] == "code"
    assert by_key["catalogue_complete"] == "data" and by_key["no_pending_rows"] == "sign-off"
    assert by_key["be-signoff-security"] == "sign-off" and by_key["be-owner-content"] == "sign-off"
    assert all(by_key[k] == "data" for k in by_key if k.startswith("schema_"))
    assert all(g["owner"] for g in gates)                                  # the gate's owner is shown too


# ── overlapping packs that cover today ───────────────────────────────────────
def test_overlapping_current_packs_judge_the_latest_start_and_warn(db, monkeypatch):
    from app.modules.payroll import belgium_readiness as r

    _empty_pack(db, "BE-OVERLAP-EARLY", date(2026, 1, 1), date(2026, 12, 31))
    _empty_pack(db, "BE-OVERLAP-LATE", date(2026, 6, 1), date(2026, 12, 31))
    _on(monkeypatch, date(2026, 11, 25))
    pack, why = r.be_g1_pack(db)
    assert pack.pack_id == "BE-OVERLAP-LATE" and why == "in force today"
    warning = r.be_g1_overlap_warning(db)
    assert warning.startswith("2 non-Active Belgian packs cover today: BE-OVERLAP-LATE v1.0")
    assert "BE-OVERLAP-EARLY v1.0" in warning and "latest start date, BE-OVERLAP-LATE v1.0" in warning
    state = r.be_readiness(db)
    assert state["warnings"] == [warning]
    gate = next(g for g in state["gates"] if g["gate"] == "G1")
    assert not gate["passed"]                                         # the judged (empty) pack still fails


def test_a_single_current_pack_has_no_overlap_warning(db, monkeypatch):
    from app.modules.payroll import belgium_readiness as r
    from app.modules.payroll import belgium_service as be

    be.seed_belgium_pack(db)
    db.commit()
    _empty_pack(db, "BE-PAYROLL-2027", date(2027, 1, 1), date(2027, 12, 31))   # future: not overlapping today
    _on(monkeypatch, date(2026, 11, 25))
    assert r.be_g1_overlap_warning(db) is None and r.be_readiness(db)["warnings"] == []
    summary = be.be_statutory_summary(db)
    assert summary["readinessWarnings"] == []

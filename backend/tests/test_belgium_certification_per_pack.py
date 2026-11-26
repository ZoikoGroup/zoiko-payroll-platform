"""Belgian golden-vector certification runs count only for the pack they were
recorded against, and only while that pack's content is unchanged.

A run stores the pack it certified (jurisdiction_pack_id) and a SHA-256
fingerprint of the pack's content at run time (be_pack_fingerprint); gate G1
and pack activation accept it only for the same pack while the fingerprint
still matches. Stricter only: runs recorded before runs were tied to packs
count for no pack. Existing run records are never altered. SYNTHETIC data only."""
from datetime import date

from tests.test_belgium_super_admin import _c, seeded  # noqa: F401  (pytest fixture)


def _g():
    from app.modules.payroll import belgium_golden

    return belgium_golden


def _run(db, pack=None, status="PASS", fingerprint=None, legacy=False):
    """A certification run row, as record_be_golden_certification would store it."""
    from app.modules.payroll.models import TestCertificationRun

    run = TestCertificationRun(jurisdiction_country="BE", status=status, real_case_count=1, total_cases=1,
                               passed_cases=1 if status == "PASS" else 0, failed_cases=0 if status == "PASS" else 1,
                               jurisdiction_pack_id=None if legacy else pack.id,
                               content_fingerprint=None if legacy else (fingerprint or _g().be_pack_fingerprint(db, pack)))
    db.add(run)
    db.commit()
    return run


def _other_pack(db, pack_id="BE-PAYROLL-2027"):
    from app.modules.payroll.models import JurisdictionPack

    other = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country="BE", pack_type="tax",
                             status="Draft", effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31),
                             tax_year="2027")
    db.add(other)
    db.commit()
    return other


def test_no_run_fails(db, seeded):
    run, why = _g().be_certification_for(db, seeded)
    assert run is None and why == "the certification run is missing: no run has been recorded for BE-PAYROLL-2026 v1.0"


def test_a_pass_run_for_the_same_pack_counts(db, seeded):
    run = _run(db, seeded)
    assert _g().be_certification_for(db, seeded) == (run, None)


def test_a_pass_run_for_a_different_pack_does_not_count(db, seeded):
    other = _other_pack(db)
    _run(db, other)
    run, why = _g().be_certification_for(db, seeded)
    assert run is None
    assert why.startswith("the certification run is missing for BE-PAYROLL-2026 v1.0: the last certification run "
                          "was for BE-PAYROLL-2027 v1.0")


def test_a_pass_run_followed_by_a_row_edit_no_longer_counts(db, seeded):
    from app.modules.payroll.models import ContributionRate

    _run(db, seeded)
    row = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == seeded.id).first()
    row.text_value = "SYNTHETIC CHANGE"
    db.commit()
    _run_, why = _g().be_certification_for(db, seeded)
    assert why.startswith("content changed after the last certification run for BE-PAYROLL-2026 v1.0")


def test_a_fail_run_never_counts(db, seeded):
    run = _run(db, seeded, status="FAIL")
    assert _g().be_certification_for(db, seeded) == (
        run, f"the last certification run for BE-PAYROLL-2026 v1.0 ({run.run_at.date().isoformat()}) is FAIL")


def test_a_legacy_run_without_a_pack_counts_for_no_pack(db, seeded):
    _run(db, legacy=True)
    run, why = _g().be_certification_for(db, seeded)
    assert run is None and "is not tied to any pack" in why


def test_the_newest_run_for_the_pack_decides(db, seeded):
    _run(db, seeded)                                                  # an older PASS ...
    latest = _run(db, seeded, status="FAIL")                         # ... superseded by a FAIL
    assert _g().be_certification_for(db, seeded)[0] == latest
    assert _g().be_certification_for(db, seeded)[1].endswith("is FAIL")


def test_recording_a_run_stores_the_pack_and_its_fingerprint(db, seeded):
    run, _check = _g().record_be_golden_certification(db, seeded, None)
    db.commit()
    assert run.jurisdiction_pack_id == seeded.id
    assert run.content_fingerprint == _g().be_pack_fingerprint(db, seeded) and len(run.content_fingerprint) == 64


def test_existing_run_records_are_not_altered(db, seeded):
    from app.modules.payroll.models import TestCertificationRun

    legacy = _run(db, legacy=True)
    before = {c.name: getattr(legacy, c.name) for c in TestCertificationRun.__table__.columns}
    _g().be_certification_for(db, seeded)
    assert not (db.new or db.dirty or db.deleted)
    db.refresh(legacy)
    assert {c.name: getattr(legacy, c.name) for c in TestCertificationRun.__table__.columns} == before

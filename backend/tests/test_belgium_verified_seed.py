"""scripts/seed_belgium_verified_values.py: loads a file of verified Belgian
values into a Draft pack through the SAME governed import as the Super Admin
"Import from file" button. Dry run by default; --apply writes the rows (in force: no signing step since the
gate removal, 2026-11-25); a
missing or unverified (AI / SAMPLE / DRAFT / NOT VERIFIED) source is refused,
and so is the AI-drafted workbook by name. SYNTHETIC values only: every number
here is a 0.00 placeholder, never Belgian statutory content."""
import asyncio
import csv
import io
import json
from types import SimpleNamespace

import pytest

from tests.test_belgium_super_admin import _c, _rate, _verified_source, seeded  # noqa: F401  (pytest fixture)

IMPORTER = 611
ZERO = "0.00"                                      # placeholder, not a Belgian figure


def _seed_script():
    from scripts import seed_belgium_verified_values

    return seed_belgium_verified_values


def _rate_key():
    """A catalogue key holding a rate (picked from the catalogue, not typed)."""
    c = _c()
    return next(k for k, (_g, kind, _r, _l) in c.KEYS.items() if kind == c.KIND_RATE and not c.is_reference_only(k))


def _csv(rows):
    columns = ["sheet"] + sorted({k for r in rows for k in r} - {"sheet"})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return out.getvalue().encode("utf-8")


def _scalar_row(db, pack, source, key=None):
    key = key or _rate_key()
    return {"sheet": "Scalar keys", "rowId": str(_rate(db, pack, key).id), "key": key,
            "employeeRatePct": ZERO, "sourceDocumentId": source}


def _run(db, pack, data, filename="verified.csv", apply=False):
    return _seed_script().run(db, pack_id=pack.pack_id, data=data, filename=filename, actor_id=IMPORTER, apply=apply)


def _pack_state(db, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = [(r.component_key, r.label, r.employee_rate_pct, r.employer_rate_pct, r.flat_amount, r.text_value,
              r.source_document_id) for r in db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == pack.id).order_by(ContributionRate.id)]
    slabs = [(s.rule_type, s.rate_label, s.min_amount, s.max_amount, s.rate_pct, s.source_document_id)
             for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).order_by(TaxSlab.id)]
    return rates, slabs


def test_dry_run_writes_nothing(db, seeded):
    src = _verified_source(db)
    before = _pack_state(db, seeded)
    out = _run(db, seeded, _csv([_scalar_row(db, seeded, str(src.id))]))
    assert out["applied"] is False and out["refusals"] == [] and out["errors"] == []
    assert out["changes"] >= 1 and sum(sum(v.values()) for v in out["perGroup"].values()) == 1
    db.expire_all()
    assert _pack_state(db, seeded) == before


def test_apply_writes_rows_in_force(db, seeded):
    from decimal import Decimal

    src = _verified_source(db)
    out = _run(db, seeded, _csv([_scalar_row(db, seeded, str(src.id))]), apply=True)
    assert out["applied"] is True
    db.expire_all()
    row = _rate(db, seeded, _rate_key())
    assert row.employee_rate_pct == Decimal(ZERO) and row.source_document_id == src.id
    assert _c().PENDING_MARK not in row.label                   # no marker: in force (gate removal 2026-11-25)
    assert seeded.status == "Draft" and seeded.approved_by_id is None    # nothing approved / activated


def test_a_missing_source_is_refused_and_nothing_is_written(db, seeded):
    before = _pack_state(db, seeded)
    out = _run(db, seeded, _csv([_scalar_row(db, seeded, "")]), apply=True)
    assert out["applied"] is False and out["refusals"] and "source is empty" in out["refusals"][0]
    db.expire_all()
    assert _pack_state(db, seeded) == before


@pytest.mark.parametrize("source", ["AI-DRAFT workbook", "ai generated", "SAMPLE source", "draft ref",
                                    "Not Verified yet"])
def test_an_unverified_source_text_is_refused(db, seeded, source):
    out = _run(db, seeded, _csv([_scalar_row(db, seeded, source)]), apply=True)
    assert out["applied"] is False and out["refusals"]


def test_a_source_document_marked_unverified_is_refused(db, seeded):
    from app.modules.payroll.models import SourceArtifact

    src = SourceArtifact(agency="Synthetic", title="SYNTHETIC [UNVERIFIED: not archived]", form_number="SYN-AI-DRAFT",
                         created_by_id=900)
    db.add(src)
    db.commit()
    out = _run(db, seeded, _csv([_scalar_row(db, seeded, str(src.id))]), apply=True)
    assert out["applied"] is False and "marked as not verified" in out["refusals"][0]


def test_ai_is_matched_as_a_word_not_as_letters():
    script = _seed_script()
    assert script.banned_source("AI") and script.banned_source("from an AI draft")
    assert not script.banned_source("SYNTHETIC detail reference") and not script.banned_source("SYN-1")


def test_the_ai_draft_workbook_is_refused_by_name(db, seeded):
    with pytest.raises(_seed_script().Refused, match="AI-drafted workbook"):
        _run(db, seeded, b"not read", filename="BE_2026_AI_DRAFT.xlsx")


def test_draft_sources_sheet_is_refused(db, seeded):
    rows = [{"sheet": "Draft sources", "reference": "SYN-REF", "title": "SYNTHETIC"}]
    data = json.dumps({"rows": rows}).encode("utf-8")
    out = _run(db, seeded, data, filename="verified.json", apply=True)
    assert out["applied"] is False and any("Draft sources" in r for r in out["refusals"])


def test_summary_lists_missing_catalogue_keys(db, seeded):
    src = _verified_source(db)
    out = _run(db, seeded, _csv([_scalar_row(db, seeded, str(src.id))]))
    assert _rate_key() not in out["missingKeys"]
    assert len(out["missingKeys"]) == len(_c().KEYS) - 1


def test_validation_errors_block_apply(db, seeded):
    src = _verified_source(db)
    bad = {**_scalar_row(db, seeded, str(src.id)), "rowId": "999999"}
    before = _pack_state(db, seeded)
    out = _run(db, seeded, _csv([bad]), apply=True)
    assert out["applied"] is False and out["errors"]
    db.expire_all()
    assert _pack_state(db, seeded) == before


@pytest.fixture
def db2():
    """A second, independent database with the same empty schema as `db`."""
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from tests.conftest import _sqlite_schema_template

    raw = sqlite3.connect(":memory:", check_same_thread=False)
    _sqlite_schema_template(Base.metadata).backup(raw)
    engine = create_engine("sqlite:///:memory:", creator=lambda: raw, poolclass=StaticPool)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        raw.close()


def test_the_result_matches_the_import_from_file_button(db, seeded, db2):
    from starlette.datastructures import UploadFile

    from app.modules.super_admin import router as sa_router
    from scripts.seed_belgium_canonical_packs import seed_belgium

    ui_pack = seed_belgium(db2)["pack"]
    db2.commit()
    src, ui_src = _verified_source(db), _verified_source(db2)
    assert (seeded.id, src.id) == (ui_pack.id, ui_src.id)       # identical starting points
    data = _csv([_scalar_row(db, seeded, str(src.id))])

    out = _run(db, seeded, data, apply=True)                    # the script
    reason = f"Verified values loaded from verified.csv ({_seed_script().SCRIPT_NAME})"
    ui = asyncio.run(sa_router.belgium_content_workbook_import(  # the button's route, same file and reason
        ui_pack.id, file=UploadFile(io.BytesIO(data), filename="verified.csv"), reason=reason, dry_run=False,
        current_user=SimpleNamespace(id=IMPORTER), db=db2))
    assert out["applied"] is True and ui["written"] is True and out["changes"] == ui["changes"]
    db.expire_all()
    db2.expire_all()
    assert _pack_state(db, seeded) == _pack_state(db2, ui_pack)


def test_cli_dry_run_is_the_default_and_apply_is_explicit(tmp_path, capsys):
    script = _seed_script()
    # No database is opened: a missing file stops first.
    assert script.main(["--pack", "BE-X", "--file", str(tmp_path / "none.csv"), "--actor-id", "1"]) == 1
    with pytest.raises(SystemExit):                              # --dry-run and --apply are exclusive
        script.main(["--pack", "BE-X", "--file", "f.csv", "--actor-id", "1", "--dry-run", "--apply"])
    with pytest.raises(SystemExit):                              # --actor-id is required
        script.main(["--pack", "BE-X", "--file", "f.csv"])

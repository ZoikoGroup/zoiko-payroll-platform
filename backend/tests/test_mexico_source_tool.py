"""Mexico Phase 1 evidence tool (scripts/verify_mexico_sources.py) — manifest
hashing, status rules and the row-by-row number comparison, exercised on
SYNTHETIC files in a temp directory (never on statutory content)."""

from decimal import Decimal

import pytest


def _tool():
    from scripts import verify_mexico_sources as v

    return v


def test_hash_adds_new_files_unverified_and_detects_changes(tmp_path, capsys):
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    (tmp_path / "S2_test.txt").write_text("SYNTHETIC " * 50, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    rows = v.cmd_hash(tmp_path, manifest)
    assert [(r["code"], r["status"], r["text_layer"]) for r in rows] == [("S2", "UNVERIFIED", "yes")]
    assert rows[0]["url"] == v.DEFAULT_URLS["S2"] and len(rows[0]["sha256"]) == 64
    v.cmd_set("S2", ["title=T", "issuer=I", "header_version=H", "status=VERIFIED"], manifest)
    assert v.read_manifest(manifest)[0]["status"] == "VERIFIED"
    (tmp_path / "S2_test.txt").write_text("CHANGED " * 50, encoding="utf-8")
    v.cmd_hash(tmp_path, manifest)
    assert v.read_manifest(manifest)[0]["status"] == "UNVERIFIED"         # a changed file must be re-verified
    assert "CHANGED" in capsys.readouterr().out


def test_verified_needs_metadata_and_a_text_layer(tmp_path):
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    (tmp_path / "S6_short.txt").write_text("x", encoding="utf-8")
    v.cmd_hash(tmp_path, manifest)
    with pytest.raises(SystemExit, match="title"):
        v.cmd_set("S6", ["status=VERIFIED"], manifest)
    with pytest.raises(SystemExit, match="text layer"):
        v.cmd_set("S6", ["title=T", "issuer=I", "header_version=H", "status=VERIFIED"], manifest)
    with pytest.raises(SystemExit, match="status must be"):
        v.cmd_set("S6", ["status=OK"], manifest)
    with pytest.raises(SystemExit, match="not editable"):
        v.cmd_set("S6", ["sha256=0"], manifest)


def test_check_reports_missing_and_altered_files(tmp_path):
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    path = tmp_path / "S9_test.txt"
    path.write_text("SYNTHETIC " * 50, encoding="utf-8")
    v.cmd_hash(tmp_path, manifest)
    assert v.cmd_check(manifest, tmp_path) == []
    path.write_text("ALTERED " * 50, encoding="utf-8")
    assert any("SHA-256" in p for p in v.cmd_check(manifest, tmp_path))
    path.unlink()
    assert any("missing" in p for p in v.cmd_check(manifest, tmp_path))


def test_numbers_are_normalised_from_mexican_formatting():
    v = _tool()
    assert v.numbers_in("$ 1,234.56 y 7.5% del 2026") == [Decimal("1234.56"), Decimal("7.5"), Decimal("2026")]


def test_compare_is_runnable_on_empty_content(tmp_path, capsys):
    v = _tool()
    assert v.cmd_compare(tmp_path / "SOURCES_MANIFEST.csv", tmp_path) == []
    assert "0 content rows checked" in capsys.readouterr().out


def test_compare_finds_isr_rows_on_one_line_and_reports_misses(tmp_path, monkeypatch):
    """SYNTHETIC tariff text: the four numbers of a bracket must sit on ONE line."""
    v = _tool()
    from app.modules.payroll.engine.countries import mexico_content as c

    src = tmp_path / "S2_synthetic.txt"
    src.write_text("Tarifa SINTETICA\n" + "header line " * 30 + "\n0.01 100.00 0.00 10.00\n100.01 200.00\n10.00 20.00\n",
                   encoding="utf-8")
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    v.cmd_hash(tmp_path, manifest)
    v.cmd_set("S2", ["title=T", "issuer=I", "header_version=H", "status=VERIFIED"], manifest)
    ok = c.IsrBracket("MONTHLY", "0.01", "100.00", "0.00", "10.00", None, None, "S2", "SYNTHETIC")
    split = c.IsrBracket("MONTHLY", "100.01", "200.00", "10.00", "20.00", None, None, "S2", "SYNTHETIC")
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", (ok,))
    assert v.cmd_compare(manifest, tmp_path) == []
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", (ok, split))
    misses = v.cmd_compare(manifest, tmp_path)
    assert len(misses) == 1 and "on one line" in misses[0]
    unverified = c.IsrBracket("MONTHLY", "0.01", None, "0.00", "10.00", None, None, "S7", "SYNTHETIC")
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", (unverified,))
    assert "no VERIFIED file" in v.cmd_compare(manifest, tmp_path)[0]

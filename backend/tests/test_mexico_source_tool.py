"""Mexico Phase 1 evidence tool (scripts/verify_mexico_sources.py) — manifest
hashing, status rules and the row-by-row number comparison, exercised on
SYNTHETIC files in a temp directory (never on statutory content)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest


def _tool():
    from scripts import verify_mexico_sources as v

    return v


def _fetch_file(path):
    """A SYNTHETIC direct download returning the saved file's bytes."""
    return lambda url: (url, path.read_bytes())


def test_hash_adds_new_files_unverified_and_detects_changes(tmp_path, capsys):
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    (tmp_path / "S2_test.txt").write_text("SYNTHETIC " * 50, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    rows = v.cmd_hash(tmp_path, manifest)
    assert [(r["code"], r["status"], r["text_layer"]) for r in rows] == [("S2", "UNVERIFIED", "yes")]
    assert rows[0]["url"] == v.DEFAULT_URLS["S2"] and len(rows[0]["sha256"]) == 64
    v.cmd_set("S2", ["title=T", "issuer=I", "header_version=H"], manifest)
    v.cmd_verify("S2", "test@example.com", manifest_path=manifest, sources_dir=tmp_path,
                 fetch=_fetch_file(tmp_path / "S2_test.txt"))
    assert v.read_manifest(manifest)[0]["status"] == "VERIFIED"
    before = manifest.read_bytes()
    (tmp_path / "S2_test.txt").write_text("CHANGED " * 50, encoding="utf-8")
    with pytest.raises(SystemExit, match="CHANGED S2_test.txt"):          # a changed file is refused
        v.cmd_hash(tmp_path, manifest)
    assert manifest.read_bytes() == before                                # and nothing is written


def test_hash_never_overwrites_an_existing_row(tmp_path):
    """Phase 11d: curated fields (content type, text layer, retrieval time,
    notes) survive a re-hash; only blank fields are filled and new files added."""
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    (tmp_path / "S28_test.xsd").write_text("<xs:schema/>" + " " * 300, encoding="utf-8")
    v.cmd_hash(tmp_path, manifest)
    v.cmd_set("S28", ["title=T", "note=curated", "status=ARCHIVE_COPY_VERIFIED"], manifest)
    rows = v.read_manifest(manifest)
    rows[0].update(content_type="text/xml", text_layer="n/a", retrieved_at="2026-10-23T05:42:57Z", bytes="")
    v.write_manifest(rows, manifest)
    curated = dict(v.read_manifest(manifest)[0])
    (tmp_path / "S6_new.txt").write_text("SYNTHETIC " * 50, encoding="utf-8")
    after = {r["file"]: r for r in v.cmd_hash(tmp_path, manifest)}
    kept = after["S28_test.xsd"]
    assert {k: kept[k] for k in kept if k != "bytes"} == {k: curated[k] for k in curated if k != "bytes"}
    assert kept["bytes"] == str((tmp_path / "S28_test.xsd").stat().st_size)    # a blank field is filled
    assert after["S6_new.txt"]["status"] == "UNVERIFIED"                      # a new file is added


def test_verified_needs_metadata_and_a_text_layer(tmp_path):
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    (tmp_path / "S6_short.txt").write_text("x", encoding="utf-8")
    v.cmd_hash(tmp_path, manifest)
    fetch = _fetch_file(tmp_path / "S6_short.txt")
    with pytest.raises(SystemExit, match="title"):
        v.cmd_verify("S6", "test@example.com", manifest_path=manifest, sources_dir=tmp_path, fetch=fetch)
    v.cmd_set("S6", ["title=T", "issuer=I", "header_version=H"], manifest)
    with pytest.raises(SystemExit, match="text layer"):
        v.cmd_verify("S6", "test@example.com", manifest_path=manifest, sources_dir=tmp_path, fetch=fetch)
    with pytest.raises(SystemExit, match="only by `verify`"):
        v.cmd_set("S6", ["status=VERIFIED"], manifest)
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
    # INEGI's space-separated thousands are also read as one amount (Batch 1)
    assert Decimal("3566.22") in v.numbers_in("2026 117.31 3 566.22 42 794.64")
    assert Decimal("42794.64") in v.numbers_in("2026 117.31 3 566.22 42 794.64")


def _empty_content(monkeypatch):
    """These tests run the comparison on SYNTHETIC content only — never on the
    transcribed tables (Batch 1 onward the real tables are not empty)."""
    from app.modules.payroll.engine.countries import mexico_content as c

    for table in ("MX_SCALAR_CONTENT", "MX_ISR_TARIFFS", "MX_MIN_WAGES", "MX_CEAV_SCHEDULE", "MX_WORKWEEK",
                  "MX_VACATION_DAYS", "MX_ZLFN_MUNICIPALITIES"):
        monkeypatch.setattr(c, table, ())
    monkeypatch.setattr(c, "MX_ISN_CONTENT", {state: () for state in c.MX_ISN_CONTENT})
    for table in ("MX_SPECIAL_PAY_ISN_INCLUSION", "MX_SPECIAL_PAY_RULES", "MX_TERMINATION_REASONS",
                  "MX_PTU_EXCLUSION_REASONS", "MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS", "MX_OFFICIAL_HOLIDAYS",
                  "MX_ORDINARY_EXEMPTION_RULES", "MX_JORNADA_DAILY_HOURS"):
        monkeypatch.setattr(c, table, {})
    for rule in ("MX_AGUINALDO_RULE", "MX_FINIQUITO_RULE", "MX_PTU_RULE", "MX_ANNUAL_ADJUSTMENT_RULE",
                 "MX_RISK_PREMIUM_PERIOD", "MX_IMSS_MOVEMENT_DEADLINE", "MX_CONTRIBUTION_DAYS_RULE"):
        monkeypatch.setattr(c, rule, None)
    monkeypatch.setattr(c, "MX_FILING_CALENDAR", ())
    monkeypatch.setattr(c, "MX_ISR_ANNUAL_TARIFFS", {})                  # W1-4
    return c


def test_compare_is_runnable_on_empty_content(tmp_path, capsys, monkeypatch):
    v = _tool()
    _empty_content(monkeypatch)
    assert v.cmd_compare(tmp_path / "SOURCES_MANIFEST.csv", tmp_path) == []
    assert "0 content rows checked" in capsys.readouterr().out


def test_compare_finds_isr_rows_on_one_line_and_reports_misses(tmp_path, monkeypatch):
    """SYNTHETIC tariff text: the four numbers of a bracket must sit on ONE line."""
    v = _tool()
    c = _empty_content(monkeypatch)

    src = tmp_path / "S2_synthetic.txt"
    src.write_text("Tarifa SINTETICA\n" + "header line " * 30 + "\n0.01 100.00 0.00 10.00\n100.01 200.00\n10.00 20.00\n",
                   encoding="utf-8")
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    v.cmd_hash(tmp_path, manifest)
    v.cmd_set("S2", ["title=T", "issuer=I", "header_version=H"], manifest)
    v.cmd_verify("S2", "test@example.com", manifest_path=manifest, sources_dir=tmp_path, fetch=_fetch_file(src))
    ok = c.IsrBracket("MONTHLY", "0.01", "100.00", "0.00", "10.00", None, None, "S2", "SYNTHETIC")
    split = c.IsrBracket("MONTHLY", "100.01", "200.00", "10.00", "20.00", None, None, "S2", "SYNTHETIC")
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", (ok,))
    assert v.cmd_compare(manifest, tmp_path) == []
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", (ok, split))
    misses = v.cmd_compare(manifest, tmp_path)
    assert len(misses) == 1 and "on one line" in misses[0]
    unverified = c.IsrBracket("MONTHLY", "0.01", None, "0.00", "10.00", None, None, "S7", "SYNTHETIC")
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", (unverified,))
    assert "no usable" in v.cmd_compare(manifest, tmp_path)[0]


def test_compare_checks_the_wording_a_text_rule_quotes(tmp_path, monkeypatch):
    """W1-1: a text rule has no number, so the wording its citation quotes must
    be in the cited file — accents and line breaks aside. SYNTHETIC text."""
    v = _tool()
    c = _empty_content(monkeypatch)
    src = tmp_path / "S10_synthetic.txt"
    src.write_text("Ley SINTETICA\n" + "relleno " * 40 + "\ncomo límite inferior el salario\nmínimo de la zona\n",
                   encoding="utf-8")
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    v.cmd_hash(tmp_path, manifest)
    v.cmd_set("S10", ["status=ARCHIVE_COPY_VERIFIED"], manifest)
    row = c.ScalarRow("mx_sbc_min_rule", None, None, None, "RAISE_TO_ZONE_MIN_WAGE", None, None, "S10",
                      "Art. X: 'como limite inferior el salario minimo de la zona', SYNTHETIC")
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (row,))
    assert v.cmd_compare(manifest, tmp_path) == []
    misquoted = row._replace(source_ref="Art. X: 'como limite superior el salario minimo de la zona'")
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (misquoted,))
    misses = v.cmd_compare(manifest, tmp_path)
    assert len(misses) == 1 and "quote" in misses[0] and "not found" in misses[0]
    assert v._quotes("a 'short' b 'long enough quote here', c") == ["long enough quote here"]


def test_compare_requires_every_module_direct_rule_to_quote_its_wording(tmp_path, monkeypatch):
    """W1-2: an ISN inclusion / special-pay / termination rule has no table row,
    so its citation must quote the source wording, and the quote must be found."""
    v = _tool()
    c = _empty_content(monkeypatch)
    src = tmp_path / "S22_synthetic.txt"
    src.write_text("Codigo SINTETICO\n" + "relleno " * 40 + "\nV. Gratificaciones y aguinaldos;\n", encoding="utf-8")
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    v.cmd_hash(tmp_path, manifest)
    v.cmd_set("S22", ["status=ARCHIVE_COPY_VERIFIED"], manifest)
    quoted = {("CDMX", "AGUINALDO"): (True, "S22", "Art. X V: 'Gratificaciones y aguinaldos', SYNTHETIC")}
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", quoted)
    assert v.cmd_compare(manifest, tmp_path) == []
    unquoted = {("CDMX", "AGUINALDO"): (True, "S22", "Art. X V, SYNTHETIC")}
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", unquoted)
    misses = v.cmd_compare(manifest, tmp_path)
    assert len(misses) == 1 and "quotes no wording" in misses[0]
    rule = SimpleNamespace(source="S22", source_ref="x", citations=(("S22", "Art. Y: 'Gratificaciones y aguinaldos'"),
                                                                    ("S22", "Art. Z: 'texto que no existe aqui'")))
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", {})
    monkeypatch.setattr(c, "MX_AGUINALDO_RULE", rule)
    misses = v.cmd_compare(manifest, tmp_path)
    assert len(misses) == 1 and "texto que no existe" in misses[0]


# -- Phase 11d: VERIFIED only through a logged direct download --

def _ready(tmp_path, url=None):
    v = _tool()
    manifest = tmp_path / "SOURCES_MANIFEST.csv"
    (tmp_path / "S2_test.txt").write_text("SYNTHETIC " * 50, encoding="utf-8")
    v.cmd_hash(tmp_path, manifest)
    v.cmd_set("S2", ["title=T", "issuer=I", "header_version=H"] + ([f"url={url}"] if url else []), manifest)
    return v, manifest


def _log(tmp_path):
    import csv

    with open(tmp_path / "VERIFICATION_LOG.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_verify_logs_the_download_and_sets_verified_on_a_match(tmp_path):
    from datetime import datetime, timezone

    v, manifest = _ready(tmp_path)
    body = (tmp_path / "S2_test.txt").read_bytes()
    row = v.cmd_verify("S2", "ops@example.com", manifest_path=manifest, sources_dir=tmp_path,
                       fetch=lambda url: (url, body), now=datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc))
    assert row["status"] == "VERIFIED"
    [entry] = _log(tmp_path)
    assert entry == {"code": "S2", "file": "S2_test.txt", "url": v.DEFAULT_URLS["S2"], "final_url": v.DEFAULT_URLS["S2"],
                     "downloaded_at": "2026-10-26T09:30:00Z", "downloader": "ops@example.com",
                     "response_bytes": str(len(body)), "sha256": row["sha256"], "result": "MATCH"}
    from app.modules.payroll import mexico_sources

    assert mexico_sources.verified_artifact(v.read_manifest(manifest), row["url"], row["sha256"],
                                            mexico_sources.read_log(manifest))


def test_verify_refuses_a_hash_mismatch_and_logs_it(tmp_path):
    v, manifest = _ready(tmp_path)
    with pytest.raises(SystemExit, match="not VERIFIED"):
        v.cmd_verify("S2", "ops@example.com", manifest_path=manifest, sources_dir=tmp_path,
                     fetch=lambda url: (url, b"a different document"))
    assert v.read_manifest(manifest)[0]["status"] == "UNVERIFIED"
    assert [e["result"] for e in _log(tmp_path)] == ["MISMATCH"]


def test_verify_never_uses_an_archive_capture(tmp_path):
    body_of = _fetch_file(tmp_path / "S2_test.txt")
    v, manifest = _ready(tmp_path, url="https://web.archive.org/web/2026id_/https://www.sat.gob.mx/x.pdf")
    with pytest.raises(SystemExit, match="not an archive capture"):
        v.cmd_verify("S2", "ops@example.com", manifest_path=manifest, sources_dir=tmp_path, fetch=body_of)
    v.cmd_set("S2", ["url=https://www.sat.gob.mx/x.pdf"], manifest)
    redirected = lambda url: ("https://web.archive.org/web/2026/" + url, (tmp_path / "S2_test.txt").read_bytes())
    with pytest.raises(SystemExit, match="redirected to an archive host"):
        v.cmd_verify("S2", "ops@example.com", manifest_path=manifest, sources_dir=tmp_path, fetch=redirected)
    with pytest.raises(SystemExit, match="downloader"):
        v.cmd_verify("S2", " ", manifest_path=manifest, sources_dir=tmp_path, fetch=body_of)
    assert v.read_manifest(manifest)[0]["status"] == "UNVERIFIED"


def test_verify_refuses_when_the_saved_copy_changed(tmp_path):
    v, manifest = _ready(tmp_path)
    (tmp_path / "S2_test.txt").write_text("EDITED " * 50, encoding="utf-8")
    with pytest.raises(SystemExit, match="run `hash` first"):
        v.cmd_verify("S2", "ops@example.com", manifest_path=manifest, sources_dir=tmp_path,
                     fetch=_fetch_file(tmp_path / "S2_test.txt"))


def test_spanish_number_words_are_read_as_numbers():
    """Batch 2: the LSS / LFT write rates in words."""
    v = _tool()
    cases = {"uno punto cero cinco por ciento": [Decimal("1.05")],
             "cero punto trescientos setenta y cinco por ciento": [Decimal("0.375")],
             "uno punto ciento veinticinco por ciento": [Decimal("1.125")],
             "cero punto cinco por ciento y quince por ciento": [Decimal("0.5"), Decimal("15")],
             "sesenta y cinco centésimas de punto porcentual": [Decimal("0.65")],
             "veinticinco veces el salario mínimo": [Decimal("25")],
             "un cien por ciento más": [Decimal("1"), Decimal("100")]}
    for text, expected in cases.items():
        assert v.word_numbers(text) == expected, text


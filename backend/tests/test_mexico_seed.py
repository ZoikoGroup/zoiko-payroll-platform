"""Mexico (ZP-MX-ENG-001) Phase 1 seed and governance — Draft-only packs,
guard refusals, evidence linkage, idempotence, activation still refused,
canonical-only reads, the generic-tax-path spy and the validation-switch
blast radius. In-memory SQLite (conftest `db`).

Every row these tests build is SYNTHETIC test data (values such as 1 and 2),
never a statutory figure. `app.*` / `scripts.*` are imported lazily."""

import ast
import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _seed_module():
    from scripts import seed_mexico_canonical_packs as seed

    return seed


@pytest.fixture(autouse=True)
def _synthetic_content_only(monkeypatch):
    """These tests exercise the seed on SYNTHETIC rows. Since Batch 1
    (2026-10-26) the real ISR / scalar tables are not empty, so every test here
    starts from empty tables and sets only the rows it needs. Seeding the real
    content is tested in test_mexico_activation_gates (today's real packs)."""
    c = _content()
    for table in ("MX_SCALAR_CONTENT", "MX_ISR_TARIFFS", "MX_MIN_WAGES", "MX_ZLFN_MUNICIPALITIES", "MX_CEAV_SCHEDULE",
                  "MX_WORKWEEK", "MX_VACATION_DAYS"):
        monkeypatch.setattr(c, table, ())
    monkeypatch.setattr(c, "MX_ISN_CONTENT", {state: () for state in c.MX_ISN_CONTENT})   # W1-2 filled CDMX


def _content():
    from app.modules.payroll.engine.countries import mexico_content

    return mexico_content


def _models():
    from app.modules.payroll import models

    return models


def _counts(db):
    m = _models()
    out = {}
    for pack in db.query(m.JurisdictionPack).filter(m.JurisdictionPack.jurisdiction_country == "MX").all():
        out[pack.pack_id] = (
            db.query(m.ContributionRate).filter(m.ContributionRate.jurisdiction_pack_id == pack.id).count(),
            db.query(m.TaxSlab).filter(m.TaxSlab.jurisdiction_pack_id == pack.id).count(),
        )
    out["_artifacts"] = db.query(m.SourceArtifact).count()
    out["_readiness"] = db.query(m.StateLocalProgramReadiness).filter(
        m.StateLocalProgramReadiness.jurisdiction_country == "MX").count()
    return out


def _manifest_row(code, sha, status="VERIFIED"):
    return {"code": code, "title": f"SYNTHETIC {code}", "issuer": "Test issuer", "url": f"https://example.test/{code}",
            "file": f"{code}_synthetic.pdf", "sha256": sha, "bytes": "10", "retrieved_at": "2026-10-15T00:00:00Z",
            "content_type": "application/pdf", "header_version": "test", "text_layer": "yes", "status": status,
            "note": ""}


def _scalar(key, value, eff_from=None, eff_to=None, source="S6", pending_g2=False, text=None):
    c = _content()
    return c.ScalarRow(key, None, None, value, text, eff_from, eff_to, source, "SYNTHETIC TEST ROW",
                       pending_g2=pending_g2)


# ── seeding on today's (empty) content ──────────────────────────────────────

def test_seed_creates_draft_national_and_cdmx_isn_packs_with_no_rows(db):
    m, seed = _models(), _seed_module()
    out = seed.seed_mexico(db, manifest={})
    db.flush()
    national, cdmx = out["national"], out["isn"]["CDMX"]
    assert (national.pack_id, national.status, national.jurisdiction_state) == ("MX-PAYROLL-2026", "Draft", None)
    assert (cdmx.pack_id, cdmx.status, cdmx.jurisdiction_state) == ("MX-ISN-CDMX-2026", "Draft", "CDMX")
    assert cdmx.parent_pack_id == national.id
    assert (str(national.effective_from), str(national.effective_to), national.currency) == ("2026-01-01", "2026-12-31", "MXN")
    assert _counts(db)["MX-PAYROLL-2026"] == (0, 0) and _counts(db)["MX-ISN-CDMX-2026"] == (0, 0)
    assert db.query(m.SourceArtifact).count() == 0
    audits = db.query(m.TaxConfigurationAudit).filter(m.TaxConfigurationAudit.action == "seed").all()
    assert {a.entity_id for a in audits} == {national.id, cdmx.id}


def test_seed_creates_registry_and_isn_readiness_rows_once(db):
    from app.modules.billing.models import JurisdictionServiceRegistry

    m, seed = _models(), _seed_module()
    seed.seed_mexico(db, manifest={})
    seed.seed_mexico(db, manifest={})
    db.flush()
    reg = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "MX").all()
    assert len(reg) == 1 and reg[0].availability == "PLANNED"
    assert reg[0].payment_execution_responsibility == reg[0].filing_responsibility == "NOT_OFFERED"
    ready = db.query(m.StateLocalProgramReadiness).filter(m.StateLocalProgramReadiness.jurisdiction_country == "MX").all()
    assert [(r.jurisdiction_state, r.program, r.legal_status) for r in ready] == [
        ("CDMX", "OTHER_STATE_PAYROLL", "SOURCE_REQUIRED")]          # Phase 0 decision 6


def test_seed_is_idempotent_on_rerun(db):
    seed = _seed_module()
    seed.seed_mexico(db, manifest={})
    db.flush()
    first = _counts(db)
    seed.seed_mexico(db, manifest={})
    db.flush()
    assert _counts(db) == first


@pytest.mark.parametrize("pack_id", ["MX-PAYROLL-2026", "MX-ISN-CDMX-2026"])
def test_seed_refuses_to_rewrite_a_pack_that_left_draft(db, pack_id):
    m, seed = _models(), _seed_module()
    seed.seed_mexico(db, manifest={})
    db.flush()
    pack = db.query(m.JurisdictionPack).filter(m.JurisdictionPack.pack_id == pack_id).one()
    pack.status = "In Review"
    db.flush()
    with pytest.raises(SystemExit):
        seed.seed_mexico(db, manifest={})


# ── evidence linkage (synthetic rows, synthetic manifest) ───────────────────

def test_a_row_citing_an_unverified_source_refuses_the_seed(db, monkeypatch):
    c, seed = _content(), _seed_module()
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_uma_daily", "1"),))
    with pytest.raises(SystemExit, match="S6"):
        seed.seed_mexico(db, manifest={})
    with pytest.raises(SystemExit, match="S6"):
        seed.seed_mexico(db, manifest=seed.load_manifest(Path("does-not-exist.csv")))


def test_rows_link_a_url_and_hash_artifact_and_carry_the_g1_marker(db, monkeypatch):
    m, c, seed = _models(), _content(), _seed_module()
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_uma_daily", "1", date(2026, 1, 1), date(2026, 1, 31)),))
    manifest = {"S6": _manifest_row("S6", "a" * 64)}
    seed.seed_mexico(db, manifest=manifest)
    db.flush()
    row = db.query(m.ContributionRate).filter(m.ContributionRate.jurisdiction_country == "MX").one()
    art = db.get(m.SourceArtifact, row.source_document_id)
    assert (art.source_url, art.checksum_sha256, art.file_path) == (
        "https://example.test/S6", "a" * 64, "docs/mexico/sources/S6_synthetic.pdf")
    assert row.label.endswith(c.PENDING_G1) and (str(row.effective_from), str(row.effective_to)) == ("2026-01-01", "2026-01-31")
    seed.seed_mexico(db, manifest=manifest)                         # same file -> same artifact
    db.flush()
    assert db.query(m.SourceArtifact).count() == 1
    seed.seed_mexico(db, manifest={"S6": _manifest_row("S6", "b" * 64)})   # changed file -> NEW artifact
    db.flush()
    assert db.query(m.SourceArtifact).count() == 2


def test_only_verified_manifest_rows_are_usable(tmp_path):
    seed = _seed_module()
    path = tmp_path / "SOURCES_MANIFEST.csv"
    rows = [_manifest_row("S2", "a" * 64), _manifest_row("S22", "b" * 64, status="WRONG_VERSION"),
            _manifest_row("S6", "c" * 64, status="UNVERIFIED")]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    # Phase 11d: a VERIFIED row counts only with its verification-log entry.
    assert set(seed.load_manifest(path)) == set()
    _write_log(path, rows)
    # Draft packs accept VERIFIED and ARCHIVE_COPY_VERIFIED; each file is
    # keyed CODE/file, and a single-file code by its bare code too.
    assert set(seed.load_manifest(path)) == {"S2", "S2/S2_synthetic.pdf"}


def test_catalog_drift_scope_and_g2_flag_are_refused(db, monkeypatch):
    c, seed = _content(), _seed_module()
    manifest = {"S6": _manifest_row("S6", "a" * 64), "S22": _manifest_row("S22", "d" * 64)}
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_not_a_key", "1"),))
    with pytest.raises(SystemExit, match="MX_PARAMETER_KEYS"):
        seed.seed_mexico(db, manifest=manifest)
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_isn_rate_pct", "1"),))     # state key in national pack
    with pytest.raises(SystemExit, match="state"):
        seed.seed_mexico(db, manifest=manifest)
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_ceav_lowest_band_min_wage_ref", None, text="X"),))
    with pytest.raises(SystemExit, match="pending_g2"):                                  # must carry the G2 flag
        seed.seed_mexico(db, manifest=manifest)


def test_only_the_seeded_ceav_year_enters_the_2026_pack(db, monkeypatch):
    m, c, seed = _models(), _content(), _seed_module()
    rows = tuple(c.CeavBand(y, "1", "UMA", None, None, "1", date(y, 1, 1), date(y, 12, 31), "S11", "SYNTHETIC")
                 for y in (2025, 2026, 2027))
    monkeypatch.setattr(c, "MX_CEAV_SCHEDULE", rows)
    seed.seed_mexico(db, manifest={"S11": _manifest_row("S11", "e" * 64)})
    db.flush()
    slabs = db.query(m.TaxSlab).filter(m.TaxSlab.rule_type == c.MX_CEAV_BAND_RULE).all()
    assert [s.tax_table_number for s in slabs] == ["2026"]


# ── the confirmation guard ──────────────────────────────────────────────────

class _Stdin(io.StringIO):
    def __init__(self, text, tty):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.mark.parametrize("env, tty, typed", [
    (None, True, "CONFIRM\n"),              # no override -> refused even for SQLite
    ("I_UNDERSTAND", False, "CONFIRM\n"),   # non-interactive -> refused
    ("I_UNDERSTAND", True, "yes\n"),        # not confirmed -> refused
])
def test_guard_refuses_without_override_terminal_and_confirmation(monkeypatch, env, tty, typed):
    seed = _seed_module()
    if env is None:
        monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    else:
        monkeypatch.setenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", env)
    monkeypatch.setattr("sys.stdin", _Stdin(typed, tty))
    with pytest.raises(SystemExit) as exc:
        seed._require_confirmed_target()
    assert exc.value.code == 2


def test_guard_passes_only_with_override_terminal_and_confirm(monkeypatch):
    seed = _seed_module()
    monkeypatch.setenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", "I_UNDERSTAND")
    monkeypatch.setattr("sys.stdin", _Stdin("CONFIRM\n", True))
    assert seed._require_confirmed_target() is None


# ── activation: still refused, and never set by production code ────────────

def test_governed_activation_of_a_seeded_pack_is_refused(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    m, seed = _models(), _seed_module()
    out = seed.seed_mexico(db, manifest={})
    db.commit()
    for pack in (out["national"], out["isn"]["CDMX"]):
        # Phase 2: MX is on the transition graph, so Draft -> Active is refused
        # before any Mexico gate runs (tests/test_mexico_activation_gates.py
        # covers each Mexico gate on an Approved pack).
        with pytest.raises(BadRequestException):
            service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=1)
        assert db.get(m.JurisdictionPack, pack.id).status == "Draft"


_PRODUCTION_FILES = (
    "app/modules/payroll/mexico_service.py", "app/modules/payroll/mexico_router.py",
    "app/modules/payroll/mexico_schemas.py", "app/modules/payroll/engine/countries/mexico.py",
    "app/modules/payroll/engine/countries/mexico_content.py", "scripts/seed_mexico_canonical_packs.py",
    "scripts/verify_mexico_sources.py",
)


def _is_active(node):
    return isinstance(node, ast.Constant) and node.value == "Active"


def test_no_production_mexico_code_sets_a_status_to_active():
    """No Mexico production code ever WRITES "Active": no `….status = "Active"`
    assignment, no `status="Active"` keyword, and no status-setting call given
    "Active". (Reading a status — `== "Active"` — is fine; so is the CFDI
    release state map, whose activate step is refused in Phase 2.)"""
    for rel in _PRODUCTION_FILES:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _is_active(node.value) and any(
                    isinstance(t, ast.Attribute) and t.attr == "status" for t in node.targets):
                pytest.fail(f"{rel}:{node.lineno} assigns status = 'Active'")
            if isinstance(node, ast.keyword) and node.arg == "status" and _is_active(node.value):
                pytest.fail(f"{rel}:{node.value.lineno} passes status='Active'")
            if isinstance(node, ast.Call) and any(_is_active(a) for a in node.args):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if "status" in name.lower():
                    pytest.fail(f"{rel}:{node.lineno} calls {name}(…, 'Active')")


# ── test-only Active pack (fixture-inserted, never via a service function) ──

@pytest.fixture()
def synthetic_active_mx_pack(db):
    """A test-only Active MX pack inserted directly with the ORM. Every row is
    SYNTHETIC; the UMA row has a January (1) and a February (2) version."""
    m, c = _models(), _content()
    pack = m.JurisdictionPack(pack_id="MX-TEST-ACTIVE", jurisdiction_country="MX", version="1.0", pack_type="tax",
                              status="Active", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
                              tax_year="2026", currency="MXN")
    db.add(pack)
    db.flush()
    order = 0
    for key, (kind, label, scope) in c.MX_PARAMETER_KEYS.items():
        if scope != "national":
            continue
        windows = ([(date(2026, 1, 1), date(2026, 1, 31), "1"), (date(2026, 2, 1), date(2026, 12, 31), "2")]
                   if key == "mx_uma_daily" else [(None, None, "1")])
        for eff_from, eff_to, value in windows:
            order += 1
            num = Decimal(value)
            db.add(m.ContributionRate(
                jurisdiction_pack_id=pack.id, jurisdiction_country="MX", organization_id=None, component_key=key,
                label=f"SYNTHETIC {key}", employee_share="—", employer_share="—", total="—",
                employee_rate_pct=num if kind == "employee_pct" else None,
                employer_rate_pct=num if kind == "employer_pct" else None,
                flat_amount=num if kind == "amount" else None, text_value="SYNTHETIC" if kind == "text" else None,
                effective_from=eff_from, effective_to=eff_to, sort_order=order))
    db.add(m.TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", organization_id=None,
                     rule_type=c.MX_ISR_TARIFF_RULE, filing_status="MONTHLY", min_amount=Decimal("0.01"),
                     max_amount=None, rate_pct=Decimal("1"), flat_amount=Decimal("0"),
                     rate_label="SYNTHETIC", tax_formula="SYNTHETIC", sort_order=1))
    db.commit()
    return pack


def test_rows_are_selected_by_pay_date_through_the_real_resolver(db, synthetic_active_mx_pack):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    def uma(on):
        rates, _slabs, pack = resolve_tax_configuration(db, "MX", payroll_date=on)
        assert pack.id == synthetic_active_mx_pack.id
        return [r.flat_amount for r in rates if r.component_key == "mx_uma_daily"]

    assert uma(date(2026, 1, 31)) == [Decimal("1")]
    assert uma(date(2026, 2, 1)) == [Decimal("2")]


def test_mexico_reads_canonical_rows_only_never_org_copies(db, organization, synthetic_active_mx_pack):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    m = _models()
    db.add(m.ContributionRate(                       # an org-scoped copy with a deliberately wrong value
        jurisdiction_country="MX", organization_id=organization.id, component_key="mx_uma_daily",
        label="SYNTHETIC org copy", employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("999"), sort_order=1))
    db.commit()
    for opted_in in (False, True):
        rate_map, _slabs, _rows, pack = service._resolve_effective_rate_inputs(
            db, organization.id, "MX", date(2026, 1, 15), org_opted_in=opted_in)
        assert pack.id == synthetic_active_mx_pack.id
        assert rate_map["mx_uma_daily"].flat_amount == Decimal("1")
        assert rate_map["mx_uma_daily"].organization_id is None
    with pytest.raises(BadRequestException, match="cannot be applied from an extracted document"):
        service.apply_extracted_rate(db, organization.id, "contributionRate",
                                     {"label": "UMA", "rate": "1"}, country_code="MX")


def test_an_mx_pack_missing_a_required_key_fails_readiness(db, organization, synthetic_active_mx_pack):
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    m = _models()
    db.query(m.ContributionRate).filter(m.ContributionRate.component_key == "mx_imss_iv_er_pct").delete()
    db.commit()
    with pytest.raises(MissingComplianceConfigurationError):
        service._resolve_effective_rate_inputs(db, organization.id, "MX", date(2026, 3, 1), org_opted_in=False)


# ── generic progressive-tax path never sees MX slabs ───────────────────────

def test_mx_slabs_never_reach_the_generic_progressive_tax_path(monkeypatch):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries import generic, shared
    from app.modules.payroll.engine.countries.mexico import MexicoCalculationBlockedError
    from app.modules.payroll.engine.resolver import calculate_payroll

    calls = []

    def spy(annual_income, slabs, *args, **kwargs):
        calls.append([getattr(s, "rule_type", None) for s in slabs])
        return Decimal("0")

    monkeypatch.setattr(shared, "_calculate_annual_tax", spy)
    monkeypatch.setattr(generic, "_calculate_annual_tax", spy)
    slabs = [SimpleNamespace(rule_type=r, min_amount=Decimal("0.01"), max_amount=None, rate_pct=Decimal("1"),
                             flat_amount=Decimal("0"), filing_status="MONTHLY", jurisdiction_state=None)
             for r in _content().MX_SLAB_RULES]

    def ctx(country):
        return PayrollContext(gross=Decimal("20000"), basic=Decimal("20000"), country=country, slabs=list(slabs))

    for mode in ("standard", "enterprise"):
        with pytest.raises(MexicoCalculationBlockedError):
            calculate_payroll(ctx("MX"), mode)
    assert calls == []
    calculate_payroll(ctx("ZZ"), "standard")                       # the spy does watch the generic path
    assert calls and all(rule.startswith("MX_") for rule in calls[0])


# ── validation switch: MX on, nobody else changed ───────────────────────────

_VALIDATION_SET_BEFORE_MX = {"IE", "SG", "SE", "IT", "HK", "CH", "SA", "NL"}


def test_validation_switch_adds_only_mexico():
    from app.modules.payroll.engine.countries.shared import _VALIDATION_ENABLED_COUNTRIES

    # + Brazil (ZP-BR-ENG-001), opted in alongside Mexico at the venu/main merge.
    # + South Africa (ZP-ZA-ENG-001 Phase 3), fail-closed from its first engine.
    # + Japan (ZP-JP-ENG-001 Phase 3), fail-closed from its first engine.
    assert set(_VALIDATION_ENABLED_COUNTRIES) == _VALIDATION_SET_BEFORE_MX | {"MX", "BR", "ZA", "JP"}


def test_validation_behaviour_is_unchanged_for_every_other_country():
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries.shared import (
        _VALIDATION_ENABLED_COUNTRIES, MissingComplianceConfigurationError,
    )

    for country in ("US", "UK", "IN", "AU", "CA", "DE", "FR"):        # not opted in: still a no-op
        assert country not in _VALIDATION_ENABLED_COUNTRIES
        service._assert_jurisdiction_ready({}, [], country, None)
    for country in sorted(_VALIDATION_SET_BEFORE_MX):               # opted in before MX: still refuse empty
        with pytest.raises(MissingComplianceConfigurationError):
            service._assert_jurisdiction_ready({}, [], country, None)
    with pytest.raises(MissingComplianceConfigurationError):
        service._assert_jurisdiction_ready({}, [], "MX", None)
    with pytest.raises(MissingComplianceConfigurationError):
        service._assert_jurisdiction_ready({}, [], "JP", None)


def test_mexico_registry_rows_are_value_free_and_complete():
    from app.modules.payroll.engine import fallback_registry as fr

    c = _content()
    rows = [r for r in fr._ENGINE_CONSTANT_REGISTRY if r["country"] == "MX"]
    keyed = {r["resolverKey"]: r for r in rows if not r["resolverKey"].startswith("N/A")}
    assert set(keyed) == set(c.MX_PARAMETER_KEYS)
    assert all(r["attr"] == "MX_NO_FALLBACK" and r["module"] == "mexico" for r in rows)
    from app.modules.payroll.engine.countries import mexico

    assert hasattr(mexico, "MX_NO_FALLBACK") and mexico.MX_NO_FALLBACK is None
    required = {r["key"] for r in fr.get_required_parameter_keys("MX")}
    assert required == {k for k, (kind, _l, scope) in c.MX_PARAMETER_KEYS.items()
                        if scope == "national" and kind != "text" and k not in c.MX_PER_CASE_KEYS}
    inventory = [e for e in fr.get_engine_fallback_inventory()["engineConstants"] if e["country"] == "MX"]
    assert inventory and all(e["value"] is None for e in inventory)


# -- Phase 11d (gap register A9) --

def _write_log(manifest_path, rows):
    """A MATCH verification-log entry for every VERIFIED row (what
    verify_mexico_sources.py writes after a direct download)."""
    import csv

    from app.modules.payroll import mexico_sources

    with open(mexico_sources.log_path(manifest_path), "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=mexico_sources.LOG_COLUMNS)
        writer.writeheader()
        for r in rows:
            if r["status"] == "VERIFIED":
                writer.writerow({"code": r["code"], "file": r["file"], "url": r["url"], "final_url": r["url"],
                                 "downloaded_at": "2026-10-26T00:00:00Z", "downloader": "test@example.com",
                                 "response_bytes": r.get("bytes") or "1", "sha256": r["sha256"], "result": "MATCH"})


def _manifest_file(tmp_path, rows):
    path = tmp_path / "SOURCES_MANIFEST.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_log(path, rows)
    return path


def test_an_archive_copy_may_back_a_draft_pack(db, monkeypatch, tmp_path):
    m, c, seed = _models(), _content(), _seed_module()
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_uma_daily", "1", source="S6"),))
    path = _manifest_file(tmp_path, [_manifest_row("S6", "a" * 64, status="ARCHIVE_COPY_VERIFIED"),
                                     _manifest_row("S22", "b" * 64, status="WRONG_VERSION")])
    manifest = seed.load_manifest(path)
    assert set(manifest) == {"S6", "S6/S6_synthetic.pdf"}                  # WRONG_VERSION never usable
    out = seed.seed_mexico(db, manifest=manifest)
    db.flush()
    assert out["national"].status == "Draft"
    row = db.query(m.ContributionRate).filter(m.ContributionRate.jurisdiction_country == "MX").one()
    assert db.get(m.SourceArtifact, row.source_document_id).checksum_sha256 == "a" * 64


def test_a_code_with_several_files_must_be_cited_by_file(db, monkeypatch, tmp_path):
    m, c, seed = _models(), _content(), _seed_module()
    two = [{**_manifest_row("S28", "a" * 64), "file": "S28_a.xsd"},
           {**_manifest_row("S28", "b" * 64), "file": "S28_b.xls"}]
    manifest = seed.load_manifest(_manifest_file(tmp_path, two))
    assert set(manifest) == {"S28/S28_a.xsd", "S28/S28_b.xls"}             # never collapsed to one row
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_uma_daily", "1", source="S28"),))
    with pytest.raises(SystemExit, match="S28 has 2 saved files"):
        seed.seed_mexico(db, manifest=manifest)
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (_scalar("mx_uma_daily", "1", source="S28/S28_b.xls"),))
    seed.seed_mexico(db, manifest=manifest)
    db.flush()
    row = db.query(m.ContributionRate).filter(m.ContributionRate.jurisdiction_country == "MX").one()
    assert db.get(m.SourceArtifact, row.source_document_id).checksum_sha256 == "b" * 64


def test_a_professional_minimum_wage_keeps_its_zone(db, monkeypatch):
    """The zone is stored (TaxSlab.jurisdiction_state), so Content.min_wage
    restricts a professional minimum to it and the content check sees it."""
    m, c, seed = _models(), _content(), _seed_module()
    from app.modules.payroll import mexico_service, service
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content

    monkeypatch.setattr(c, "MX_MIN_WAGES", (
        c.MinWageRow("PROF_X", "PROFESSION", "SYNTHETIC trade", "300", "ZLFN", None, None, "S9", "SYNTHETIC"),
        c.MinWageRow("PROF_X", "PROFESSION", "SYNTHETIC trade", "200", "GENERAL", None, None, "S9", "SYNTHETIC")))
    pack = seed.seed_mexico(db, manifest={"S9": _manifest_row("S9", "a" * 64)})["national"]
    db.flush()
    slabs = db.query(m.TaxSlab).filter(m.TaxSlab.jurisdiction_pack_id == pack.id).all()
    assert sorted((s.flat_amount, s.jurisdiction_state) for s in slabs) == [(Decimal("200"), "GENERAL"),
                                                                           (Decimal("300"), "ZLFN")]
    rate_map, rows = service.pack_rows_for_golden(db, pack, date(2026, 6, 30))
    content = Content(rate_map, rows, "SYNTHETIC pack")
    assert content.min_wage("PROF_X", "ZLFN") == Decimal("300")
    assert content.min_wage("PROF_X", "GENERAL") == Decimal("200")
    expected = set(c.expected_national_signatures(pack.effective_from, pack.effective_to))
    assert set(mexico_service._db_signatures(*mexico_service._pack_rows(db, pack))) == expected
    slabs[0].jurisdiction_state = None                                   # a lost zone no longer matches
    db.flush()
    assert set(mexico_service._db_signatures(*mexico_service._pack_rows(db, pack))) != expected

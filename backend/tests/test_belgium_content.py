"""Belgium (ZP-BE-ENG-001) Phase 3A: the statutory content catalogue.

Keys and vocabularies only — no statutory value in code. App modules are
imported inside each test (collection-order DB-binding hazard)."""
import ast
import re
from pathlib import Path

import pytest

PAYROLL = Path(__file__).resolve().parents[1] / "app" / "modules" / "payroll"


def _c():
    from app.modules.payroll.engine.countries import belgium_content

    return belgium_content


# ── catalogue shape ────────────────────────────────────────────────────────
def test_every_key_is_in_exactly_one_known_group():
    c = _c()
    seen = []
    for group in c.GROUPS:
        seen.extend(c.keys_in_group(group))
    assert sorted(seen) == sorted(c.KEYS) and len(seen) == len(set(seen))
    assert {g for g, *_ in c.KEYS.values()} == set(c.GROUPS) == set(c.CATEGORY_LABELS)


def test_every_key_has_a_valid_kind_and_cites_a_reference():
    c = _c()
    for key, (_group, kind, ref, label) in c.KEYS.items():
        assert key.startswith("be_") and len(key) <= 50, key
        assert kind in c.KINDS, key
        assert ref and re.search(r"BE-\d{3}|§\d+|G-\d{2}|D\d+|S\d+", ref), key
        assert label, key
    assert c.KEYS["be_bssc_pending"][2] == "G-06 / G-17 (no spec ID)"


def test_catalogue_corrections_c1_to_c6():
    c = _c()
    # C1: the rate-file quarter carries no spec value (schema versions are Phase 9 content).
    assert "be_onss_rate_file_quarter" not in c.SPEC_PROPOSED
    # C2: public holidays are a table of BE_PUBLIC_HOLIDAY slab rows.
    assert c.KEYS["be_public_holidays"][1] == c.KIND_TABLE
    assert c.RULE_TYPES["be_public_holidays"] == c.PUBLIC_HOLIDAY_RULE == "BE_PUBLIC_HOLIDAY"
    assert "dates none in spec (G-09)" in c.SPEC_PROPOSED["be_public_holidays"]
    assert "be_public_holiday_substitution_rule" in c.KEYS
    # C3: multiple-birth maternity is a band, value only in the label.
    assert c.KEYS["be_abs_maternity_multiple_weeks"][1] == c.KIND_BAND
    assert "17-19 weeks (multiple birth)" in c.key_label("be_abs_maternity_multiple_weeks")
    # C4: frequencies (no HOURLY) + the pay-bases key.
    assert c.PAY_FREQUENCIES == ("MONTHLY", "SEMI_MONTHLY", "FORTNIGHTLY", "WEEKLY")
    assert c.KEYS["be_supported_pay_bases"][:3] == ("policy", c.KIND_TEXT, "BE-004")
    assert c.LIST_VOCABULARIES["be_supported_pay_bases"] == ("SALARIED", "HOURLY")
    # C5: supported employer categories / worker codes (list keys, no spec value).
    for key in ("be_onss_supported_employer_categories", "be_onss_supported_worker_codes"):
        assert c.KEYS[key][:2] == ("onss_employer", c.KIND_TEXT) and "BE-015" in c.KEYS[key][2]
        assert key not in c.SPEC_PROPOSED
    # C6: profit sharing is a component.
    assert "PROFIT_SHARING" in c.COMPONENTS


def test_owner_decisions_include_g11_and_g16():
    keys = [k for k, _label, _blocks in _c().OWNER_DECISIONS]
    assert {"G-01", "G-02", "G-06", "G-11", "G-12", "G-13", "G-16", "G-21"} == set(keys)


def test_vocabularies_match_the_phase_2_models():
    from app.modules.payroll import models

    c = _c()
    assert c.ACCUMULATORS == models._BE_ACCUMULATORS
    assert c.DECLARATION_TYPES == models._BE_DECLARATION_TYPES
    assert c.WORKER_CATEGORIES == models._BE_WORKER_CATEGORIES


def test_evidence_register_s1_to_s24():
    c = _c()
    assert c.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 25))
    for _code, agency, title, url in c.SOURCE_REFERENCES:
        assert agency and title and url.startswith("https://")


def test_labels_fit_and_carry_spec_proposals_only_as_text():
    c = _c()
    assert set(c.SPEC_PROPOSED) <= set(c.KEYS)
    for key in c.KEYS:
        label = c.key_label(key) + " " + c.PENDING_MARK
        assert len(label) <= 100, key
        if key in c.SPEC_PROPOSED:
            assert f"spec-proposed: {c.SPEC_PROPOSED[key]}" in label
        else:
            assert "(none in spec)" in label


def test_onss_employer_rates_are_reference_only():
    c = _c()
    refs = [k for k in c.KEYS if c.is_reference_only(k)]
    assert set(refs) == {"be_onss_employer_base_rate", "be_onss_wage_moderation", "be_onss_special_160",
                         "be_onss_pension_special", "be_onss_fund_contributions"}
    for key in refs:
        assert c.REFERENCE_MARKER in c.key_label(key)
    assert c.REFERENCE_NOTE == "reference only; resolved by employer category and worker code (BE-015/BE-019)"


def test_rule_types_are_unique_and_fit_the_column():
    c = _c()
    rules = list(c.RULE_TYPES.values()) + [c.EARNING_CLASS_RULE, c.AUTHORITY_EXAMPLE_RULE]
    assert len(rules) == len(set(rules)) and all(len(r) <= 30 for r in rules)
    assert set(c.RULE_TYPES) == {k for k, v in c.KEYS.items() if v[1] in c.SLAB_KINDS}


@pytest.mark.parametrize("code, parsed", [("BE-PC-200-1.0", ("200", None, "1.0")),
                                          ("BE-PC-124-A-1.0", ("124", "A", "1.0")),
                                          ("be-pc-302-2", ("302", None, "2")),
                                          ("BE-PC-124.01-2-1.1", ("124.01", "2", "1.1"))])
def test_parse_be_agreement_code_accepts_valid_codes(code, parsed):
    assert _c().parse_be_agreement_code(code) == parsed


@pytest.mark.parametrize("code", ["", None, "BE-PC-", "BE-PC-200", "SE-SECTOR-TEKNIK-2026", "BE-200-1.0",
                                  "BE-PC-ABC-1.0", "BE-PC-200-A-B-1.0", "BE-PC-200-1.0-extra"])
def test_parse_be_agreement_code_rejects_malformed_codes(code):
    with pytest.raises(ValueError):
        _c().parse_be_agreement_code(code)


# ── guard: no statutory number in Belgian code ─────────────────────────────
# Every numeric literal in a belgium*.py / be_*.py / engine/jurisdictions/belgium
# file must be listed here with its structural justification. A statutory value
# (rate, threshold, day count, date) is never one of these: it is a pack row.
_STRUCTURAL_NUMBERS = {
    "engine/countries/belgium_content.py": {
        2026: "BE_2026 pack window year (calendar pack, not a statutory value)",
        1: "pack window start month/day; regex group index",
        12: "pack window end month", 31: "pack window end day",
        2: "regex group index", 3: "regex group index",
    },
    "engine/jurisdictions/belgium/pack.py": {
        0: "list index / slice", 1: "list index", 10: "ISO date string slice [:10]",
    },
    "be_super_admin.py": {
        0: "list index", 1: "list index / regex quantifier", 10: "ISO date string slice [:10]",
        50: "ContributionRate.total column width", 100: "ContributionRate.label column width",
        150: "TaxSlab.rate_label / tax_formula column width", 300: "reason length cap (audit column)",
        9000: "authority-example sort order (after content rows)",
    },
    "belgium_service.py": {
        0: "list index", 1: "list index", 8: "refusal message shows the first 8 problems",
        10: "ISO date string slice [:10]", 2: "resolved_pack tuple index (rates, slabs, pack)",
        3: "months per quarter (calendar fact, ONSS quarter number)",
        100: "ContributionRate.label column width", 150: "TaxSlab.rate_label column width",
        200: "SourceArtifact.agency column width", 300: "SourceArtifact.title column width",
    },
    "engine/jurisdictions/belgium/applicability.py": {
        0: "list index", 1: "list index / count of the other blocking reasons",
    },
    "engine/countries/belgium.py": {0: "list index", 1: "exactly one employment line"},
    "engine/jurisdictions/belgium/declarations.py": {0: "a count cannot be negative"},
    "engine/jurisdictions/belgium/formula.py": {
        0: "evaluation depth start", 1: "depth step",
        2000: "maximum formula length (guard against pathological input)",
        60: "maximum nesting depth (guard against pathological input)",
    },
    "engine/jurisdictions/belgium/wages.py": {0: "default seniority / index"},
    "engine/jurisdictions/belgium/working_time.py": {
        0: "list index", 1: "list index / inclusive day span (+1)", 6: "date.weekday() of a Sunday (calendar)",

    },
    "engine/jurisdictions/belgium/absence.py": {
        0: "list index / zero days", 1: "day numbering (day 1 = start) / inclusive day count",
        7: "days per week (calendar)", 12: "months per year (calendar)",
    },
    "engine/jurisdictions/belgium/holiday.py": {0: "default year index", 1: "service year = the year before the taking year (BE-024)"},
    "belgium_filing.py": {
        0: "list index / zero", 1: "first month / day; version start; index", 2: "months to a quarter end",
        3: "months per quarter", 4: "YYYY width (string slice)", 5: "YYYY-MM / YYYYQn slice offset",
        7: "YYYY-MM length", 12: "December (calendar year end) / months per year", 20: "XSD error lines shown",
        31: "31 December (calendar year end, not a deadline)", 40: "error code width",
        64: "sha256 hex width (key column)", 100: "reference column width (String(100))",
        200: "XSD error message width", 300: "note / message column width (String(300))",
    },
    "belgium_golden.py": {0: "zero / first row", 1: "first day of the year / split once",
                          5: "names shown in a refusal", 400: "case text width (formula_expression)"},
    "belgium_parallel.py": {
        0: "zero / no tolerance", 1: "first day of the cycle month", 2: "file size factor / first data line",
        10: "enterprise-number SHAPE (ten digits; refused in an import)", 11: "NISS / BIS SHAPE (eleven digits)",
        16: "Belgian IBAN SHAPE (BE + 14)", 100: "source name width", 300: "note width",
        1024: "bytes per KiB (file size limit)", 5000: "maximum rows per import (operational limit)",
    },
    "belgium_readiness.py": {0: "zero / none", 1: "one / any", 5: "items shown in a detail"},
    "belgium_payment_service.py": {0: "list index / zero amount", 1: "batch sequence (+1)",
                                   100: "idempotency key / column width 100", 200: "return reason column width"},
    "be_identifiers.py": {
        1: "regex group index; key versions start at 1", 2: "two hex characters per key byte",
        4: "base64 padding block", 12: "AES-GCM nonce length in bytes", 32: "AES-256 key length in bytes",
    },
}
# Strings that look numeric but are not statutory values.
_STRUCTURAL_STRINGS = {
    ("engine/jurisdictions/belgium/pack.py", "0.01"): "EUR cent unit (the signed rounding rule picks it)",
    ("engine/countries/belgium_content.py", "^[A-Z0-9]{1,10}$"):
        "ONSS code shape (1-10 letters / digits) for code lists and EC / WC dimensions",
    ("engine/countries/belgium_content.py", "Belcotax 281.10/281.11 XML guidance"):
        "evidence S22 title: Belcotax form numbers 281.10 / 281.11, not values",
    ("be_super_admin.py", "^[A-Za-z0-9 _.-]{1,20}$"): "authority-example name pattern (length 1-20)",
    ("belgium_service.py", "Belgium form templates (Dimona, DmfA, 281.10, payslip) stay inactive until the "
                           "authority schemas are archived and the filing path is certified (gate G3)."):
        "Belcotax form number 281.10, not a value",
    ("engine/countries/belgium.py", "BE-ENGINE-A3-2026.11"): "engine build identifier (not a value)",
    ("belgium_service.py", "[a-z0-9_-]{1,50}"): "policy allowance key slug shape (column width 50)",
    ("belgium_service.py", "0.01"): "ledger amount column scale Numeric(14, 2) (storage precision, not rounding)",
    ("belgium_filing.py", "0.01"): "filing amount scale Numeric(14, 2) (storage precision, not rounding)",
    ("belgium_parallel.py", "0.01"): "amount scale of an imported figure (two decimals; storage precision)",
    ("belgium_filing.py", "281.10"): "the Belcotax fiche NAME (form identifier, not a statutory value)",
    ("be_identifiers.py", r"^\d{5,16}$"): "ONSS employer number shape (5-16 digits; format only, G-16)",
    ("belgium_service.py", "^[A-Z0-9]{1,10}$"): "ONSS category / sub-committee code shape (1-10 letters / digits)",
    ("belgium_service.py", r"\d{9,12}"): "KBO/BCE enterprise number shape (format only, G-16)",
    ("belgium_service.py", r"\d{1,20}"): "establishment unit number shape (digits, column width 20)",
}
_NUMERIC_TEXT = re.compile(r"\d+(?:[.,]\d+)?\s*%|EUR\s*\d|\b\d+[.,]\d{2}\b")


def _belgian_files():
    files = set(PAYROLL.glob("**/belgium*.py")) | set(PAYROLL.glob("be_*.py")) \
        | set((PAYROLL / "engine" / "jurisdictions" / "belgium").glob("*.py"))
    return sorted(p for p in files if "__pycache__" not in p.parts)


def _spec_proposed_node(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SPEC_PROPOSED" for t in node.targets):
            return node
    return None


def test_no_statutory_numeric_literal_in_belgian_code():
    problems = []
    for path in _belgian_files():
        rel = path.relative_to(PAYROLL).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # SPEC_PROPOSED is display text for the G1 signer, never a value
        # (written only into row labels; tests/test_belgium_super_admin.py
        # proves no value field is ever seeded).
        skip = set()
        spec_node = _spec_proposed_node(tree)
        if spec_node is not None:
            skip = {id(n) for n in ast.walk(spec_node)}
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        allowed = _STRUCTURAL_NUMBERS.get(rel, {})
        for node in ast.walk(tree):
            if id(node) in skip or id(node) in docstrings or not isinstance(node, ast.Constant):
                continue
            value = node.value
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value not in allowed:
                problems.append(f"{rel}: numeric literal {value!r}")
            if isinstance(value, str) and _NUMERIC_TEXT.search(value) and (rel, value) not in _STRUCTURAL_STRINGS:
                problems.append(f"{rel}: numeric text {value[:60]!r}")
    assert problems == []
    assert _belgian_files(), "guard found no files"

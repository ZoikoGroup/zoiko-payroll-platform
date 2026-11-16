"""Belgium (ZP-BE-ENG-001) Block I3: every Belgian code is documented in docs/belgium/OPERATIONS_RUNBOOK.md.

The runbook is generated from the codes discovered in the Belgian modules (scripts/belgium_ops_runbook.py). A new
code without a catalogue entry, a catalogue entry for a removed code, or a stale runbook file all fail here."""
import importlib.util
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _runbook():
    spec = importlib.util.spec_from_file_location("belgium_ops_runbook", BACKEND / "scripts" / "belgium_ops_runbook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_code_is_documented_and_the_runbook_is_current():
    rb = _runbook()
    assert rb.problems() == []


def test_every_engine_constant_is_a_documented_code():
    from app.modules.payroll.engine.jurisdictions.belgium import errors

    constants = {v for k, v in vars(errors).items() if k.isupper() and isinstance(v, str) and v.startswith("BE_")}
    rb = _runbook()
    assert constants <= set(rb.CATALOGUE), sorted(constants - set(rb.CATALOGUE))


def test_each_entry_names_an_owner_and_a_fix():
    rb = _runbook()
    owners = {rb.CONTENT, rb.SETUP, rb.EMPLOYEE, rb.OPERATOR, rb.AUTHORITY, rb.ENGINEERING}
    for code, (kind, meaning, cause, owner, fix) in rb.CATALOGUE.items():
        assert kind in ("BLOCK", "EXCEPTION", "PREFLIGHT", "REFUSAL", "WARNING"), code
        assert owner in owners and meaning and cause and fix, code

"""
tests/test_netherlands_migrations.py
------------------------------------
Static contract for the Netherlands (ZP-NL-ENG-001) Alembic migrations.

SQLite tests build the schema from the ORM metadata, never from these
migration files, so a migration that references a non-existent table passes
every other test and only fails on Postgres at deploy time (which is exactly
how ac68f3723174 / 774eeaf9b33c broke the main deploy). This file parses each
NL migration and checks every table reference against the real model tables.
"""

import ast
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_VERSIONS = _BACKEND / "alembic" / "versions"

# The NL chain, oldest first.
NL_CHAIN = [
    ("43662178315b", "c7d3e8f1a2b4"),
    ("ac68f3723174", "43662178315b"),
    ("774eeaf9b33c", "ac68f3723174"),
    ("972ecd8c1dba", "774eeaf9b33c"),
    ("1080702411b1", "972ecd8c1dba"),
    ("2ad71ebff6b5", "1080702411b1"),
    ("2f905bb1c296", "2ad71ebff6b5"),
    # M8 follows main's HK migration 8b14824fb575 (itself a child of M7).
    ("3b4e5c6d7e8f", "8b14824fb575"),
    ("4c5d6e7f8a9b", "3b4e5c6d7e8f"),
]


def _model_tables() -> set:
    tables = set()
    for path in (_BACKEND / "app").rglob("*.py"):
        tables.update(re.findall(r'__tablename__\s*=\s*"([a-z_0-9]+)"', path.read_text(encoding="utf-8")))
    return tables


def _migration_file(rev: str) -> Path:
    matches = list(_VERSIONS.glob(f"{rev}_*.py"))
    assert len(matches) == 1, f"expected exactly one migration file for {rev}, found {matches}"
    return matches[0]


def _calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            yield name, args


def _created_tables() -> set:
    created = set()
    for rev, _ in NL_CHAIN:
        for name, args in _calls(ast.parse(_migration_file(rev).read_text(encoding="utf-8"))):
            if name == "create_table" and args:
                created.add(args[0])
    return created


def test_nl_chain_is_linear():
    for rev, down in NL_CHAIN:
        text = _migration_file(rev).read_text(encoding="utf-8")
        assert re.search(rf"^revision[^=]*=\s*['\"]{rev}['\"]", text, re.M), rev
        assert re.search(rf"^down_revision[^=]*=\s*['\"]{down}['\"]", text, re.M), (rev, down)


def test_every_referenced_table_exists():
    real = _model_tables()
    created_so_far = set()
    for rev, _ in NL_CHAIN:
        tree = ast.parse(_migration_file(rev).read_text(encoding="utf-8"))
        here = {args[0] for name, args in _calls(tree) if name == "create_table" and args}
        known = real | created_so_far | here
        for name, args in _calls(tree):
            if name == "ForeignKey" and args:
                target = args[0].split(".")[0]
                # A FK may only point at a table that exists by the time this
                # migration runs (earlier migration, this migration, or the
                # pre-NL schema the models describe).
                assert target in real | created_so_far | here, f"{rev}: ForeignKey -> unknown table {target}"
                if target.startswith("payroll_nl_"):
                    assert target in created_so_far | here, f"{rev}: ForeignKey -> {target} which is created LATER"
            if name in ("add_column", "batch_alter_table") and args:
                assert args[0] in known, f"{rev}: {name} on unknown table {args[0]}"
            if name == "create_index" and len(args) > 1:
                assert args[1] in known, f"{rev}: create_index on unknown table {args[1]}"
        created_so_far |= here


def test_every_nl_table_has_a_model():
    missing = sorted(_created_tables() - _model_tables())
    assert missing == [], f"NL migration tables without an ORM model: {missing}"


def test_every_nl_model_table_has_a_migration():
    nl_models = {t for t in _model_tables() if t.startswith("payroll_nl_")}
    missing = sorted(nl_models - _created_tables())
    assert missing == [], f"NL models with no migration: {missing}"

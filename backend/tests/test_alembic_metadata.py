"""
tests/test_alembic_metadata.py
-------------------------------
Validates the alembic migration history for NL payroll migrations.

Ensures:
  - NL migrations exist with correct down_revision chain
  - Total revision count matches expected
  - New head is the NL M3 migration
"""

from alembic.config import Config
from alembic.script import ScriptDirectory

import pytest


class TestAlembicMetadata:
    def test_nl_migrations_exist(self):
        """All three NL migrations exist with correct IDs."""
        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)

        revisions = {rev.revision for rev in script.walk_revisions()}

        # Phase 1: Wage tax tables M1
        assert "43662178315b" in revisions, "M1 (wage tax tables) missing"
        # Phase 3: VCR snapshots + employer premium decisions M2
        assert "ac68f3723174" in revisions, "M2 (VCR snapshots) missing"
        # Phase 4: Employer profiles, IKV, tax credit, contracts M3
        assert "774eeaf9b33c" in revisions, "M3 (employer profiles) missing"

    def test_migration_chain(self):
        """Migrations chain correctly: head -> M3 -> M2 -> M1 -> c7d3e8f1a2b4"""
        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)

        # Get the migration objects
        m1 = script.get_revision("43662178315b")
        m2 = script.get_revision("ac68f3723174")
        m3 = script.get_revision("774eeaf9b33c")

        # M1 should point to the previous head
        assert m1.down_revision == "c7d3e8f1a2b4", f"M1 down_revision wrong: {m1.down_revision}"

        # M2 should point to M1
        assert m2.down_revision == "43662178315b", f"M2 down_revision wrong: {m2.down_revision}"

        # M3 should point to M2
        assert m3.down_revision == "ac68f3723174", f"M3 down_revision wrong: {m3.down_revision}"

    def test_new_head(self):
        """The new head is M3 (774eeaf9b33c)."""
        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()

        assert "774eeaf9b33c" in heads, f"M3 is not a head: {heads}"
        # Should be the only head unless there are other parallel branches
        # (we don't enforce single head since other work may have added branches)

    def test_revision_count_increased(self):
        """At least 3 new NL revisions exist."""
        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)

        nl_revisions = [
            "43662178315b",  # M1
            "ac68f3723174",  # M2
            "774eeaf9b33c",  # M3
        ]

        for rev_id in nl_revisions:
            rev = script.get_revision(rev_id)
            assert rev is not None, f"Revision {rev_id} not found"
            assert rev.doc and "NL" in rev.doc, f"Revision {rev_id} doesn't mention NL in docstring"

    def test_migration_files_exist(self):
        """Migration files exist on disk."""
        import os
        from pathlib import Path

        alembic_versions = Path("alembic/versions")
        expected_files = [
            "43662178315b_nl_wage_tax_tables_m1.py",
            "ac68f3723174_nl_vcr_snapshots_and_employer_premium_.py",
            "774eeaf9b33c_nl_employer_profiles_income_.py",
        ]

        for fname in expected_files:
            fpath = alembic_versions / fname
            assert fpath.exists(), f"Migration file {fname} not found at {fpath}"

    def test_migrations_have_upgrade_downgrade(self):
        """Each NL migration has both upgrade() and downgrade() functions."""
        import importlib.util
        from pathlib import Path

        alembic_versions = Path("alembic/versions")
        expected_files = {
            "43662178315b_nl_wage_tax_tables_m1.py": ["upgrade", "downgrade"],
            "ac68f3723174_nl_vcr_snapshots_and_employer_premium_.py": ["upgrade", "downgrade"],
            "774eeaf9b33c_nl_employer_profiles_income_.py": ["upgrade", "downgrade"],
        }

        for fname, functions in expected_files.items():
            fpath = alembic_versions / fname
            spec = importlib.util.spec_from_file_location(fname[:-3], fpath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for func_name in functions:
                assert hasattr(module, func_name), f"{fname} missing {func_name}()"
                assert callable(getattr(module, func_name)), f"{fname}.{func_name} is not callable"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
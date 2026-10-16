"""Alembic refuses schema writes against a non-local database unless the
deploy pipeline sets ZOIKO_ALLOW_REMOTE_MIGRATIONS (2026-10-14 incident: a
migration run from a laptop moved production's alembic_version to a head whose
tables were never created, failing the next production deploy)."""

from pathlib import Path

import pytest

from scripts._local_db_guard import assert_migration_target_allowed

REMOTE = "postgresql://user:s3cret@ep-example.eu-central-1.aws.neon.tech/payroll"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("ZOIKO_ALLOW_REMOTE_MIGRATIONS", raising=False)


@pytest.mark.parametrize("command", ["upgrade", "downgrade", "stamp", None])
def test_writes_to_a_remote_database_are_refused(command, capsys):
    with pytest.raises(SystemExit) as exc:
        assert_migration_target_allowed(command, REMOTE)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "REFUSING" in err and "s3cret" not in err            # the password is never printed


@pytest.mark.parametrize("command", ["current", "heads", "history", "check", "branches", "show"])
def test_read_only_commands_are_never_blocked(command):
    assert_migration_target_allowed(command, REMOTE)


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///./local.db", "postgresql://postgres@localhost:55432/x",
                                 "postgresql://u:p@127.0.0.1/x"])
def test_local_databases_are_allowed(url):
    assert_migration_target_allowed("upgrade", url)


def test_the_deploy_override_allows_a_remote_upgrade(monkeypatch, capsys):
    monkeypatch.setenv("ZOIKO_ALLOW_REMOTE_MIGRATIONS", "I_UNDERSTAND")
    assert_migration_target_allowed("upgrade", REMOTE)
    assert "NON-LOCAL" in capsys.readouterr().err


def test_a_wrong_override_value_does_not_count(monkeypatch):
    monkeypatch.setenv("ZOIKO_ALLOW_REMOTE_MIGRATIONS", "yes")
    with pytest.raises(SystemExit):
        assert_migration_target_allowed("upgrade", REMOTE)


def test_env_py_calls_the_guard_before_connecting():
    text = (ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    online = text[text.index("def run_migrations_online"):]
    assert online.index("assert_migration_target_allowed(") < online.index("engine.connect()")


def test_only_the_deploy_script_sets_the_override():
    deploy = (ROOT / "scripts" / "deploy_migrate.sh").read_text(encoding="utf-8")
    assert "export ZOIKO_ALLOW_REMOTE_MIGRATIONS=I_UNDERSTAND" in deploy
    # set at the top level, before the script's `alembic upgrade head`
    lines = deploy.splitlines()
    assert lines.index("export ZOIKO_ALLOW_REMOTE_MIGRATIONS=I_UNDERSTAND") < lines.index("alembic upgrade head")

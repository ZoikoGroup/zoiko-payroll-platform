"""The production read-only verification script stays SELECT-only and carries the
pre-deploy size check for migration 8b14824fb575. Imported lazily (collection-order
DB-binding hazard: the script imports app.database)."""


def test_every_check_is_a_single_select_and_passes_the_guard():
    from scripts import hk_production_readonly_verification as v

    for key, sql, expected in v.CHECKS:
        v._guard(sql)
        assert sql.lstrip().upper().startswith("SELECT"), key
        assert expected, key


def test_pre_deploy_row_count_check_reads_exact_and_estimated_size():
    from scripts import hk_production_readonly_verification as v

    checks = {key: (sql, expected) for key, sql, expected in v.CHECKS}
    sql, expected = checks["pre_deploy_assisted_access_sessions_size"]
    assert "count(*) AS exact_rows" in sql and "reltuples" in sql and "FROM assisted_access_sessions" in sql
    assert "never edit 8b14824fb575" in expected


def test_the_guard_refuses_writes():
    import pytest
    from scripts import hk_production_readonly_verification as v

    for bad in ("UPDATE users SET email = 'x'", "SELECT 1; DROP TABLE users", "DELETE FROM users"):
        with pytest.raises(SystemExit):
            v._guard(bad)

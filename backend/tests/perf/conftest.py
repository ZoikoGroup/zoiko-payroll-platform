"""Belgium scale tests (Block I2) are slow: excluded from the default run.

Run them with:  ZP_BE_SCALE=1 python -m pytest -q tests/perf      (optionally ZP_BE_SCALE_N=500)
"""
import os

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: scale / performance test, excluded unless ZP_BE_SCALE=1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ZP_BE_SCALE") == "1":
        return
    skip = pytest.mark.skip(reason="slow scale test: set ZP_BE_SCALE=1 to run (docs/belgium/PERFORMANCE.md)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)

"""Smoke test: every skeleton module imports cleanly.

This test passes as soon as the package skeleton is in place. It does NOT
test any actual functionality — every real function still raises
NotImplementedError. It catches structural breakage early (missing imports,
typos in module names, broken pyproject.toml).

Run after Phase A.1 (when contracts/ is populated) — until then, the contract
imports inside generator/metadata.py etc. are commented out and skipped here.
"""

import importlib


def test_generator_package_imports():
    import generator
    import generator.constants
    import generator.types
    import generator.spec_loader
    import generator.metadata
    import generator.terraform
    import generator.llm_client
    import generator.pass1
    import generator.pass2
    import generator.splitter
    import generator.pipeline
    import generator.cli


def test_qa_package_imports():
    import qa
    import qa.qa_validator
    import qa.smoke_test


def test_constants_are_sane():
    from generator.constants import (
        DATA_WINDOW_START_UTC,
        DATA_WINDOW_DAYS,
        INTERVAL_MINUTES,
        RECORDS_PER_TIER,
        WEEKDAY_DATES,
        WEEKEND_DATES,
        ALL_SCENARIO_IDS,
    )
    assert DATA_WINDOW_DAYS == 14
    assert INTERVAL_MINUTES == 15
    assert RECORDS_PER_TIER == 14 * 96  # 1344
    assert len(WEEKDAY_DATES) == 10
    assert len(WEEKEND_DATES) == 4
    assert len(ALL_SCENARIO_IDS) == 18
    assert ALL_SCENARIO_IDS[0] == "01"
    assert ALL_SCENARIO_IDS[-1] == "18"

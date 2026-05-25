"""Pytest fixtures shared across the test suite."""

from __future__ import annotations
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repo root."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def docs_internal_dir(repo_root: Path) -> Path:
    """docs/internal/ — gitignored, contains scenario specs."""
    return repo_root / "docs" / "internal"


@pytest.fixture(scope="session")
def scenario_specs_dir(docs_internal_dir: Path) -> Path:
    """docs/internal/scenarios/ — the 18 spec YAMLs."""
    return docs_internal_dir / "scenarios"


@pytest.fixture(scope="session")
def all_scenario_ids() -> list[str]:
    """Zero-padded scenario IDs '01' through '18'."""
    return [f"{i:02d}" for i in range(1, 19)]

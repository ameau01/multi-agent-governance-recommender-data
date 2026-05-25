"""Split Pass 2 wire format into consumer-facing telemetry files.

Pass 2 uses capitalized tier names (Compute_Metrics, Database_Metrics, etc.)
in its single-document wire format. The consumer reads four separate files with
lowercase names per the contract:

    Compute_Metrics  →  scenarios/NN/compute_telemetry.json
    Database_Metrics →  scenarios/NN/database_telemetry.json
    Cache_Metrics    →  scenarios/NN/cache_telemetry.json
    Network_Metrics  →  scenarios/NN/network_telemetry.json

Empty arrays for absent tiers stay empty.
"""

from __future__ import annotations
from pathlib import Path

from generator.types import Pass2Output


def split_telemetry(pass2_output: Pass2Output, output_dir: Path) -> dict[str, Path]:
    """Write four consumer-facing telemetry JSON files.

    Args:
        pass2_output: Result of generate_pass2.
        output_dir: e.g. `scenarios/01/`.

    Returns:
        Dict mapping tier name → path to the written file (4 entries always).
    """
    raise NotImplementedError("Phase B.4 — see BUILD_PLAN.md §B.4")


def write_correlation_evidence(
    pairs: list,    # list[CorrelationPair] post Phase A.1
    output_dir: Path,
) -> Path:
    """Write `scenarios/NN/correlation_evidence.json`.

    Empty list → file contains `[]`. Each pair is validated by the
    CorrelationPair Pydantic model before writing.
    """
    raise NotImplementedError("Phase B.3/B.4 — see BUILD_PLAN.md")

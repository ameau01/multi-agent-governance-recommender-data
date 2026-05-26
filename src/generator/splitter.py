"""Split Pass 2 wire format into the four consumer-facing telemetry files.

Pass 2's internal `Pass2Output` uses capitalized tier names (Compute_Metrics,
Database_Metrics, etc.). The contract's consumer files are lowercase per-tier
JSON arrays:

    Compute_Metrics  →  scenarios/NN/compute_telemetry.json
    Database_Metrics →  scenarios/NN/database_telemetry.json
    Cache_Metrics    →  scenarios/NN/cache_telemetry.json
    Network_Metrics  →  scenarios/NN/network_telemetry.json

Also writes correlation_evidence.json (which may be []).

Per docs/internal/generation-methodology.md §3 (correlation_evidence) +
docs/contract-spec.md §12.3.
"""

from __future__ import annotations
import json
from pathlib import Path

from contracts import CorrelationPair
from generator.checkpoint import write_json_atomic
from generator.types import Pass2Output


_OUTPUT_FILES = {
    "Compute_Metrics": "compute_telemetry.json",
    "Database_Metrics": "database_telemetry.json",
    "Cache_Metrics": "cache_telemetry.json",
    "Network_Metrics": "network_telemetry.json",
}


def split_telemetry(pass2_output: Pass2Output, output_dir: Path) -> dict[str, Path]:
    """Write the four consumer-facing telemetry JSON files atomically.

    Empty tiers produce `[]` files (per the contract's tier-presence rule).

    Args:
        pass2_output: Pass 2 result for one scenario.
        output_dir: e.g. scenarios/07/. Created if it doesn't exist.

    Returns:
        dict mapping tier wire-format key → path to the written file (4 entries).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for wire_key, filename in _OUTPUT_FILES.items():
        records = getattr(pass2_output, wire_key)
        target = output_dir / filename
        write_json_atomic(target, records)
        written[wire_key] = target
    return written


def write_correlation_evidence(
    pairs: list[CorrelationPair], output_dir: Path,
) -> Path:
    """Write correlation_evidence.json atomically.

    Args:
        pairs: List of CorrelationPair (may be []).
        output_dir: e.g. scenarios/07/. Created if needed.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "correlation_evidence.json"
    # Convert Pydantic models to dicts for serialization
    serialized = [p.model_dump(mode="json") for p in pairs]
    write_json_atomic(target, serialized)
    return target

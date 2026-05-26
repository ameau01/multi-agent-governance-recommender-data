"""Checkpoint helpers for resumable phase execution.

The pipeline is designed so that every per-scenario LLM call writes its
result atomically to `intermediates/NN/<phase>.json` before moving on. If the
pipeline is interrupted (Mac sleep, network failure, Ctrl-C, OOM, anything),
re-running the same phase command will:

  1. Scan `intermediates/NN/` for valid checkpoints.
  2. Skip scenarios that already have a valid checkpoint for this phase.
  3. Re-run only the scenarios that are missing or whose checkpoint is corrupt.

This module provides the helpers that make that pattern work.

# Atomic writes

`write_json_atomic()` uses the tmp-file-and-rename pattern: write to
`<path>.<random>.tmp`, fsync, then atomic os.replace() onto the final path.
A partial write left over from an interrupted process is never observable —
either the full file is there, or the file is absent. No half-written JSON.

# Validation

`is_scenario_complete()` optionally validates the checkpoint file against a
Pydantic model before declaring it complete. This catches the case where the
file was written but the content is structurally wrong (e.g., schema drift
after a contract bump). Invalid files are treated as not-complete and the
scenario will be regenerated.

# Partitioning

`remaining_scenarios()` returns `(completed, remaining)` for a given phase
across a list of scenario IDs. The phase runner uses this to print
"N/18 already complete, M remaining, estimated cost for remaining: ~$X"
before asking for confirmation.

This module is concrete — not stubbed. It works as-is once Phase A.1 ships
the contracts package.
"""

from __future__ import annotations
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

from pydantic import BaseModel, ValidationError


# ============================================================
# Atomic write
# ============================================================
def write_json_atomic(path: Path, data: Any, *, indent: int = 2) -> None:
    """Atomically write a JSON-serializable object to `path`.

    Writes to a tmp file in the same directory, fsyncs, then atomically
    renames over the final path. If the process is interrupted at any point,
    the original file (if any) is untouched and the tmp file is cleaned up.

    Args:
        path: Final destination path.
        data: JSON-serializable object (dicts, lists, primitives, or Pydantic
              models via `.model_dump(mode="json")` first).
        indent: JSON indentation. Default 2 for diff-friendly output.

    Raises:
        TypeError: if data is not JSON-serializable.
        OSError: on filesystem failures (disk full, permission, etc.).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create tmp file in the same directory (so rename is atomic on POSIX).
    fd, tmp_str = tempfile.mkstemp(
        suffix=".tmp",
        prefix=path.name + ".",
        dir=str(path.parent),
    )
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent, default=str)
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename. On POSIX, replaces any existing file at `path`.
        os.replace(tmp, path)
    except BaseException:
        # Clean up the tmp file on any failure, including KeyboardInterrupt.
        tmp.unlink(missing_ok=True)
        raise


def write_pydantic_atomic(path: Path, model: BaseModel) -> None:
    """Atomic-write a Pydantic model as JSON.

    Equivalent to `write_json_atomic(path, model.model_dump(mode="json"))`.
    """
    write_json_atomic(path, model.model_dump(mode="json"))


def read_json(path: Path) -> Any:
    """Read JSON from path. Raises FileNotFoundError if missing,
    json.JSONDecodeError if corrupt."""
    return json.loads(path.read_text())


# ============================================================
# Checkpoint validity
# ============================================================
def is_scenario_complete(
    scenario_id: str,
    phase: str,
    intermediates_dir: Path,
    model_cls: Type[BaseModel] | None = None,
) -> bool:
    """Has `scenario_id` completed `phase` successfully?

    A scenario is complete for a phase iff:
      - `intermediates/<scenario_id>/<phase>.json` exists
      - File is non-empty
      - (If model_cls is supplied) JSON parses and validates against model_cls

    Returns False on any failure mode — corrupt/incomplete checkpoint files
    are treated as not-done so the next run regenerates them.

    Args:
        scenario_id: Zero-padded ID, e.g. "07".
        phase: Phase name matching the checkpoint filename stem,
               e.g. "pass1", "pass2", "smoke_test", "smoke_test_judge".
        intermediates_dir: Repo's intermediates/ directory.
        model_cls: Optional Pydantic class to validate against. If None,
                   existence alone is sufficient.

    Returns:
        True if the checkpoint is valid, False otherwise.
    """
    path = intermediates_dir / scenario_id / f"{phase}.json"
    if not path.exists():
        return False
    try:
        if path.stat().st_size == 0:
            return False
        if model_cls is None:
            return True
        data = read_json(path)
        model_cls.model_validate(data)
        return True
    except (json.JSONDecodeError, ValidationError, OSError):
        return False


# ============================================================
# Partitioning — for resume
# ============================================================
@dataclass(frozen=True)
class PhasePartition:
    """Result of partitioning scenarios into completed / remaining for a phase."""

    phase: str
    completed: list[str]                       # scenario_ids with valid checkpoints
    remaining: list[str]                       # scenario_ids that still need work

    @property
    def total(self) -> int:
        return len(self.completed) + len(self.remaining)

    @property
    def all_complete(self) -> bool:
        return len(self.remaining) == 0

    def summary_line(self) -> str:
        """e.g. "Pass 1: 12/18 already complete, 6 remaining" """
        return (
            f"Phase {self.phase!r}: {len(self.completed)}/{self.total} already "
            f"complete, {len(self.remaining)} remaining"
        )


def partition_scenarios(
    scenario_ids: list[str],
    phase: str,
    intermediates_dir: Path,
    model_cls: Type[BaseModel] | None = None,
) -> PhasePartition:
    """Split scenario_ids into (completed, remaining) for a given phase.

    Use this in CLI phase commands to determine what work to skip after a
    resume:

        partition = partition_scenarios(
            scenario_ids=ALL_SCENARIO_IDS,
            phase="pass1",
            intermediates_dir=INTERMEDIATES_DIR,
            model_cls=Pass1Output,
        )
        print(partition.summary_line())
        if not partition.remaining:
            print("✓ Nothing to do.")
            return
        # ... run only `partition.remaining` ...

    Returns:
        PhasePartition with .completed and .remaining lists, both
        preserving the input order of scenario_ids.
    """
    completed: list[str] = []
    remaining: list[str] = []
    for sid in scenario_ids:
        if is_scenario_complete(sid, phase, intermediates_dir, model_cls):
            completed.append(sid)
        else:
            remaining.append(sid)
    return PhasePartition(phase=phase, completed=completed, remaining=remaining)


# ============================================================
# Path helpers
# ============================================================
def checkpoint_path(scenario_id: str, phase: str, intermediates_dir: Path) -> Path:
    """Canonical path for a per-scenario per-phase checkpoint file."""
    return intermediates_dir / scenario_id / f"{phase}.json"


def usage_path(scenario_id: str, phase: str, intermediates_dir: Path) -> Path:
    """Canonical path for a per-scenario per-phase usage/cost log."""
    return intermediates_dir / scenario_id / f"{phase}.usage.json"


# ============================================================
# Chunk-aware helpers (Pass 1 day-chunked generation)
# ============================================================
def chunk_checkpoint_path(
    scenario_id: str,
    phase: str,
    tier: str,
    chunk_index: int,
    intermediates_dir: Path,
) -> Path:
    """Canonical path for a per-chunk checkpoint file.

    Example: intermediates/01/pass1_compute_day03.json (zero-padded 2 digits).
    """
    return (
        intermediates_dir / scenario_id
        / f"{phase}_{tier}_day{chunk_index:02d}.json"
    )


def chunk_llm_log_path(
    scenario_id: str,
    phase: str,
    tier: str,
    chunk_index: int,
    intermediates_dir: Path,
) -> Path:
    """LLM log file path for one chunk."""
    return (
        intermediates_dir / scenario_id
        / f"{phase}_{tier}_day{chunk_index:02d}_llm_log.json"
    )


@dataclass(frozen=True)
class ChunkPartition:
    """Per-tier partition of day-chunks into (completed, remaining)."""

    tier: str
    completed: list[int]                       # day indices [0..13] with valid checkpoints
    remaining: list[int]                       # day indices that need to run

    @property
    def total(self) -> int:
        return len(self.completed) + len(self.remaining)

    @property
    def all_complete(self) -> bool:
        return len(self.remaining) == 0


def partition_chunks(
    scenario_id: str,
    phase: str,
    tier: str,
    days: int,
    intermediates_dir: Path,
) -> ChunkPartition:
    """For one (scenario, phase, tier), partition days into (completed, remaining).

    A day is complete if its chunk file exists, is non-empty, and contains
    valid JSON. Pydantic validation of contents is the caller's responsibility
    (different per tier).

    Args:
        scenario_id: e.g. "01".
        phase: typically "pass1".
        tier: "compute" / "database" / "cache" / "network".
        days: total number of day-chunks expected (typically 14).
        intermediates_dir: repo's intermediates/ directory.

    Returns:
        ChunkPartition with completed + remaining day indices.
    """
    completed: list[int] = []
    remaining: list[int] = []
    for day_index in range(days):
        path = chunk_checkpoint_path(
            scenario_id, phase, tier, day_index, intermediates_dir,
        )
        if path.exists() and path.stat().st_size > 0:
            try:
                # Quick JSON validity check (content validation is caller's job)
                read_json(path)
                completed.append(day_index)
            except json.JSONDecodeError:
                remaining.append(day_index)
        else:
            remaining.append(day_index)
    return ChunkPartition(tier=tier, completed=completed, remaining=remaining)


# ============================================================
# Pass 2 window-based checkpoints (with provenance stamping for G9)
# ============================================================
#
# A "window checkpoint" stores the modified records for ONE work item.
# Each window file has a sidecar `.stamp.json` that records the exact
# provenance: Pass 1 content hash, rule index, prompt content hash, and
# the work item's trigger span.
#
# Resume rules: a checkpoint is reused ONLY if its stamp matches the
# current plan's stamp values for that work item. Any mismatch causes
# the chunk to be re-generated, never silently consumed. This eliminates
# the "you re-ran Pass 1 and Pass 2 silently used stale chunks" failure
# mode that would otherwise be invisible.
#
# File layout per scenario:
#   intermediates/NN/pass2_window_<work_id>.json          ← the modified records
#   intermediates/NN/pass2_window_<work_id>.stamp.json    ← provenance sidecar
#   intermediates/NN/pass2_window_<work_id>_llm_log.json  ← per-window LLM log
#   intermediates/NN/pass2_plan.json                      ← Phase 2A output
#   intermediates/NN/pass2_verification.json              ← Phase 2 verification (G10)
#   intermediates/NN/pass2.json                           ← final merged Pass 2 (Phase 2C)


def window_checkpoint_path(
    scenario_id: str,
    work_id: str,
    intermediates_dir: Path,
) -> Path:
    """Path for one window's modified-records checkpoint."""
    return intermediates_dir / scenario_id / f"pass2_window_{work_id}.json"


def window_stamp_path(
    scenario_id: str,
    work_id: str,
    intermediates_dir: Path,
) -> Path:
    """Path for one window's provenance sidecar."""
    return intermediates_dir / scenario_id / f"pass2_window_{work_id}.stamp.json"


def window_llm_log_path(
    scenario_id: str,
    work_id: str,
    intermediates_dir: Path,
) -> Path:
    """Path for one window's LLM call log (multi-turn agent loop)."""
    return intermediates_dir / scenario_id / f"pass2_window_{work_id}_llm_log.json"


@dataclass(frozen=True)
class WindowStamp:
    """Provenance fields stamped onto each Pass 2 window checkpoint.

    All four fields must match between the stamp and the current run for
    the checkpoint to be reused. Otherwise the window is regenerated.
    """

    pass1_sha256: str                    # Pass 1 content hash (first 16 chars enough)
    rule_index: int                      # which rule in spec.pass2_correlations
    prompt_sha256: str                   # prompts/pass2.txt content hash
    trigger_start_iso: str               # window's first trigger timestamp
    trigger_end_iso: str                 # window's last trigger timestamp


def write_window_stamp(
    path: Path, stamp: WindowStamp,
) -> None:
    """Atomic write of a window's provenance stamp."""
    write_json_atomic(
        path,
        {
            "pass1_sha256": stamp.pass1_sha256,
            "rule_index": stamp.rule_index,
            "prompt_sha256": stamp.prompt_sha256,
            "trigger_start_iso": stamp.trigger_start_iso,
            "trigger_end_iso": stamp.trigger_end_iso,
        },
        indent=2,
    )


def read_window_stamp(path: Path) -> WindowStamp | None:
    """Read a window's provenance stamp, or return None if missing/corrupt."""
    if not path.exists():
        return None
    try:
        data = read_json(path)
        return WindowStamp(
            pass1_sha256=data["pass1_sha256"],
            rule_index=int(data["rule_index"]),
            prompt_sha256=data["prompt_sha256"],
            trigger_start_iso=data["trigger_start_iso"],
            trigger_end_iso=data["trigger_end_iso"],
        )
    except (json.JSONDecodeError, KeyError, OSError, ValueError):
        return None


def window_checkpoint_valid(
    scenario_id: str,
    work_id: str,
    expected_stamp: WindowStamp,
    intermediates_dir: Path,
) -> bool:
    """A window checkpoint is reusable iff:
       - The records file exists and is non-empty valid JSON.
       - The stamp file exists.
       - The stamp matches `expected_stamp` on all four fields.
    """
    records_path = window_checkpoint_path(scenario_id, work_id, intermediates_dir)
    if not records_path.exists() or records_path.stat().st_size == 0:
        return False
    try:
        read_json(records_path)
    except json.JSONDecodeError:
        return False
    stamp_path = window_stamp_path(scenario_id, work_id, intermediates_dir)
    actual = read_window_stamp(stamp_path)
    if actual is None:
        return False
    return (
        actual.pass1_sha256 == expected_stamp.pass1_sha256
        and actual.rule_index == expected_stamp.rule_index
        and actual.prompt_sha256 == expected_stamp.prompt_sha256
        and actual.trigger_start_iso == expected_stamp.trigger_start_iso
        and actual.trigger_end_iso == expected_stamp.trigger_end_iso
    )


@dataclass(frozen=True)
class WindowPartition:
    """Partition of a scenario's work_ids into (completed, remaining)."""

    completed: list[str]
    remaining: list[str]

    @property
    def total(self) -> int:
        return len(self.completed) + len(self.remaining)

    @property
    def all_complete(self) -> bool:
        return len(self.remaining) == 0


def partition_windows(
    scenario_id: str,
    work_ids: list[str],
    expected_stamps: dict[str, WindowStamp],
    intermediates_dir: Path,
) -> WindowPartition:
    """For a scenario's work plan, classify each work_id as completed or remaining.

    A work_id is `completed` iff its checkpoint exists AND its stamp matches
    the expected provenance. Any mismatch / missing file → `remaining`.
    """
    completed: list[str] = []
    remaining: list[str] = []
    for wid in work_ids:
        stamp = expected_stamps.get(wid)
        if stamp is None:
            remaining.append(wid)
            continue
        if window_checkpoint_valid(scenario_id, wid, stamp, intermediates_dir):
            completed.append(wid)
        else:
            remaining.append(wid)
    return WindowPartition(completed=completed, remaining=remaining)


# ============================================================
# Generic content hashing — used for provenance
# ============================================================
def sha256_bytes_hex(data: bytes, *, length: int = 16) -> str:
    """Short SHA-256 hex digest (default 16 chars) for stamping checkpoints.

    16 hex chars = 64 bits of entropy = collision-safe for our scale.
    """
    import hashlib
    return hashlib.sha256(data).hexdigest()[:length]


def sha256_file_hex(path: Path, *, length: int = 16) -> str:
    """Short SHA-256 of a file's content."""
    return sha256_bytes_hex(path.read_bytes(), length=length)

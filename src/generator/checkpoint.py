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

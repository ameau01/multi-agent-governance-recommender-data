"""Build helpers for public-export/. Three subcommands:

  copy-scenarios          : sanitize + copy each scenario into dataset/
  emit-expectations       : write 18 evaluation_expectations.json from rubrics.py
  emit-sample-predictions : degrade real smoke_test.json into sample_predictions.json

This module is BUILD-TIME only. It stays in the private repo. Do not copy it
into public-export/.
"""

from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "public-export"
SCEN = REPO / "scenarios"
INTER = REPO / "intermediates"

# These keys must NEVER appear in the public files.
SANITIZE_KEYS = {
    "raw_model_response",
    "_llm_log",
    "model",
    "model_name",
    "anthropic_model",
    "system_prompt",
    "prompt",
    "stop_reason",
    "usage",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "trace_id",
    "langsmith_trace_id",
    # Metadata-level keys: the full gold answer is in
    # handcrafted_recommendation.json, so the compact metadata copy is
    # redundant. generated_at is a generation timestamp.
    "target_recommendation",
    "generated_at",
}


# ============================================================
# copy-scenarios
# ============================================================
def copy_scenarios() -> None:
    """Copy each scenario's data + sanitized recommendation into dataset/."""
    sids = [f"{i:02d}" for i in range(1, 19)]
    for sid in sids:
        src_dir = SCEN / sid
        smoke_path = INTER / sid / "smoke_test.json"
        dst_dir = OUT / "dataset" / "scenarios" / sid
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Telemetry + infra files: direct copy
        for fname in (
            "metadata.json", "main.tf",
            "cache_telemetry.json", "compute_telemetry.json",
            "database_telemetry.json", "network_telemetry.json",
            "correlation_evidence.json",
        ):
            src = src_dir / fname
            if not src.exists():
                continue
            if fname.endswith(".json"):
                data = json.loads(src.read_text())
                data = _strip_keys(data)
                (dst_dir / fname).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n"
                )
            else:
                (dst_dir / fname).write_text(src.read_text())

        # Gold recommendation: sanitized + renamed
        if smoke_path.exists():
            rec = json.loads(smoke_path.read_text())
            rec = _strip_keys(rec)
            # Rename if any field uses target_recommendation
            rec = _rename_target_to_handcrafted(rec)
            dst_rec = dst_dir / "handcrafted_recommendation.json"
            dst_rec.write_text(json.dumps(rec, indent=2) + "\n")

        print(f"  ✓ {sid}: copied {len(list(dst_dir.iterdir()))} files")


# ============================================================
# emit-expectations
# ============================================================
def emit_expectations() -> None:
    """Emit one evaluation_expectations.json per scenario from rubrics.py."""
    sys.path.insert(0, str(REPO / "src"))
    from qa.rubrics import RUBRICS  # noqa: E402

    for sid, rubric in RUBRICS.items():
        # Strip Python-side leading underscores; keep _rationale as
        # 'description' for clarity in the public file.
        public = {}
        for k, v in rubric.items():
            if k == "_rationale":
                public["description"] = _scrub_prose(v)
            elif k.startswith("_") and k.endswith("_rationale"):
                # _action_category_rationale → action_category_rationale
                public[k.lstrip("_")] = _scrub_prose(v)
            else:
                public[k] = v

        out_dir = OUT / "eval-set" / "expectations" / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "evaluation_expectations.json").write_text(
            json.dumps(public, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"  ✓ {sid}: expectations written")


# ============================================================
# emit-sample-predictions
# ============================================================
def emit_sample_predictions() -> None:
    """Degrade real smoke_test.json outputs into sample submissions.

    Strategy: take 2 scenarios (01 + 06), keep the JSON shape exactly, but
    replace prose with stub content and replace numeric fields with placeholder
    zeros. The result is shape-valid (passes Floor on parseability) but
    fails on content (sample makes it obvious this is not a real prediction).
    """
    sample_ids = ["01", "06"]
    out: dict = {"predictions": []}

    for sid in sample_ids:
        smoke = json.loads((INTER / sid / "smoke_test.json").read_text())
        smoke = _strip_keys(smoke)
        stub = _degrade(smoke)
        out["predictions"].append(stub)

    # Helpful inline comment via a sibling note
    note = {
        "_note": "This is a sample showing the prediction shape. The content is stub "
                 "and is not a real recommendation. Replace each prediction with your "
                 "agent's output.",
    }
    final = {**note, **out}

    for dst in (OUT / "dataset" / "sample_predictions.json",
                OUT / "eval-set" / "sample_predictions.json"):
        dst.write_text(json.dumps(final, indent=2) + "\n")
        print(f"  ✓ wrote {dst.relative_to(REPO)}")


# ============================================================
# Helpers
# ============================================================
def _scrub_prose(text: str) -> str:
    """Apply the voice-rule cleanup to a prose string.

    Replaces em/en-dashes with commas (preserving sentence flow), drops
    typographic quotes, and trims trailing whitespace. Used on descriptions
    emitted to public JSON files.
    """
    if not isinstance(text, str):
        return text
    # Spaced em-dash / en-dash / double-hyphen → comma (clause separator)
    for needle in (" — ", " – ", " -- ", " — ", " – "):
        text = text.replace(needle, ", ")
    # Bare em/en-dash (no surrounding spaces) → comma
    for needle in ("—", "–"):
        text = text.replace(needle, ", ")
    # Curly quotes → straight
    for needle, repl in (("“", '"'), ("”", '"'),
                         ("‘", "'"), ("’", "'")):
        text = text.replace(needle, repl)
    # Collapse double spaces and double punctuation
    while "  " in text:
        text = text.replace("  ", " ")
    while ", ," in text:
        text = text.replace(", ,", ",")
    while " ," in text:
        text = text.replace(" ,", ",")
    return text.strip()


def _strip_keys(obj):
    """Recursively drop any forbidden keys."""
    if isinstance(obj, dict):
        return {
            k: _strip_keys(v)
            for k, v in obj.items()
            if k not in SANITIZE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_keys(x) for x in obj]
    return obj


def _rename_target_to_handcrafted(obj):
    """Rename any 'target_recommendation' key to 'handcrafted_recommendation'."""
    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            nk = "handcrafted_recommendation" if k == "target_recommendation" else k
            new[nk] = _rename_target_to_handcrafted(v)
        return new
    if isinstance(obj, list):
        return [_rename_target_to_handcrafted(x) for x in obj]
    return obj


def _degrade(rec: dict) -> dict:
    """Stub out the content of a real recommendation while keeping the shape."""
    stub = {
        "scenario_id": rec.get("scenario_id"),
        "finding_type": "issue_found",  # plausible but generic
        "specific_change": ("Sample only — replace with your agent's recommendation. "
                            "Must be at least 20 characters."),
        "primary_tier": "compute",
        "secondary_tier": None,
        "action_category": "rightsizing",
        "conclusion": {
            "finding_type": "issue_found",
            "primary_tier": "compute",
            "secondary_tier": None,
            "action_category": "rightsizing",
            "headline": "Sample headline only.",
        },
        "evidence": {
            "telemetry_observations": ["Sample telemetry observation."],
            "infrastructure_context": ["Sample infrastructure context."],
            "correlation_observations": ["Sample correlation observation."],
        },
        "reasoning": "Sample reasoning only. Replace with your agent's reasoning.",
        "projected_state": {
            "cpu_p95_pct_estimate": 0,
            "memory_p95_pct_estimate": 0,
            "latency_p95_ms_estimate": 0,
            "sla_availability_preserved": True,
            "notes": "Sample projected state.",
        },
        "cost_impact": {
            "current_monthly_usd": 0,
            "projected_monthly_usd": 0,
            "savings_monthly_usd": 0,
            "savings_pct": 0,
            "notes": "Sample cost impact.",
        },
        "risk_assessment": {
            "primary_risk": "Sample risk.",
            "mitigation": "Sample mitigation.",
            "rollback": "Sample rollback plan.",
            "notes": "Sample risk notes.",
        },
    }
    return stub


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "copy-scenarios":
        copy_scenarios()
    elif cmd == "emit-expectations":
        emit_expectations()
    elif cmd == "emit-sample-predictions":
        emit_sample_predictions()
    else:
        print(f"ERROR: unknown subcommand: {cmd}")
        sys.exit(2)

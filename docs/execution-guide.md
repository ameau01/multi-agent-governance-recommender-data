# Execution Guide

> How to take the skeleton in `src/` from "imports cleanly" to "produces 18 scenarios."

This guide is the practical companion to [`BUILD_PLAN.md`](../BUILD_PLAN.md). The build plan describes *what* to deliver in each phase; this guide describes *how to wire it up*, *what order to fill in the stubs*, and *where to look in `docs/internal/` for the rules each module enforces*.

---

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) installed (`brew install uv` on macOS)
- An Anthropic API key from `console.anthropic.com` (separate from claude.ai)
- A LangSmith API key from `smith.langchain.com` (optional but recommended for tracing)

---

## Day 0: Bootstrap

```bash
git clone <this repo>
cd cloud-governance-data-gen

# 1. Set up your environment
cp .env.example .env
# Edit .env and fill in real values for ANTHROPIC_API_KEY and (optionally) LANGSMITH_*

# 2. Install dependencies and verify the skeleton
make install                          # uv sync — installs all runtime + dev deps
make test                             # runs tests/test_skeleton_imports.py — should pass on a fresh clone
```

If `make test` fails because `src/contracts/` is empty, you're ahead of Phase A.1. Continue.

**About the .env file.** Required for any LLM-driven stage (Pass 1, Pass 2, smoke test). The CLI loads `.env` automatically via `python-dotenv`. `.env` is gitignored; never commit it. The `.env.example` template is the canonical reference for which variables are needed.

**About LangSmith tracing.** If `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` are set, every Anthropic API call is automatically logged to the project named in `LANGSMITH_PROJECT` (recommended: `multi-agent-governance-recommender-data`). Tracing is implemented via `langsmith.wrappers.wrap_anthropic` in `src/generator/llm_client.py:_make_anthropic_client` — no code changes needed to enable, just set the env vars. When `LANGSMITH_TRACING` is unset or `false`, the pipeline runs against the raw Anthropic SDK with zero tracing overhead.

To group per-scenario LLM calls into a single LangSmith run (so Pass 1 + Pass 2 + smoke test for Scenario 07 all appear under one parent trace), decorate the calling function:

```python
from langsmith import traceable

@traceable(name="build_scenario", metadata={"scenario_id": scenario_id})
def build_scenario(scenario_id, ...):
    ...   # Anthropic calls inside are auto-nested under this run
```

This is a Phase B enhancement — useful for debugging multi-stage runs but not required for the pipeline to work.

---

## The pipeline at a glance

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Input: docs/internal/scenarios/NN.spec.yaml                             │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                        spec_loader.load_spec(NN)
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
         pass1.generate     metadata.build      terraform.render
         pass1.write        metadata.write      terraform.validate
              │                   │             terraform.write
              ▼                   │                   │
         pass2.generate           │                   │
         pass2.write              │                   │
              │                   │                   │
              ▼                   │                   │
         splitter.split           │                   │
         splitter.write_corr      │                   │
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  │
                                  ▼
                        qa.qa_validator.validate
                                  │
                          pass? ──┼── fail?
                            │     │     │
                            ▼     │     ▼
              keep scenarios/NN/  │  rollback + report
                                  │
                                  ▼
            (later, before handoff) qa.smoke_test.smoke_test_scenario
```

---

## Phase A — Foundations (Days 1–3)

**Goal:** make the deterministic part of the pipeline work end-to-end. No LLM yet.

### Order of implementation

| Order | Stub to fill | File | What it does | Rules live in |
|---|---|---|---|---|
| 1 | `spec_loader.load_spec` + `load_all_specs` | `src/generator/spec_loader.py` | Load + validate one or all scenario YAMLs | `docs/internal/scenarios/07.spec.yaml` (canonical example) |
| 2 | `metadata.build_metadata` + `write_metadata` | `src/generator/metadata.py` | Spec YAML → `ScenarioMetadata` → `metadata.json` | `docs/internal/generation-methodology.md` §4 + `generation-conventions.md` §§5–8 |
| 3 | `terraform.render_terraform` + `validate_terraform` + `write_terraform` | `src/generator/terraform.py` + `templates/*.tf.j2` | Metadata → HCL via Jinja | `docs/internal/generation-methodology.md` §5 |

### Order of testing

```bash
# After step 1
make test                                        # spec_loader unit tests pass

# After step 2
make build-metadata SCENARIO=01                  # writes scenarios/01/metadata.json
make build-metadata SCENARIO=07                  # cross-tier with all four tiers
make build-metadata SCENARIO=17                  # diagnostic_deferral (null action_category)

# After step 3
make build-terraform SCENARIO=01                 # writes scenarios/01/main.tf
make build-terraform SCENARIO=05                 # load-balancer scenario — check algorithm is set
make build-terraform SCENARIO=07                 # multi-tier — check security group rules
```

### Phase A exit gate

You can run `make build-metadata SCENARIO=NN` and `make build-terraform SCENARIO=NN` for any of `01`–`18`, and both files validate. Telemetry files are still missing — Phase B fills them in.

### Common Phase A gotchas

- **Pydantic v2 syntax.** `extra="forbid"` is via `model_config = ConfigDict(extra="forbid")`, not the v1 `class Config:` style. The contract package and `types.py` already follow v2 — don't mix.
- **Empty tier handling.** For scenarios that don't use a tier (e.g., Scenario 01 has no DB, cache, or network), `tier_topology.database` is `None`. The Terraform renderer must not emit a database block. The metadata generator must auto-fill `cost_baseline.by_tier.database = 0.0`.
- **`scenario_id` is always a string.** `"01"` not `1`. The Pydantic `ScenarioMetadata.scenario_id` field is typed `str` — passing an int will fail validation.

---

## Phase B — Pipeline (Days 4–7)

**Goal:** wire up the LLM-driven stages + the QA validator. End of Phase B, two scenarios are fully working.

### Order of implementation

| Order | Stub to fill | File | What it does | Rules live in |
|---|---|---|---|---|
| 1 | `LLMClient.call` | `src/generator/llm_client.py` | Anthropic SDK wrapper, prompt rendering, response stripping, logging | — |
| 2 | `pass1.generate_pass1` + helpers | `src/generator/pass1.py` | LLM-driven base telemetry | `docs/internal/generation-methodology.md` §2, `prompts/pass1.txt` |
| 3 | `pass2.generate_pass2` + `_enforce_invariance` + `_compute_correlation_evidence` | `src/generator/pass2.py` | LLM-driven correlation injection + post-hoc correlation summary | `docs/internal/generation-methodology.md` §3, `prompts/pass2.txt` |
| 4 | `splitter.split_telemetry` + `write_correlation_evidence` | `src/generator/splitter.py` | Pass 2 wire format → 4 consumer telemetry files + correlation_evidence.json | `docs/internal/generation-methodology.md` §3 (correlation_evidence) |
| 5 | `qa_validator.validate_scenario` + 10 semantic checks | `src/qa/qa_validator.py` | All checks from generation-qa.md | `docs/internal/generation-qa.md` §§2–3 |
| 6 | `pipeline.build_scenario` | `src/generator/pipeline.py` | Orchestrate Pass 1 → Pass 2 → Splitter → Metadata → Terraform → QA | `docs/internal/generation-methodology.md` §1 |
| 7 | `smoke_test.smoke_test_scenario` | `src/qa/smoke_test.py` | Single-LLM-call solvability check | `docs/internal/scenario-quality-smoke-test.md` |

### Pilot run (after step 7)

```bash
make build SCENARIO=01                           # simplest — single-tier, no correlations
make build SCENARIO=07                           # representative cross-tier with correlations
make smoke-test-pilots                           # confirm both are solvable by baseline LLM
```

### Phase B exit gate

Scenarios 01 and 07 are committed under `scenarios/`, all 7 files per scenario validate, QA reports show 0 failures in either layer, smoke test passes on both.

### Phase B prompt iteration

Expect to revise `prompts/pass1.txt` and `prompts/pass2.txt` during Phase B. Common iterations:

- Pass 1 emits values outside the spec's range → tighten the prompt's emphasis on "must remain within the ranges stated in PASS 1 METRIC RANGES."
- Pass 1 fails to produce a recognizable business-hours pattern → add a worked example in the prompt or restate the time-pattern conventions.
- Pass 2 drifts on unrelated tiers → re-emphasize "tiers NOT mentioned in the correlation rules: output their Pass 1 values UNCHANGED, bit-for-bit."
- Pass 2 treats relative magnitudes as absolute → emphasize the baseline-reference section.

After each prompt change, re-run the affected scenarios + the QA validator. Treat the pilot scenarios (01, 07) as the prompt-iteration corpus.

### Common Phase B gotchas

- **Pass 1 wire format vs file layout.** Pass 1 emits one JSON document with `Compute_Metrics`/`Database_Metrics`/etc. The splitter renames to lowercase `compute_telemetry.json` etc. Don't write the consumer-facing files directly from Pass 1 — Pass 2 needs to read Pass 1's output as a single document first.
- **Pass 2 invariance is enforced by code, not the LLM.** Even with the prompt insisting on invariance, the model will drift. The `_enforce_invariance` function in `pass2.py` is your gate. If it raises, retry with a tightened prompt before falling back to manual intervention.
- **Correlation evidence is computed, not extracted from the LLM.** Pass 2 produces correlated telemetry; the *coefficient* / *lag* / *alignment_score* in `correlation_evidence.json` is computed by Python from the resulting time series. Don't ask the LLM for these — it would hallucinate them.
- **Scenario 5 record count is N × 1344.** With 8 instances and 1,344 timestamps, `compute_telemetry.json` has 10,752 records. The QA validator's record-count check has a special case for Scenario 5; the Pass 1 driver does too.

---

## Phase C — Full run + handoff (Days 8–10)

**Goal:** run the full pipeline against all 18 scenarios, validate the bunch, hand off to the agent project.

### Recommended path: supervised oversight run

For the first full build, use the supervised path. It walks through all **five** phases with a pause after each so you can inspect intermediates and abort if anything looks wrong:

```bash
make oversight                                   # interactive, ~$157, ~30 min
# or
make oversight-batch                             # Batch API mode, ~$79, ~65 min
```

The script (`bin/run_oversight.sh`) does this for you:

| # | Phase | Model | Cost | Wall time |
|---|---|---|---|---|
| 1 | `pass1` — base telemetry generation | Sonnet 4.6 | ~$101 | ~15 min |
| 2 | `pass2` — cross-tier correlation injection | Sonnet 4.6 | ~$54 | ~8 min |
| 3 | `validate` — contract + semantic QA | (none) | $0 | ~1 min |
| 4 | `smoke-test` — Opus recommendation per scenario | Opus 4.6 | ~$1.44 | ~5 min |
| 5 | `smoke-test-judge` — Haiku judge on saved recommendations | Haiku 4.5 | ~$0.01 | ~1 min |

Between each phase, the script pauses with review hints (`ls intermediates/*/pass1.json`, `head -50 intermediates/01/pass1.json`, etc.) and asks "Continue to next phase?". You can abort cleanly at any pause — intermediates are preserved and the next run resumes from where you stopped.

### Recovery: every phase is resumable

If your Mac sleeps mid-Pass-1 after 12 of 18 scenarios complete, you don't lose those 12. Each per-scenario LLM call writes its output **atomically** to `intermediates/NN/<phase>.json` after the call returns. On the next run:

```bash
make oversight                                   # (or make resume — same thing)
# Output during Phase 1 preview:
#   === Phase: pass1 ===
#     Model:                claude-sonnet-4-6
#     Scenarios total:      18
#     Already complete:     12 (skipped — found valid checkpoint)
#     Remaining to run:     6
#     Estimated cost:       ~$33.67    ← pro-rated, NOT the full $101
#     Estimated time:       ~5 minutes
#   Proceed? [y/N]:
```

You only pay for the 6 remaining scenarios. The 12 completed scenarios are loaded from their checkpoint files.

**Why the smoke test is split into two phases (4 and 5).** Phase 4 makes the expensive Opus calls (~$1.44 total). Phase 5 does the cheap Haiku judging (~$0.01). If Phase 5 is interrupted halfway through, you don't waste any Opus money — the saved recommendations from Phase 4 are still on disk and Phase 5 just resumes. You can also abort between 4 and 5 to review Opus's raw recommendations before letting the judge score them.

**Force re-run** (after a contract bump or major prompt change):

```bash
make pass1-all --force                           # ignores existing checkpoints; re-runs all 18
```

### Alternative: per-phase manual control

If you prefer driving phases individually rather than via the supervised walk-through:

```bash
make pass1-all                                   # Pass 1, cost preview + confirmation
# ... review intermediates/*/pass1.json ...
make pass2-all                                   # Pass 2 (correlation scenarios)
# ... review intermediates/*/pass2.json + scenarios/*/correlation_evidence.json ...
make validate-all                                # QA layers (no LLM)
# ... review intermediates/*/qa_report.json ...
make smoke-test-all                              # Opus recommendation per scenario
# ... inspect intermediates/*/smoke_test.json BEFORE judging ...
make smoke-test-judge-all                        # Haiku judge on saved recommendations
# ... review intermediates/smoke_test_summary.md ...
```

Each phase command:
- Scans `intermediates/` and shows N completed + M remaining
- Prints model + pro-rated cost + pro-rated time for remaining
- Asks `Proceed? [y/N]` (skip with `--yes`)
- Writes each scenario's output atomically as it completes
- Prints a per-scenario summary table at the end

Flags:
- `--batch` — use Anthropic Batches API at 50% cost (~5–30 min async wall time per phase)
- `--yes` — skip the confirmation prompt (useful for unattended runs once you trust the pipeline)
- `--force` — ignore existing checkpoints; re-run all scenarios from scratch (after a contract bump or major prompt change)

### Per-scenario recovery (when one scenario fails QA or smoke test)

If the smoke test fails for Scenario 13 specifically, you can re-run just that scenario's pipeline:

```bash
make pass1 SCENARIO=13                           # regenerate Pass 1 for scenario 13
make pass2 SCENARIO=13                           # then Pass 2
make validate SCENARIO=13                        # then validate
make smoke-test SCENARIO=13                      # then smoke test recommendation
make smoke-test-judge SCENARIO=13                # then judge
```

Or resume the full pipeline (everything else is already done, only 13 will be re-run):

```bash
make resume                                      # or just: make oversight
```

### Unattended (after you've done one supervised run)

```bash
make build-all                                   # no per-phase pauses
```

### Expected friction

### Expected friction

| Scenario | Why it may need extra work |
|---|---|
| 05 | Per-instance records (10,752 instead of 1,344) — Pass 1 may exceed output budget on Haiku; switch to Sonnet just for this scenario. |
| 08, 09, 13 | Multiple correlation rules — Pass 2 prompt may need more iteration. |
| 17 | Diagnostic-deferral correlations (rise together with no causation) — subtle pattern, 2–3 prompt iterations expected. |
| 11 | The "co-presence with no causal adjustment" pattern is unusual; Pass 2 may try to add an adjustment anyway. |

### Smoke test interpretation

Per `docs/internal/scenario-quality-smoke-test.md` §3:

| Aggregate | Action |
|---|---|
| ≥14 pass | GREEN — proceed with handoff |
| 12–13 pass | YELLOW — spot-check failed scenarios; if data looks fine, accept |
| ≤11 pass | RED — investigate data quality |

A scenario failing the smoke test is **not** a blocker if it's one of the deliberately hard cases (restraint, diagnostic deferral, SLA review, hard cross-tier). The smoke test surfaces failures for human review; it doesn't auto-reject.

### Phase C exit gate

All 18 scenarios committed under `scenarios/`. QA validator green across all. Smoke test GREEN or YELLOW with documented exceptions. Agent project's Input Harness accepts each scenario without rejection.

---

## File-level reference card

**When implementing a stub, where do the rules live?**

| Module | Doc to consult |
|---|---|
| `spec_loader.py` | `docs/internal/scenarios/07.spec.yaml` (the YAML schema by example) |
| `metadata.py` | `generation-methodology.md` §4 + `generation-conventions.md` §§5–8 |
| `terraform.py` + `templates/` | `generation-methodology.md` §5 |
| `llm_client.py` | (none — just Anthropic SDK best practices) |
| `pass1.py` | `generation-methodology.md` §2 + `prompts/pass1.txt` + `healthy-baselines.md` |
| `pass2.py` | `generation-methodology.md` §3 + `prompts/pass2.txt` |
| `splitter.py` | `generation-methodology.md` §3 (correlation evidence) + contract §12.3 |
| `qa_validator.py` | `generation-qa.md` §§2–3 |
| `smoke_test.py` | `scenario-quality-smoke-test.md` |
| `pipeline.py` | `generation-methodology.md` §1 |
| `cli.py` | `BUILD_PLAN.md` task list |

---

## Cost expectations

| Activity | Estimated cost |
|---|---|
| One scenario, end-to-end (Pass 1 + Pass 2 + smoke test) | ~$0.10 |
| Full 18-scenario build | ~$1.00 |
| Phase B prompt iteration on pilots (50× regeneration) | ~$5–10 |
| **Total project LLM cost** | **~$10–15** |

If costs run higher, the dominant driver is prompt iteration. Move to Sonnet for difficult scenarios only.

---

## What to NOT do

- Don't generate scenarios by hand. The pipeline is the source of truth; manual edits to `scenarios/NN/*.json` will fail the QA validator and won't survive regeneration.
- Don't commit `intermediates/` or `docs/internal/` — both are gitignored. The first contains debug-only Pass 1/Pass 2 raw output; the second contains spec YAMLs and supporting docs that are working materials for this project only.
- Don't edit `src/contracts/*.py` directly. That package is owned canonically by the agent project; changes must originate there and sync over via the procedure in `src/contracts/CONTRACT_SYNC.md`.
- Don't skip Phase B prompt iteration. The first Pass 1 / Pass 2 output for a new scenario almost never passes QA cleanly. Budget time for 2–4 iteration cycles per pilot scenario.

---

## When you're done

```bash
git add scenarios/                               # commit the 18 scenario folders
git commit -m "Phase C complete: 18 scenarios generated and validated"
git push
```

Notify the agent project that 18 contract-conformant scenarios are available at `scenarios/01/` through `scenarios/18/`. Their Input Harness should accept each one without rejection. Iterate on any issues their harness surfaces.

That's Phase C done — handoff complete.

# Build Plan

> Execution-focused plan for implementing the data-generation pipeline. Read this when you're about to write code.

This document is the operational counterpart to [`docs/data-generation-plan.md`](docs/data-generation-plan.md). The plan doc explains *what* and *why*; this doc explains *what to build in what order, with what file paths and exit criteria*.

**Total window:** ~1.5 weeks (10 working days) overlapping with the agent project's four-week build. The data-gen pipeline must produce all 18 scenarios before the agent's Phase 3 (Tier Specialists) needs them.

---

## Phase overview

| Phase | Window | Deliverables | LLM? | Exit criterion |
|---|---|---|---|---|
| **A — Foundations** | Days 1–3 | Contract sync, metadata generator, Terraform renderer | No | Can build a `metadata.json` + `main.tf` from a spec YAML for any scenario |
| **B — Pipeline** | Days 4–7 | Pass 1, Pass 2, QA validator, end-to-end on 1–2 scenarios | Yes | Two complete scenario folders pass all QA |
| **C — Full run + handoff** | Days 8–10 | All 18 scenarios generated, validated, committed | Yes | All 18 folders pass contract + semantic QA; handoff to agent project |

---

## Phase A — Foundations (Days 1–3)

**Goal:** Get the deterministic (non-LLM) pieces working. By end of Phase A, you can take any one of the 18 scenario specs, run a non-LLM command, and produce a valid `metadata.json` and `main.tf`. The four telemetry JSON files come in Phase B.

### A.1 — Sync the shared contract package (Day 1)

The agent project (`cloud-governance-agent`) writes the canonical Pydantic contract as their Phase 1 deliverable. Receive it via their handoff package and drop into this repo.

**Files to land:**
- `src/contracts/__init__.py`
- `src/contracts/version.py` (defines `CONTRACT_VERSION = "1.0.0"`)
- `src/contracts/enums.py`
- `src/contracts/telemetry.py` — `ComputeRecord`, `DatabaseRecord`, `CacheRecord`, `NetworkRecord`
- `src/contracts/evidence.py` — `TopQuery`, `TopCacheKey`, `InstanceBreakdown`, `BeforeAfterEvidence`, `CorrelationPair`
- `src/contracts/configurations.py` — `ComputeTopologyEntry`, `DatabaseTopologyEntry`, `CacheTopologyEntry`, `NetworkTopologyEntry`, `TierTopology`
- `src/contracts/recommendation.py` — `TargetRecommendation`, `EvaluationProperties`
- `src/contracts/narrative.py` — `ScenarioNarrative`, `BusinessContext`, `CostBaseline`, `ScenarioSpecificEvidence`, `TelemetryFilePointers`
- `src/contracts/metadata.py` — `ScenarioMetadata` (top-level)
- `src/contracts/CONTRACT_SYNC.md` — sync procedure documentation
- `docs/contract-spec.md` — verbatim copy of the agent's `docs/12-shared-contract.md`

**Estimated:** ~390 lines of Pydantic code, received as-is.

**Validation:**
- `python -c "from contracts.version import CONTRACT_VERSION; print(CONTRACT_VERSION)"` prints `1.0.0`.
- `python -c "from contracts.metadata import ScenarioMetadata; print(ScenarioMetadata.model_fields.keys())"` succeeds.

### A.2 — Project skeleton + constants (Day 1)

**Files to create:**

```
src/
├── __init__.py
├── generator/
│   ├── __init__.py
│   ├── constants.py          # DATA_WINDOW_START_UTC, INTERVAL_MINUTES, etc.
│   ├── spec_loader.py        # load + validate docs/internal/scenarios/NN.spec.yaml
│   ├── metadata.py           # programmatic ScenarioMetadata builder
│   ├── terraform.py          # Jinja-based main.tf renderer
│   └── templates/
│       ├── wrapper.tf.j2
│       ├── compute.tf.j2
│       ├── database.tf.j2
│       ├── cache.tf.j2
│       └── network.tf.j2
└── qa/
    ├── __init__.py
    └── qa_validator.py       # stub for Phase B
```

**`src/generator/constants.py`** should encode the sampling envelope from `docs/internal/generation-conventions.md` §1:

```python
from datetime import datetime, timedelta, timezone

DATA_WINDOW_START_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
DATA_WINDOW_DAYS = 14
INTERVAL_MINUTES = 15
RECORDS_PER_TIER = 1344  # 14 * 96
WEEKDAY_DATES = ["2026-05-01", "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07",
                 "2026-05-08", "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14"]
WEEKEND_DATES = ["2026-05-02", "2026-05-03", "2026-05-09", "2026-05-10"]
```

### A.3 — Metadata generator (Day 2)

**File:** `src/generator/metadata.py`

**Inputs:**
- A loaded `NN.spec.yaml` (from `spec_loader.py`).
- Optionally the produced telemetry arrays (for `TelemetryFilePointers` — but the field is static, so this is just for documentation).

**Output:** A Pydantic-validated `ScenarioMetadata` object, serialized to `scenarios/NN/metadata.json`.

**Required behavior** (per `docs/internal/generation-methodology.md` §4 and `docs/internal/generation-conventions.md`):

- Populate `contract_version` from `src/contracts/version.py:CONTRACT_VERSION`.
- Set `generated_at` to current UTC timestamp.
- Map spec's `scenario_type` string → `ScenarioType` enum.
- Map spec's `target_recommendation.action_category` → `ActionCategory` enum (allow `null`).
- Map spec's `tier_topology.<tier>` — emit `None` if `present: false` or absent.
- Build `cost_baseline.by_tier` with all four tier keys; absent tiers get `0.0`. Auto-compute `monthly_cost_total_usd = sum(by_tier.values())`, override spec value.
- Derive `business_context.sla_target_description` from structured fields per generation-conventions.md §6: `f"{availability_pct}% availability, P95 < {p95_ms}ms"`.
- `telemetry_file_pointers` → always `TelemetryFilePointers()` defaults.
- `infrastructure_file` → always `"main.tf"`.

**Tests** (`tests/generator/test_metadata.py`):
- Builds valid `metadata.json` for scenario 01 (single-tier, no cache, no network).
- Builds valid `metadata.json` for scenario 06 (healthy, all four tiers).
- Builds valid `metadata.json` for scenario 17 (diagnostic deferral, null action_category).
- `cost_baseline` sum invariant holds.
- `sla_target_description` matches the derivation formula.

### A.4 — Terraform Jinja renderer (Day 3)

**File:** `src/generator/terraform.py`

**Inputs:** A `ScenarioMetadata` object (the just-produced one).

**Output:** `scenarios/NN/main.tf` — valid HCL that parses against `python-hcl2`.

**Required behavior:**

- Render one block per tier marked `present: true` in `tier_topology`, using the per-tier-type Jinja templates.
- Every resource tagged with `Application = "appNN"` and `Tier = "<tier_name>"`.
- Compute → `aws_instance` or `aws_autoscaling_group` (depending on `scaling_policy`).
- Database → `aws_db_instance` + replicas as separate resources.
- Cache → `aws_elasticache_cluster`.
- Network → `aws_lb` + `aws_lb_target_group` with `load_balancing_algorithm_type` set per `algorithm`.
- For multi-tier scenarios: `aws_security_group_rule` blocks between relevant tiers with descriptive `description` fields.

**Validation:**
- After render, parse with `python-hcl2`; assert every tier marked present has at least one matching `aws_*` resource.
- Assert tags `Application` and `Tier` are present on every resource.
- Assert load-balancer scenarios (Scenarios 5, 9, 10, 11, 14, 15) have `load_balancing_algorithm_type`.

**Tests** (`tests/generator/test_terraform.py`):
- Scenario 01 (compute-only) — emits 1 aws_instance or asg, tagged correctly.
- Scenario 07 (compute + db + cache) — three tier blocks, plus security group rules.
- Scenario 05 (load balancer round_robin) — algorithm is set on target group.

### Phase A exit criterion

```bash
$ python -m generator.cli build-metadata 07
✅ Wrote scenarios/07/metadata.json (contract version 1.0.0)

$ python -m generator.cli build-terraform 07
✅ Wrote scenarios/07/main.tf (parses cleanly against python-hcl2)
```

Both files validate. Telemetry files are still missing — that's Phase B.

---

## Phase B — Pipeline (Days 4–7)

**Goal:** Wire up the LLM-driven Pass 1 and Pass 2 generators, plus the semantic QA validator. By end of Phase B, you can produce a complete, contract-and-semantic-valid scenario folder for any of the 18 scenarios.

### B.1 — LLM client wrapper (Day 4 morning)

**File:** `src/generator/llm_client.py`

A thin wrapper around the Anthropic SDK that:
- Takes a prompt template path + a dict of substitutions.
- Loads template, performs `.format(**substitutions)`.
- Calls `messages.create()` with `temperature=0.3`, returns the response text.
- Strips any accidental markdown fencing if the model emits it despite the prompt.
- Logs the prompt + response to `intermediates/NN/passN_llm_log.json` for debugging.

Model: Sonnet 4.6 for Pass 1 and Pass 2; Opus 4.6 for the smoke test recommendation; Haiku 4.5 for the smoke-test judge. See `src/generator/constants.py` for the wired-up assignments and per-choice rationale, and "Model strategy and cost" below for the budget breakdown.

### B.2 — Pass 1 generator (Day 4 afternoon)

**File:** `src/generator/pass1.py`

**Inputs:** Loaded scenario spec.

**Output:** `intermediates/NN/pass1.json` — `{scenario_id, pass: 1, Compute_Metrics, Database_Metrics, Cache_Metrics, Network_Metrics}`.

**Flow:**

1. Read `prompts/pass1.txt`.
2. Build the substitutions dict:
   - `scenario_id`, `scenario_name`, `scenario_type`
   - `tiers_required`: list of tiers where `tier_topology.<tier>.present == true`
   - `business_context_description`, `sla_target_description`, `criticality`
   - `tier_topology_description`: prose summary of the topology (helper formatter)
   - `pass1_metrics_block`: YAML-flavored dump of the spec's `pass1_metrics`
   - `healthy_baselines_block`: contents of `docs/internal/healthy-baselines.md` §"Compute / Database / Cache / Network tier" sections
3. Call the LLM.
4. Parse response as JSON.
5. For each non-empty tier array, validate each record against the corresponding Pydantic model (`ComputeRecord`, etc.). On any failure, retry up to 3× with diagnostic appended.
6. Assert record count == 1344 (or N×1344 for Scenario 5 per-instance).
7. Assert timestamp continuity (15-min, monotonic, starts at `DATA_WINDOW_START_UTC`).
8. Write `intermediates/NN/pass1.json`.

**Chunking fallback:** If the response exceeds the model's output budget, chunk by day (96 records per tier per call) with continuity via tail values.

### B.3 — Pass 2 generator (Day 5)

**File:** `src/generator/pass2.py`

**Inputs:** `intermediates/NN/pass1.json` + loaded scenario spec.

**Output:** `intermediates/NN/pass2.json` + `scenarios/NN/correlation_evidence.json`.

**Flow:**

1. **Pass-through case.** If `spec.pass2_correlations` is empty:
   - Copy Pass 1 JSON to `pass2.json` with `"pass": 2`.
   - Write `correlation_evidence.json: []`.
   - No LLM call.
   - Return.

2. **Correlation case.** Read `prompts/pass2.txt`. Build substitutions:
   - `scenario_id`, `scenario_name`, `scenario_type`
   - `pass1_json`: the full Pass 1 JSON output
   - `pass2_correlations_block`: YAML-flavored dump of `spec.pass2_correlations`
   - `pass1_baseline_summary`: per-metric range summary from `spec.pass1_metrics` so the LLM can compute relative adjustments
3. Call the LLM.
4. Parse response as JSON.
5. **Enforce the Pass 2 invariance contract:**
   - For every tier NOT in `correlation.effect.tier`: assert Pass 2 array == Pass 1 array bit-exact.
   - For tiers that ARE correlation effect targets, in time windows where no trigger condition is satisfied: assert records match Pass 1 exactly (timestamp + every field).
   - Timestamps NEVER changed.
6. Write `intermediates/NN/pass2.json`.
7. **Compute `correlation_evidence.json`** programmatically from the Pass 2 telemetry:
   - For each correlation rule, locate the trigger and effect metrics in the time series.
   - Compute Pearson correlation coefficient across the 14-day window.
   - Determine lag (typically 0 minutes for "same window" rules).
   - Compute alignment score (proportion where both metrics' z-scores moved in the same direction).
   - Emit a `CorrelationPair` record.
8. Write `scenarios/NN/correlation_evidence.json` (validates against the Pydantic model).

### B.4 — Splitter: Pass 2 → consumer-facing telemetry files (Day 5)

**File:** `src/generator/splitter.py`

Pass 2's wire format uses `Compute_Metrics` / `Database_Metrics` / etc. (capitalized). The consumer-facing files are lowercase: `compute_telemetry.json`, etc.

**Function:** Given `intermediates/NN/pass2.json`, write four files:
- `scenarios/NN/compute_telemetry.json` ← `Compute_Metrics` (empty array if no compute tier)
- `scenarios/NN/database_telemetry.json` ← `Database_Metrics`
- `scenarios/NN/cache_telemetry.json` ← `Cache_Metrics`
- `scenarios/NN/network_telemetry.json` ← `Network_Metrics`

### B.5 — QA validator (Day 6)

**File:** `src/qa/qa_validator.py`

Implements every check in [`docs/internal/generation-qa.md`](docs/internal/generation-qa.md). Two layers:

**Contract layer.** Re-runs every check from `docs/contract-spec.md` §12.6. Defense in depth.

**Semantic layer.** 10 checks from `generation-qa.md`:
- 3.1 Healthy-band check
- 3.2 Pattern-frequency check (11-of-14, 10-of-10 weekday)
- 3.3 Weekend behavior check
- 3.4 Pass 2 invariance check (cross-validate against `intermediates/NN/pass1.json`)
- 3.5 Correlation timing check
- 3.6 Correlation magnitude check
- 3.7 No-spurious-correlation check
- 3.8 SLA description derivation check
- 3.9 Cost baseline sum invariant
- 3.10 Per-instance breakdown consistency (Scenario 5 only)

**Output:** `intermediates/NN/qa_report.json` per `generation-qa.md` §4. Per-scenario overall pass/fail.

A scenario folder is **only committed to `scenarios/NN/` when both layers pass**.

### B.5.5 — Smoke-test the two pilot scenarios (Day 6, after QA)

After Scenarios 01 and 07 pass the QA validator, run the scenario-quality smoke test on them as an early sanity check (full smoke test of all 18 happens in Phase C). Confirms the pipeline produces solvable scenarios before scaling to all 18.

See `docs/internal/scenario-quality-smoke-test.md` for the procedure.

### B.6 — End-to-end on 2 scenarios (Day 7)

Run the full pipeline on Scenarios **01** (single-tier, simplest) and **07** (cross-tier with correlations, most representative).

```bash
$ python -m generator.cli build 01
[1/5] Pass 1 ... ✅
[2/5] Pass 2 ... ✅ (no correlations, pass-through)
[3/5] Splitter ... ✅
[4/5] Metadata ... ✅
[5/5] Terraform ... ✅
QA ... ✅ contract: 8/8, semantic: 10/10
Committed scenarios/01/

$ python -m generator.cli build 07
[1/5] Pass 1 ... ✅
[2/5] Pass 2 ... ✅ (1 correlation rule applied)
[3/5] Splitter ... ✅
[4/5] Metadata ... ✅
[5/5] Terraform ... ✅
QA ... ✅ contract: 8/8, semantic: 10/10
Committed scenarios/07/
```

Iterate Pass 1 and Pass 2 prompts as needed until both scenarios pass cleanly. This is the prompt-iteration window — expect to adjust `prompts/pass1.txt` and `prompts/pass2.txt` here.

### Phase B exit criterion

Scenarios 01 and 07 are committed under `scenarios/`, all seven files per scenario validate, QA reports show 0 failures in either layer.

---

## Phase C — Full run + handoff (Days 8–10)

### C.1 — Generate all 18 scenarios (Days 8–9)

```bash
$ python -m generator.cli build-all
[scenario 01] ✅
[scenario 02] ✅
...
[scenario 18] ✅

18/18 scenarios committed.
```

**Expected friction:**
- Scenarios with multiple correlation rules (08, 09, 10, 13, 17) will need more Pass 2 prompt iteration.
- Scenario 05 (per-instance records) — 10,752 records vs 1,344 puts this near the output-token ceiling for any single Sonnet call. Likely needs day-chunked generation per `generation-methodology.md` §2 ("Chunking for context-limited models"). Single biggest cost driver of the build.
- Scenario 17 (diagnostic deferral) has a correlation-without-causation pattern that's subtle; expect 2–3 iteration rounds.

### C.2 — Sweep validation (Day 10 morning)

Run the QA validator across all 18 scenarios in batch. Generate an aggregate report. Investigate any scenarios that pass the validator but look weird on manual inspection.

### C.2.5 — Scenario-quality smoke test (Day 10 morning)

Run the lightweight single-LLM-call smoke test across all 18 scenarios:

```bash
$ python -m qa.smoke_test --all
```

Per `docs/internal/scenario-quality-smoke-test.md`: builds a prompt per scenario containing metadata (minus target), telemetry summaries, correlation evidence, and main.tf; asks a single Opus 4.6 call to produce a `TargetRecommendation` (strongest available baseline); compares against the spec's target on four fields (finding_type, primary_tier, action_category, specific_change). The specific_change comparison uses Haiku 4.5 as a one-line LLM-as-judge.

**Expected outcome:** YELLOW or GREEN.
- ≥14 of 18 pass cleanly → GREEN, proceed.
- 12–13 pass → YELLOW, spot-check the failures.
- ≤11 pass → RED, investigate data quality.

Some scenarios are deliberately hard for a single-call LLM — restraint (6, 14, 16, 18), diagnostic deferral (17), SLA review (15), and the harder cross-tier cases. Partial fails on those are expected and acceptable. The smoke test catches *unexpected* fails (e.g., Scenario 01 being unsolvable would indicate a real data problem).

**File:** `src/qa/smoke_test.py` (~150 lines). LLM cost: ~$1.45 for the full 18-scenario smoke test on Opus 4.6.

### C.3 — Handoff to agent project (Day 10 afternoon)

- Push the 18 scenario folders to the shared repo / handoff package the agent project expects.
- Sanity-check: agent project's Input Harness ingests each of the 18 scenarios cleanly.
- File any issues the Input Harness surfaces back to this project for fix-up.

### Phase C exit criterion

All 18 scenarios committed under `scenarios/`. All pass contract and semantic QA. Smoke test result is GREEN (≥14 pass) or YELLOW (12–13 pass with documented exceptions for hard scenarios). Agent project's Input Harness accepts each one without rejection.

---

## Cross-cutting concerns

### Prompt iteration

`prompts/pass1.txt` and `prompts/pass2.txt` are starting points. Expect to revise them during Phase B testing. When a prompt change improves Scenario N, re-run the affected scenarios (not just N — adjacent scenarios may regress) and re-validate.

### Determinism

LLM passes are non-deterministic at non-zero temperature. Re-running produces equivalent scenarios (same structure, same patterns) with different specific values. The committed `scenarios/NN/` files are the canonical artifact. Don't re-generate before handoff unless something's broken.

### Model strategy and cost

**Model assignments** (wired up in `src/generator/constants.py`):

| Stage | Model | Why |
|---|---|---|
| Pass 1 (telemetry generation) | Sonnet 4.6 | Reliable adherence to ranges, time patterns, 11-of-14 rule. Fewer Phase B iteration cycles than Haiku. |
| Pass 2 (correlation injection) | Sonnet 4.6 | Pass 2 invariance demands precise rule-following on large JSON. Sonnet is the right tier; Haiku is too risky on invariance. |
| Smoke test recommendation | Opus 4.6 | Strongest available baseline check — if even Opus can't solve a scenario, the multi-agent system's depth is genuinely needed. Cost is trivial (~$1.45). |
| Smoke test LLM-as-judge | Haiku 4.5 | One-line "substantively the same change? YES/NO". Trivial reasoning, trivial cost. |

**Per-stage cost breakdown** (with prompt caching enabled — caching is automatic via the prompt template structure; see `docs/internal/generation-methodology.md` §8):

| Stage | Input cost | Output cost | Subtotal |
|---|---|---|---|
| Pass 1 (Sonnet, 18 scenarios + ~20 pilot iterations) | ~$0.66 (cached) | ~$100.50 (6.7M tokens × $15/MTok) | **~$101** |
| Pass 2 (Sonnet, 6 correlation scenarios + ~10 pilot iterations) | ~$3.06 (cached) | ~$51.00 (3.4M tokens × $15/MTok) | **~$54** |
| Smoke test (Opus, 18 scenarios + ~5 retries) | ~$1.15 | ~$0.30 | **~$1.45** |
| Smoke test judge (Haiku, 18 calls) | trivial | trivial | **~$0.01** |
| **Project total** | | | **~$157** |

**Budget against $150 credit.** The above lands ~$7 over the $150 ANTHROPIC credit. **Tight — recommend enabling Batch API.**

**With Batch API** (50% off everything — Phase B.6 deliverable below): project total drops to **~$79**, comfortably under budget with $70+ headroom for unexpected re-runs or extra Phase B iteration.

Output tokens dominate the cost — Pass 1 alone is ~$100 of the budget because each scenario emits ~120K tokens of telemetry JSON. Prompt caching only helps input; it saves ~$8 across the build. Batch API is the dominant lever; recommended path is "Batch + caching." Per-scenario LLM cost reports are logged to `intermediates/NN/passN_llm_log.json` (token counts + cost estimate per call) — track actual against this estimate as the build progresses.

### Phase B.6 — Batch API support (recommended addition)

The 18-scenario build is an asynchronous batch workload by nature, not interactive. Anthropic's Batches API runs the same calls at 50% pricing with up-to-24-hour completion. For our use case, "completion within 30 minutes" is realistic.

Add a code path in `src/generator/pipeline.py` and `src/generator/llm_client.py` that submits to the Batches API when `DATAGEN_BATCH_MODE=true` is set (the env-var name is defined in `constants.py:BATCH_MODE_ENV_VAR`). Behavior:

- Pipeline collects Pass 1 / Pass 2 / smoke-test calls into batches by stage.
- Submits each batch to Anthropic's batch endpoint.
- Polls for completion.
- On completion, applies the same validation + QA logic as the interactive path.

Estimated implementation effort: ~50 lines in `llm_client.py` (a `BatchClient` companion class) + ~30 lines in `pipeline.py` (collect-then-submit orchestration). The existing validation and QA logic is reused unchanged.

**With Batch API enabled, the build runs in ~30 minutes for ~$79.** Without it, the build runs ~5–10 minutes for ~$157 (over budget).

### Testing strategy

- **Phase A:** unit tests on metadata generator + Terraform renderer (deterministic, easy to test).
- **Phase B:** integration tests on the full pipeline for 1 scenario; LLM responses captured for offline replay.
- **Phase C:** no new tests; the QA validator IS the test.

### Documentation

Update `docs/internal/generation-methodology.md` if the operational details turn out different from spec'd (e.g., chunking strategy ends up different). Update `CHANGELOG.md` at the end of each phase.

---

## What ships at the end of Phase C

A self-contained data-gen project containing:

- The generation pipeline source code under `src/generator/` and `src/qa/`.
- The shared contract package under `src/contracts/` (synced from agent project).
- The 18 scenario folders under `scenarios/` — the deliverable.
- The prompt scaffolds under `prompts/`.
- The full documentation under `docs/` (the data-generation-plan, the synced contract spec, the alignment review history).
- `docs/internal/` containing working materials (gitignored).

The agent project's Phase 3 (Tier Specialists) can begin immediately upon receiving the 18 scenario folders.

---

## What ships separately or later

- Pydantic contract package — agent project owns canonical; this project syncs.
- `intermediates/NN/` — debug-only artifacts; not committed.
- Documentation iterations beyond initial drafts — open-ended.

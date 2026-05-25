# Cloud Governance — Data Generation Plan

**Document type:** Project-level plan for the data-generation sub-project.
**Version:** v1.0 — 2026-05-25 (paired with shared contract `1.0.0`).
**Status:** Pre-implementation. Supersedes `Cloud_Governance_Dataset_Generation_Plan_v3.pdf`.

This document is the plan of record for the data-generation sub-project. It explains what this project produces, why it exists, how it is structured, and how each piece of work fits together. It is written for the engineers (and LLM tooling) that will implement the pipeline.

---

## 1. What this project produces

The data-generation pipeline produces 18 synthetic scenarios — each one a self-contained folder of seven files — that the cloud-governance multi-agent system consumes for evaluation. The output directory:

```
scenarios/
├── 01/  (Chronic Underutilization)
│   ├── metadata.json
│   ├── compute_telemetry.json
│   ├── database_telemetry.json
│   ├── cache_telemetry.json
│   ├── network_telemetry.json
│   ├── correlation_evidence.json
│   └── main.tf
├── 02/  (Spiky Compute Load)
│   └── ...
...
└── 18/  (Mostly Healthy with Minor Inefficiency)
    └── ...
```

The shape of every file is dictated by the **shared data contract** specified in `docs/contract-spec.md` (a synchronized verbatim copy of the agent project's canonical `docs/12-shared-contract.md`). The contract is enforced by Pydantic models in `src/contracts/`, which both projects use to validate.

Each scenario is **reverse-engineered from a known target recommendation**. This is the deliberate evaluation device that makes the agent system's correctness measurable — ground-truth recommendations let R1–R5 rubric scoring be objective.

---

## 2. Project boundary

This project owns:

- The **producer side**. Everything from "I have a contract spec and 18 scenario narratives" through "I have 18 scenario folders ready for the agent to consume."
- The **scenario design**. Pass 1 metric ranges, Pass 2 correlation rules, time patterns, healthy baselines, before/after evidence, target recommendations.
- The **generation pipeline**. Pass 1 + Pass 2 LLM synthesis, Terraform Jinja rendering from metadata, generation-side semantic QA.
- The **prompt design**. The actual scaffolds in `prompts/pass1.txt` and `prompts/pass2.txt`.

This project does **not** own:

- The data contract itself. That is owned canonically by the agent project (`cloud-governance-agent/docs/12-shared-contract.md` and `src/contracts/`). This project receives a verbatim copy and conforms.
- The Data Service. That is the agent project's read layer over scenario folders.
- The agent's healthy-band thresholds for its `breaches` operation. The agent project picks those; this project shares its baselines (`docs/internal/healthy-baselines.md`) as a coordination note so both sides converge.

The boundary is the contract. Producer fills the seven files per scenario; consumer reads them through its Data Service. Everything else on this side of the boundary is data-gen's autonomy.

---

## 3. Why this project exists

Three reasons, in order of importance:

**Ground truth.** Real cloud telemetry does not come with known-correct recommendations attached. To evaluate whether a multi-agent recommender is making good decisions, the evaluation set has to be reverse-engineered from targets. Synthetic data is the only viable option.

**Coverage of edge cases.** The 18 scenarios are designed to deterministically exercise the cases that distinguish a sophisticated recommender from a simple optimization tool: restraint (don't recommend changes when none are warranted), diagnostic deferral (recommend investigation when root cause is ambiguous), cross-tier synthesis (identify cause-effect across tiers), and trade-off reasoning (cost vs performance vs reliability when they pull in different directions). Real telemetry would not deterministically exercise these.

**Decoupling from cloud account state.** A portfolio implementation must run locally on any machine without an AWS account, billing setup, or live cluster. Synthetic data makes that true.

---

## 4. The 18-scenario design at a glance

Full per-scenario specifications live in `docs/internal/scenarios/01.spec.yaml` through `18.spec.yaml`. The summary table:

| # | Scenario | Type | Tiers | Target action |
|---|---|---|---|---|
| 01 | Chronic Underutilization | single_tier_negative | Compute | Rightsizing (down) |
| 02 | Spiky Compute Load | single_tier_negative | Compute | Scaling policy change |
| 03 | Over-provisioned Database | single_tier_negative | Database | Rightsizing (down) |
| 04 | Database Connection Bottleneck | single_tier_negative | Database | Pool sizing + query optimization |
| 05 | Load Balancer Inefficiency | single_tier_negative | Compute | Load balancer reconfiguration |
| 06 | Healthy Application | healthy | All four | No action |
| 07 | Cache Miss Cascade | cross_tier_negative | Compute + DB + Cache | Cache optimization |
| 08 | Database Bottleneck Impact | cross_tier_negative | Compute + DB | Query optimization + replicas |
| 09 | Peak Hours Cost vs Reliability | cross_tier_negative | Compute + DB + Network | Scheduled scaling |
| 10 | Network Latency Impact | cross_tier_negative | Compute + Network | Network topology change |
| 11 | Multi-Tier Over-provisioning | cross_tier_negative | Compute + DB + Network | Rightsizing (all tiers) |
| 12 | Healthy Compute, Problematic Database | mixed | Compute + DB | Rightsizing (DB only) |
| 13 | Compute Spike + Database Strain | cross_tier_negative | Compute + DB | Scaling + replicas + pool |
| 14 | Good Performance, High Cost | mixed | Compute + DB + Network | Rightsizing (compute + DB) |
| 15 | Reliability Focused Over-provisioning | mixed | Compute + DB + Network | SLA review |
| 16 | Partial Optimization | single_tier_mild_negative | Compute + DB + Network | Minor compute adjustment |
| 17 | Cross-Tier Performance Degradation | diagnostic_deferral | Compute + DB + Network | Recommend trace analysis |
| 18 | Mostly Healthy with Minor Inefficiency | mostly_healthy | Compute + DB + Network | Minor compute adjustment |

Each scenario tests a specific evaluation property. The Restraint scenarios (06, 16, 18) test that the system can return "no action" when warranted. The Diagnostic-deferral scenario (17) tests that the system can recognize when root cause is ambiguous. The Cross-tier scenarios test the Cross-Tier Evaluator's synthesis. The Mixed scenarios test that the system doesn't recommend across the board when only some tiers need work.

---

## 5. Pipeline architecture

The pipeline runs in four sequential stages per scenario:

```
docs/internal/scenarios/NN.spec.yaml
            │
            ▼
   ┌─────────────────┐
   │  Pass 1         │   LLM synthesis of base per-tier telemetry.
   │  (independent   │   No cross-tier reasoning. Produces four
   │  per-tier)      │   telemetry JSON arrays per scenario.
   └─────────────────┘
            │
            ▼
   ┌─────────────────┐
   │  Pass 2         │   LLM modifies Pass 1 output surgically to
   │  (correlation   │   inject cross-tier correlations per scenario
   │  injection)     │   spec. Pass-through for non-correlated scenarios.
   └─────────────────┘                       Emits correlation_evidence.json.
            │
            ▼
   ┌─────────────────┐
   │  Metadata       │   Programmatic — reads spec.yaml + telemetry,
   │  generator      │   produces Pydantic-validated metadata.json.
   └─────────────────┘
            │
            ▼
   ┌─────────────────┐
   │  Terraform      │   Jinja template per tier type renders
   │  renderer       │   main.tf from metadata.json.tier_topology.
   └─────────────────┘
            │
            ▼
   ┌─────────────────┐
   │  QA validator   │   Contract validation (§12.6) +
   │                 │   semantic checks (generation-qa.md).
   └─────────────────┘
            │
            ▼
   scenarios/NN/   (seven files, contract-conformant)
```

Detailed mechanics for each stage are in `docs/internal/generation-methodology.md`. Prompt scaffolds for Pass 1 and Pass 2 are in `prompts/pass1.txt` and `prompts/pass2.txt`.

---

## 6. Why two passes for telemetry

The single biggest design choice in the telemetry side of the pipeline. No amount of prompt engineering reliably produces, in a single LLM generation, both (a) clean per-tier base time-series with realistic daily patterns AND (b) correct, tightly-coupled cross-tier correlations. The model is competent at either task in isolation but conflates them when asked to do both at once.

Pass 1 produces the independent base time-series for each tier. Pass 2 takes the exact Pass 1 output and surgically adds cross-tier correlations only for the scenarios that require them, preserving every Pass 1 signal without modification. Scenarios that do not require correlations pass through Pass 2 unchanged.

This is a generation-side mechanical decision; it has no consumer impact. The consumer sees only the final post-Pass-2 telemetry. Pass 1 / Pass 2 intermediates are kept under `intermediates/NN/` during pipeline runs for debugging and are not part of the deliverable.

---

## 7. Sampling parameters

All scenarios share the same sampling envelope. This is hard-coded into the pipeline and validated by the QA step.

| Parameter | Value |
|---|---|
| Interval | 15 minutes |
| Records per tier per day | 96 |
| Days | 14 (2 weeks) |
| Total records per non-empty tier | **1,344** |
| Start timestamp | **2026-05-01T00:00:00Z** (Monday) |
| Timezone | UTC |
| Timestamp format | ISO 8601 (`2026-05-01T00:00:00Z`) |

The fact that the data window always starts on a Monday matters: per `generation-conventions.md`, "weekday" and "weekend" are well-defined relative to the start date (weekdays = days 1–5 and 8–12; weekends = days 6–7 and 13–14), which lets time-pattern rules be expressed without ambiguity.

---

## 8. Healthy baselines

`docs/internal/healthy-baselines.md` defines, for every metric in the contract's telemetry schema, the typical operating range a well-sized healthy tier should sit in. Pass 1 uses these to know what "healthy" means; the QA validator uses them to confirm healthy scenarios stay inside the band; per-scenario specs use them as the default that scenario-specific ranges override.

The healthy baselines are this project's interpretation. They are shared with the agent project as a coordination note so the agent's Data Service breach thresholds can match, but the agent project picks its own thresholds independently — the contract does not specify thresholds.

---

## 9. The "11 of 14" rule

Where a scenario specifies a recurring pattern (e.g., "weekday business-hour spikes"), the pattern must hold on at least **11 of 14 days**. This threshold is high enough that the pattern is statistically unambiguous to the consumer, while low enough to leave room for realistic day-to-day variation.

For weekday-only patterns, the threshold tightens: the pattern must hold on all 10 weekdays. Weekends are explicitly exempt from the 11-of-14 count for weekday-only patterns. Each scenario spec marks whether a pattern is "weekday-only" or "all-days."

---

## 10. The reverse-engineering principle

Every scenario was built in this order:

1. **A target recommendation was written first.** (e.g., "Switch t3.large × 8 to t3.medium × 4. Expected savings: 62% on monthly compute cost (~$2,850) with no impact on SLA.")
2. **The business context, SLA, current configuration, and scenario metadata were chosen** to make that recommendation appropriate.
3. **The telemetry metric ranges, time patterns, and (where relevant) cross-tier correlations were specified** to be the evidence trail that leads naturally to the recommendation.

The dataset's job is to make each target recommendation a reasoned conclusion the agent can reach, not a leap. The R3 specificity rubric scores how closely the agent's recommendation matches the target's specific quantities (instance classes, replica counts, percentage savings, pool sizes). Per-scenario `scenario_specific_evidence` (top queries, top cache keys, per-instance breakdown) plus `before_after_evidence` (specific config_before / config_after / outcome quantities) are the grounding that makes specific recommendations possible.

---

## 11. Phase plan

The data-generation work is sequenced in three phases, paired with the agent project's four-phase build plan (the agent's Phase 1 runs in parallel with this project's full pipeline).

### Phase A — Foundations (Week 1, days 1–3)

- Receive `src/contracts/*.py` and `docs/contract-spec.md` from the agent project (Phase 1 deliverable of the agent build plan).
- Confirm Pydantic models load and validate against a hand-crafted test scenario folder.
- Implement the metadata generator (programmatic — no LLM). Pass it a `spec.yaml` + four telemetry arrays + correlation evidence, get a Pydantic-validated `metadata.json` back.
- Implement the Terraform Jinja renderer. Per-tier-type templates that read `tier_topology` and emit valid HCL.

### Phase B — Pipeline (Week 1, days 4–7)

- Implement Pass 1 generator. LLM-driven, one scenario at a time, emits four telemetry JSON arrays per scenario. Validates each array against the Pydantic model on construction.
- Implement Pass 2 generator. Reads Pass 1 output + scenario spec's correlation rules, emits correlated telemetry + `correlation_evidence.json`. For correlation-free scenarios, passes Pass 1 through unchanged.
- Implement the QA validator (`src/qa/qa_validator.py`). Runs contract validation plus the semantic checks in `generation-qa.md`.
- End-to-end test on 1–2 scenarios. Iterate Pass 1 and Pass 2 prompts until output passes QA.

### Phase C — Full run + handoff (Week 1, days 8–10, overlapping into Week 2)

- Run the full pipeline against all 18 scenarios.
- Each scenario folder validated by contract + semantic QA before being accepted.
- Run the **scenario-quality smoke test** as a final gate before handoff — a single-LLM-call sanity check that the generated data is sufficient for a baseline LLM to reach the target recommendation. See `docs/internal/scenario-quality-smoke-test.md`. Expected pass rate: 12–14 of 18 (some scenarios are deliberately hard for a single-call baseline).
- Hand 18 scenarios to the agent project for ingestion testing.
- Iterate as the agent project's Input Harness surfaces any edge cases.

End of Phase C: 18 scenarios in `scenarios/01/` through `scenarios/18/`, all passing contract and semantic QA, smoke test green or yellow with documented exceptions, ready for agent ingestion.

---

## 12. Deliverables

What this sub-project ships at the end of its build phase:

- **The 18 scenario folders** under `scenarios/`, each with seven files, all contract-conformant.
- **The generation pipeline source** under `src/generator/` and `src/qa/`. Reproducible — running it again should produce equivalent scenarios (modulo LLM non-determinism in numeric values; structure stays identical).
- **The 18 scenario specs** under `docs/internal/scenarios/`. The narrative source-of-truth that drives generation.
- **The supporting internal docs** under `docs/internal/`: healthy baselines, generation methodology, generation conventions, generation QA.
- **The prompt scaffolds** under `prompts/`.
- **The synchronized contract spec** (`docs/contract-spec.md`) and Pydantic package (`src/contracts/`), in sync with the agent project's canonical versions.

---

## 13. Repository structure

```
cloud-governance-data-gen/
├── docs/
│   ├── data-generation-plan.md        # this document
│   ├── contract-spec.md               # synced from agent project (read-only)
│   └── internal/                      # data-gen-owned, never reaches consumer
│       ├── healthy-baselines.md
│       ├── generation-methodology.md
│       ├── generation-conventions.md
│       ├── generation-qa.md
│       └── scenarios/
│           ├── 01.spec.yaml
│           ├── 02.spec.yaml
│           ├── ...
│           └── 18.spec.yaml
├── src/
│   ├── contracts/                     # synced from agent project (Phase A)
│   │   ├── __init__.py
│   │   ├── version.py
│   │   ├── enums.py
│   │   ├── telemetry.py
│   │   ├── evidence.py
│   │   ├── configurations.py
│   │   ├── recommendation.py
│   │   ├── narrative.py
│   │   └── metadata.py
│   ├── generator/
│   │   ├── pass1.py                   # LLM Pass 1 driver
│   │   ├── pass2.py                   # LLM Pass 2 driver
│   │   ├── metadata.py                # programmatic metadata.json builder
│   │   ├── terraform.py               # Jinja-based main.tf renderer
│   │   └── llm_client.py              # thin Anthropic SDK wrapper
│   └── qa/
│       └── qa_validator.py            # contract + semantic checks
├── prompts/
│   ├── pass1.txt
│   └── pass2.txt
├── intermediates/                     # gitignored — pass1/pass2 raw output for debugging
│   └── NN/
│       ├── pass1.json
│       └── pass2.json
└── scenarios/                         # output — consumer reads from here
    ├── 01/
    │   ├── metadata.json
    │   ├── compute_telemetry.json
    │   ├── database_telemetry.json
    │   ├── cache_telemetry.json
    │   ├── network_telemetry.json
    │   ├── correlation_evidence.json
    │   └── main.tf
    └── ...
```

Nothing in `docs/internal/`, `src/generator/`, `src/qa/`, `prompts/`, or `intermediates/` ever crosses the project boundary. The consumer only reads from `scenarios/NN/`.

---

## 14. Coordination with the agent project

Two small ongoing coordination obligations:

**Contract sync.** When the agent project updates `12-shared-contract.md` and/or `src/contracts/`, this project's `docs/contract-spec.md` and `src/contracts/` are updated to match per the procedure in `src/contracts/CONTRACT_SYNC.md`. After a minor or major contract version bump, the 18 scenarios are regenerated.

**Field-semantics conventions.** Two contract fields (`TopQuery.count`, `TopCacheKey.hit_count`/`miss_count`) carry no time unit in the Pydantic spec. This project establishes the convention ("total executions over the 14-day data window," see `generation-conventions.md` §3) and shares it with the agent project as a one-time coordination note so the agent's reasoning matches. This is documentation-only; no contract change needed.

Everything else is internal.

---

## 15. Document map

| For | Read |
|---|---|
| Project overview | `docs/data-generation-plan.md` (this document) |
| Consumer-facing contract | `docs/contract-spec.md` |
| What "healthy" means per metric | `docs/internal/healthy-baselines.md` |
| How Pass 1 / Pass 2 / metadata / Terraform generation work | `docs/internal/generation-methodology.md` |
| Field-semantics conventions and other generation rules | `docs/internal/generation-conventions.md` |
| Generation-side QA checks (data matches spec) | `docs/internal/generation-qa.md` |
| Scenario-quality smoke test (single-LLM solvability check) | `docs/internal/scenario-quality-smoke-test.md` |
| Per-scenario specs (narrative + ranges + correlations + target) | `docs/internal/scenarios/NN.spec.yaml` |
| Pass 1 / Pass 2 LLM prompt templates | `prompts/pass1.txt`, `prompts/pass2.txt` |

---

## 16. Out of scope

Named so no one wonders later:

- **Real telemetry integration.** This project produces synthetic data only.
- **Continuous regeneration.** Scenarios are generated once per contract version, then frozen.
- **Multi-app scenarios.** Each scenario is one application. Cross-application patterns are out of scope.
- **The agent system itself.** This project produces input; the agent project consumes it. They are independent codebases coordinated by the shared contract.
- **Production-grade Terraform.** `main.tf` files are minimal, parseable stubs sufficient to exercise the agent's System Mapper. They are not infrastructure-as-code templates anyone should deploy.
- **Test fixtures for the agent system's unit tests.** Different artifact, different concerns. The agent project produces its own fixtures separately.

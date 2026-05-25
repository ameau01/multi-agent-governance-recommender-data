# `src/contracts/` — Shared Data Contract

This directory holds the Pydantic models that define the data contract between the data-gen project (this repo) and the agent project (`cloud-governance-agent`).

## Status

**Empty pending Phase A.1.** The contract package is owned canonically by the agent project. Per the v1.2 handoff, the agent project writes `src/contracts/*.py` and `CONTRACT_SYNC.md`, then ships them as the Phase A.1 handoff package. This project copies them in verbatim.

## Sync procedure

When the agent project's `cloud-governance-agent/src/contracts/` changes:

1. Receive the updated package from the agent project.
2. Copy all `.py` files into this directory, replacing existing files.
3. Copy `CONTRACT_SYNC.md` here (replacing existing).
4. Copy `docs/12-shared-contract.md` from the agent project to `docs/contract-spec.md` in this repo.
5. If the contract version bumped (minor or major per semver), regenerate all 18 scenarios.

The full procedure will be documented in `CONTRACT_SYNC.md` once the agent project produces it.

## What lives here (post Phase A.1)

```
src/contracts/
├── __init__.py
├── version.py        # CONTRACT_VERSION constant
├── enums.py          # TierName, ScenarioType, ActionCategory, *Metric enums
├── telemetry.py      # ComputeRecord, DatabaseRecord, CacheRecord, NetworkRecord
├── evidence.py       # TopQuery, TopCacheKey, InstanceBreakdown,
│                     #   BeforeAfterEvidence, CorrelationPair
├── configurations.py # *TopologyEntry models + TierTopology
├── recommendation.py # TargetRecommendation, EvaluationProperties
├── narrative.py      # ScenarioNarrative, BusinessContext, CostBaseline,
│                     #   ScenarioSpecificEvidence, TelemetryFilePointers
├── metadata.py       # ScenarioMetadata (top-level)
├── CONTRACT_SYNC.md  # canonical sync procedure (provided by agent project)
└── README.md         # this file
```

Estimated total: ~390 lines of Python, ~1 file of sync documentation.

## See also

- `docs/contract-spec.md` — the verbatim contract specification
- `docs/data-generation-plan.md` §14 — coordination with the agent project
- `BUILD_PLAN.md` §A.1 — the Phase A task for landing this package

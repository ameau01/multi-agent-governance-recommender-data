# `export/latest/` — Cloud Governance Scenario Dataset

**Schema version:** `1.0`
**Built at:** `2026-05-26 18:43:27`
**Built by:** `scripts/export_passing_scenarios.sh`
**Source repo:** `multi-agent-governance-recommender-data`
**Mode:** `latest` (accumulating mini-repo — merge per-scenario, preserves earlier runs)

## Summary

- Total scenarios: **18**
- Judge outcomes: pass=**9**, partial=**8**, fail=**1**
- Total records:
    - compute: **21,504** records across 16 scenario(s)
    - database: **18,816** records across 14 scenario(s)
    - cache: **2,688** records across 2 scenario(s)
    - network: **12,096** records across 9 scenario(s)

## Scenarios

| ID | Name | Type | Criticality | Tiers present | Correlations | Judge |
|---|---|---|---|---|---|---|
| `01` | Chronic Underutilization | `single_tier_negative` | tier-2 | compute | — | `pass` |
| `02` | Spiky Compute Load | `single_tier_negative` | tier-1 | compute | — | `partial` |
| `03` | Over-provisioned Database | `single_tier_negative` | tier-2 | database | — | `pass` |
| `04` | Database Connection Bottleneck | `single_tier_negative` | tier-1 | database | — | `partial` |
| `05` | Load Balancer Inefficiency | `single_tier_negative` | tier-1 | compute | — | `pass` |
| `06` | Healthy Application | `healthy` | tier-2 | compute,database,cache,network | — | `pass` |
| `07` | Cache Miss Cascade | `cross_tier_negative` | tier-1 | compute,database,cache | ✓ | `partial` |
| `08` | Database Bottleneck Impact | `cross_tier_negative` | tier-1 | compute,database | ✓ | `partial` |
| `09` | Peak Hours Cost vs Reliability | `cross_tier_negative` | tier-1 | compute,database,network | ✓ | `pass` |
| `10` | Network Latency Impact | `cross_tier_negative` | tier-1 | compute,network | ✓ | `partial` |
| `11` | Multi-Tier Over-provisioning | `cross_tier_negative` | tier-2 | compute,database,network | ✓ | `pass` |
| `12` | Healthy Compute, Problematic Database | `mixed` | tier-1 | compute,database | — | `pass` |
| `13` | Compute Spike + Database Strain | `cross_tier_negative` | tier-1 | compute,database | ✓ | `partial` |
| `14` | Good Performance, High Cost | `mixed` | tier-1 | compute,database,network | — | `partial` |
| `15` | Reliability Focused Over-provisioning | `mixed` | tier-1 | compute,database,network | — | `fail` |
| `16` | Partial Optimization | `single_tier_mild_negative` | tier-2 | compute,database,network | — | `pass` |
| `17` | Cross-Tier Performance Degradation | `diagnostic_deferral` | tier-1 | compute,database,network | ✓ | `partial` |
| `18` | Mostly Healthy with Minor Inefficiency | `mostly_healthy` | tier-2 | compute,database,network | — | `pass` |

## Field match per scenario (vs. spec target_recommendation)

| ID | finding_type | primary_tier | action_category | specific_change |
|---|---|---|---|---|
| `01` | ✓ | ✓ | ✓ | ✓ |
| `02` | ✓ | ✓ | ✓ | ✗ |
| `03` | ✓ | ✓ | ✓ | ✓ |
| `04` | ✓ | ✓ | ✓ | ✗ |
| `05` | ✓ | ✓ | ✓ | ✓ |
| `06` | ✓ | ✓ | ✓ | ✓ |
| `07` | ✓ | ✓ | ✗ | ✓ |
| `08` | ✓ | ✓ | ✓ | ✗ |
| `09` | ✓ | ✓ | ✓ | ✓ |
| `10` | ✓ | ✓ | ✓ | ✗ |
| `11` | ✓ | ✓ | ✓ | ✓ |
| `12` | ✓ | ✓ | ✓ | ✓ |
| `13` | ✓ | ✓ | ✓ | ✗ |
| `14` | ✓ | ✓ | ✓ | ✗ |
| `15` | ✗ | ✗ | ✗ | ✗ |
| `16` | ✓ | ✓ | ✓ | ✓ |
| `17` | ✓ | ✗ | ✓ | ✓ |
| `18` | ✓ | ✓ | ✓ | ✓ |

## Layout

- **`scenarios/NN/metadata.json`** — Scenario metadata: narrative, business_context, cost_baseline, tier_topology, target_recommendation, evaluation_properties. Validated by contracts.ScenarioMetadata.
- **`scenarios/NN/main.tf`** — Terraform HCL infrastructure definition for the scenario. Defines aws_instance / aws_db_instance / aws_elasticache_cluster / aws_lb resources matching the metadata's tier_topology.
- **`scenarios/NN/compute_telemetry.json`** — 1,344 records (14 days × 96 intervals/day) for compute tier. Validated by contracts.ComputeRecord (array). Empty [] if scenario is not compute-bearing.
- **`scenarios/NN/database_telemetry.json`** — Same as compute_telemetry.json but for database tier. Validated by contracts.DatabaseRecord (array).
- **`scenarios/NN/cache_telemetry.json`** — Same shape for cache tier. Validated by contracts.CacheRecord (array).
- **`scenarios/NN/network_telemetry.json`** — Same shape for network tier. Validated by contracts.NetworkRecord (array).
- **`scenarios/NN/correlation_evidence.json`** — Cross-tier correlation pairs (Pearson coefficient + lag) when the scenario's pass2_correlations rules produce coupling. Empty [] if no correlations apply.
- **`smoke_tests/NN/smoke_test.json`** — Opus rich-schema recommendation (conclusion, evidence, reasoning, projected_state, cost_impact, risk_assessment). Per docs/internal/agent_recommendation_template.md.
- **`smoke_tests/NN/smoke_test_judge.json`** — Haiku LLM-as-judge field-by-field comparison vs the spec's target_recommendation. Pass/partial/fail outcome.

## Pydantic models for downstream validation

Each JSON file in this export maps to a Pydantic model in the source repo's `src/contracts/` package. To validate as you load:

```python
from contracts import ScenarioMetadata, ComputeRecord, ...
metadata = ScenarioMetadata.model_validate(json.load(open('scenarios/01/metadata.json')))
records  = [ComputeRecord.model_validate(r) for r in json.load(open('scenarios/01/compute_telemetry.json'))]
```

For machine consumption, parse `INDEX.json` instead of this file — it carries the same data in a stable JSON shape.

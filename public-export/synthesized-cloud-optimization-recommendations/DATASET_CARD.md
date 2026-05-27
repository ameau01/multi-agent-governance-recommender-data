---
license: mit
task_categories:
  - other
language:
  - en
size_categories:
  - n<1K
tags:
  - cloud-optimization
  - aws
  - telemetry
  - benchmark
  - agent-evaluation
  - synthetic-data
  - terraform
---

# Synthesized Cloud-Optimization Recommendations

## Summary

18 scenarios that pair cloud telemetry with a hand-crafted optimization
recommendation. Each scenario has multi-tier telemetry, a Terraform file
describing the deployed infrastructure, and a gold-standard recommendation.

The dataset is built around a simple input-output mapping. The input is
telemetry plus the infrastructure. The output is an optimization
recommendation that says what to change and what the impact will be.

The dataset is synthesized. Telemetry was generated procedurally to match
each scenario's narrative. Gold recommendations were hand-crafted and
verified against per-scenario expectations.

The dataset uses AWS vocabulary throughout. Instance types, service names,
and field names match AWS. This makes the scenarios concrete instead of
vendor-neutral.

## Schema

### Scenario inputs

Each `scenarios/NN/` folder has these files.

| File                              | What it is                                  |
|-----------------------------------|---------------------------------------------|
| `metadata.json`                   | scenario name, narrative, fixtures          |
| `main.tf`                         | Terraform for the deployed infra            |
| `compute_telemetry.json`          | per-window CPU, memory, latency             |
| `database_telemetry.json`         | per-window DB query rate, pool, slow queries|
| `cache_telemetry.json`            | per-window hit rate, evictions              |
| `network_telemetry.json`          | per-window bandwidth, packet loss           |
| `correlation_evidence.json`       | cross-tier correlation pairs                |
| `handcrafted_recommendation.json` | the gold answer                             |

### Recommendation shape

```json
{
  "scenario_id": "01",
  "finding_type": "issue_found",
  "specific_change": "...",
  "primary_tier": "compute",
  "secondary_tier": null,
  "action_category": "rightsizing",
  "conclusion": { ... },
  "evidence": {
    "telemetry_observations": [ ... ],
    "infrastructure_context": [ ... ],
    "correlation_observations": [ ... ]
  },
  "reasoning": "...",
  "projected_state": { ... },
  "cost_impact": { ... },
  "risk_assessment": { ... }
}
```

### Allowed values

- `finding_type`: `issue_found`, `no_issue_found`, `diagnostic_deferral`
- `primary_tier`: `compute`, `database`, `cache`, `network`, or null
- `action_category`: `rightsizing`, `scaling_policy_change`,
  `query_cache_optimization`, `pool_sizing`, `replica_adjustment`,
  `load_balancer_reconfiguration`, `network_topology_change`, `sla_review`,
  or null

## Scenario coverage

| ID | Type              | Description                                        |
|----|-------------------|----------------------------------------------------|
| 01 | single-tier       | compute over-provisioned                           |
| 02 | single-tier       | compute peak windows, needs scheduled scaling      |
| 03 | single-tier       | database over-provisioned                          |
| 04 | single-tier       | slow queries plus exhausted pool                   |
| 05 | single-tier       | ALB round-robin causing uneven CPU                 |
| 06 | no-action         | all tiers healthy                                  |
| 07 | single-tier       | cache hit ratio degraded                           |
| 08 | cross-tier        | slow DB queries cascade to compute                 |
| 09 | cross-tier        | weekday bimodal peaks, needs scheduled scaling     |
| 10 | cross-tier        | network latency cascades to compute                |
| 11 | cross-tier        | all three tiers over-provisioned                   |
| 12 | mixed             | healthy compute, over-provisioned database         |
| 13 | cross-tier        | compute spike strains database                     |
| 14 | cross-tier        | compute and database both over-provisioned         |
| 15 | reliability       | 99.99% SLA via over-provisioning                   |
| 16 | mild              | partial compute optimization                       |
| 17 | deferral          | all tiers rise in lockstep, need more diagnosis    |
| 18 | mostly healthy    | minor compute inefficiency                         |

## How to evaluate

Use the companion eval-set in the same Hugging Face repository. It scores
predictions across three tiers.

- Floor: structure and category checks. Any reasonable agent passes 18 out
  of 18.
- Mid: action keywords plus multi-tier reasoning.
- Rich: fixture citations plus quantified projections.

A typical run:

```bash
python <eval-set-folder>/eval.py \
    --predictions your_predictions.json \
    --dataset .
```

## Intended uses

- Train or fine-tune a model that maps cloud telemetry to an optimization
  recommendation.
- Evaluate AI agents on cloud-optimization reasoning.
- Compare single-shot vs orchestrated agent designs. The Rich tier is
  calibrated so that orchestration matters.

## License

MIT. See `LICENSE`.

## Citation

```
@misc{synthesized_cloud_optimization_recommendations_2026,
  title = {Synthesized Cloud-Optimization Recommendations},
  author = {Alex Meau},
  year = {2026},
  version = {1.0.0}
}
```

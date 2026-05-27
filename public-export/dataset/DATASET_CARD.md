---
license: mit
task_categories:
  - other
language:
  - en
size_categories:
  - n<1K
tags:
  - cloud-governance
  - aws
  - benchmark
  - agent-evaluation
---

# Cloud Governance Recommender Dataset

## Summary

18 scenarios that test an AI agent's ability to read cloud telemetry, locate
the root cause, and recommend an infrastructure change. Each scenario has
multi-tier telemetry, a Terraform file, and a hand-crafted gold answer.

The dataset targets AWS vocabulary on purpose. The instance types, service
names, and field names all match AWS. This makes the scenarios concrete
instead of vendor-neutral.

## Schema

### Scenario inputs

Each `scenarios/NN/` folder has these files.

| File                          | What it is                                  |
|-------------------------------|---------------------------------------------|
| `metadata.json`               | scenario name, narrative, fixtures          |
| `main.tf`                     | Terraform for the deployed infra            |
| `compute_telemetry.json`      | per-window CPU, memory, latency             |
| `database_telemetry.json`     | per-window DB query rate, pool, slow queries|
| `cache_telemetry.json`        | per-window hit rate, evictions              |
| `network_telemetry.json`      | per-window bandwidth, packet loss           |
| `correlation_evidence.json`   | cross-tier correlation pairs                |
| `handcrafted_recommendation.json` | the gold answer                         |

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
| 04 | single-tier       | slow queries + exhausted pool                      |
| 05 | single-tier       | ALB round-robin causing uneven CPU                 |
| 06 | no-action         | all tiers healthy                                  |
| 07 | single-tier       | cache hit ratio degraded                           |
| 08 | cross-tier        | slow DB queries cascade to compute                 |
| 09 | cross-tier        | weekday bimodal peaks, needs scheduled scaling     |
| 10 | cross-tier        | network latency cascades to compute                |
| 11 | cross-tier        | all three tiers over-provisioned                   |
| 12 | mixed             | healthy compute, over-provisioned database         |
| 13 | cross-tier        | compute spike strains database                     |
| 14 | cross-tier        | compute + database both over-provisioned           |
| 15 | reliability       | 99.99% SLA via over-provisioning                   |
| 16 | mild              | partial compute optimization                       |
| 17 | deferral          | all tiers rise in lockstep, need more diagnosis    |
| 18 | mostly healthy    | minor compute inefficiency                         |

## How to evaluate

Use `eval-set/` in the sibling folder. Three tiers:

- Floor: structure and category checks (anyone should pass 18/18)
- Mid: action keywords + multi-tier reasoning
- Rich: fixture citations + quantification

Run `eval-set/eval.py --predictions <file> --dataset .` from the parent folder.

## License

MIT. See `LICENSE`.

## Citation

```
@misc{cloud_governance_recommender_2026,
  title = {Cloud Governance Recommender Dataset},
  author = {Alex Meau},
  year = {2026},
  version = {1.0.0}
}
```

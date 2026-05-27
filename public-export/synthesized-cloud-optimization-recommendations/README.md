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
configs:
  - config_name: default
    data_files:
      - split: scenarios
        path: scenarios_summary.jsonl
---

# Synthesized Cloud-Optimization Recommendations

18 scenarios that pair cloud telemetry with a hand-crafted optimization
recommendation. Use them to train models or to evaluate AI agents.

## Summary

Each scenario has multi-tier telemetry, a Terraform file describing the
deployed infrastructure, and a gold-standard recommendation.

The dataset is built around a simple input-output mapping. The input is
telemetry plus the infrastructure. The output is an optimization
recommendation that says what to change and what the impact will be.

The dataset is synthesized. Telemetry was generated procedurally to match
each scenario's narrative. Gold recommendations were hand-crafted and
verified.

The dataset uses AWS vocabulary throughout. Instance types, service names,
and field names match AWS. This makes the scenarios concrete instead of
vendor-neutral.

## Folder layout

```
README.md                                # this file
LICENSE                                  # MIT
EVAL.md                                  # what eval.py checks
eval.py                                  # Floor sanity check (smoke test)
sample_predictions.json                  # worked example of submission shape
scenarios_summary.jsonl                  # one row per scenario (viewer table)
scenarios/
  01/
    metadata.json                        # scenario summary + fixtures
    main.tf                              # Terraform for the infra
    compute_telemetry.json               # CPU, memory, latency
    database_telemetry.json              # query rates, pool stats
    cache_telemetry.json                 # hit rate, eviction
    network_telemetry.json               # bandwidth, packet loss
    correlation_evidence.json            # cross-tier correlations
    handcrafted_recommendation.json      # the gold answer
  02/
    ...
```

Each scenario covers a different optimization situation. Some are
single-tier (only compute is wrong). Some span tiers (database problem
that surfaces in compute). Some are no-action cases. Two are diagnostic
deferral cases. One asks for an SLA review instead of an infra change.

## The summary table (`scenarios_summary.jsonl`)

The Hugging Face Dataset Viewer renders `scenarios_summary.jsonl` as a
browsable table. Each row is one scenario and includes the headline fields
from that scenario's metadata and gold recommendation.

The summary is for discovery only. The full inputs (telemetry, Terraform,
correlation evidence) live in `scenarios/NN/`. Always train or evaluate on
the full files, not on the summary.

Columns in the summary table:

| Column                         | Source                                         |
|--------------------------------|------------------------------------------------|
| `scenario_id`                  | folder name                                    |
| `scenario_name`                | metadata.scenario_name                         |
| `scenario_type`                | metadata.scenario_type                         |
| `what_this_demonstrates`       | metadata.narrative.what_this_demonstrates      |
| `finding_type`                 | gold.finding_type                              |
| `primary_tier`                 | gold.primary_tier                              |
| `secondary_tier`               | gold.secondary_tier                            |
| `action_category`              | gold.action_category                           |
| `specific_change`              | gold.specific_change                           |
| `savings_monthly_usd`          | gold.cost_impact.savings_monthly_usd           |
| `current_monthly_usd`          | gold.cost_impact.current_monthly_usd           |
| `projected_monthly_usd`        | gold.cost_impact.projected_monthly_usd         |

Some scenarios have negative `savings_monthly_usd`. That is expected. For
those scenarios the right action increases cost to fix a performance or
reliability problem (for example, adding a read replica).

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

## How to use it

You can use this dataset two ways.

**Train or fine-tune.** Treat each scenario's telemetry plus metadata as
input. Use the `handcrafted_recommendation.json` as the target output.

**Evaluate AI agents.** Run your agent on the scenario inputs. Compare its
output to the hand-crafted recommendation in that scenario's folder.

## Quick sanity check

```bash
python eval.py --predictions sample_predictions.json
```

This runs the bundled Floor sanity check. It confirms your predictions
parse, have the required fields, and use allowed category values. It does
NOT score recommendation quality. See `EVAL.md` for what is checked.

## Prediction shape

See `sample_predictions.json` for a worked example. Required fields per
prediction: `scenario_id`, `finding_type`, `specific_change`,
`primary_tier`, `action_category`. Optional but useful for deeper
scoring: `secondary_tier`, `reasoning`, `evidence`, `projected_state`,
`cost_impact`, `risk_assessment`.

## How to score beyond the Floor check

The dataset ships gold answers and a Floor sanity check. It does not ship
a quality scorer. Beyond the Floor check, the scoring method is up to
you. Common options:

- Exact match on the enum fields (`finding_type`, `primary_tier`,
  `action_category`).
- Keyword or substring checks on `specific_change`.
- Semantic similarity on the prose fields.
- A custom rubric per scenario, comparing prediction fields against the
  matching `handcrafted_recommendation.json`.

## Intended uses

- Train or fine-tune a model that maps cloud telemetry to an optimization
  recommendation.
- Evaluate AI agents on cloud-optimization reasoning.
- Compare single-shot vs orchestrated agent designs.

## License

MIT. See `LICENSE`.

## Citation

```
@misc{synthesized_cloud_optimization_recommendations_2026,
  title = {Synthesized Cloud-Optimization Recommendations},
  author = {Alexander Meau},
  year = {2026},
  version = {1.0.0}
}
```

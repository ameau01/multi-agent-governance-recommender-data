# Synthesized Cloud-Optimization Recommendations

18 scenarios that pair cloud telemetry with a hand-crafted optimization
recommendation. Use them to train models or to evaluate AI agents.

## What each scenario gives you

Every scenario folder has the same files.

- Multi-tier telemetry: compute, database, cache, network.
- The Terraform that describes the deployed infrastructure.
- A hand-crafted recommendation that counts as the gold answer.

The recommendation specifies a concrete change. It includes the reasoning
and the projected impact. Example changes: rightsize a compute fleet, add
a read replica, fix a slow query, reconfigure a load balancer.

## Folder layout

```
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

## How to use it

You can use this dataset two ways.

**Train or fine-tune.** Treat each scenario's telemetry plus metadata as
input. Use the `handcrafted_recommendation.json` as the target output.

**Score predictions.** Use the companion eval-set in the same Hugging
Face repository. It scores predictions across three tiers: Floor, Mid,
Rich.

## Quick sanity check

```bash
python eval.py --predictions sample_predictions.json
```

This runs the Floor competency check. It confirms your predictions parse,
have the required fields, and use allowed category values. For full
scoring, see the companion eval-set.

## Prediction shape

See `sample_predictions.json` for a worked example. Required fields per
prediction: `scenario_id`, `finding_type`, `specific_change`,
`primary_tier`, `action_category`. Optional but used by Mid and Rich:
`secondary_tier`, `reasoning`, `evidence`, `projected_state`,
`cost_impact`, `risk_assessment`.

## Scenario count by category

- Single-tier issues: 7 scenarios
- Cross-tier issues: 7 scenarios
- No-action / healthy: 1 scenario
- Diagnostic deferral: 1 scenario
- SLA review: 1 scenario
- Mild / partial optimization: 1 scenario

## License

MIT.

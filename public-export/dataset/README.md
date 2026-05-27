# dataset

18 cloud-governance scenarios. Each scenario has telemetry, infrastructure,
and a hand-crafted recommendation.

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

Each scenario covers a different cloud-governance situation. Some are
single-tier (only compute is wrong). Some span tiers (database problem that
surfaces in compute). Some are no-action cases. Two are diagnostic deferral
cases.

## How to use it

You can use this dataset two ways.

**Score predictions.** Use `eval-set/` to score your agent's predictions
against the expectations. Three tiers: Floor, Mid, Rich.

**Train or fine-tune.** Treat each scenario's telemetry plus metadata as
input and the `handcrafted_recommendation.json` as the target output.

## Quick sanity check

```bash
python eval.py --predictions sample_predictions.json
```

This runs the Floor competency check. It only confirms your predictions
parse, have the required fields, and use allowed category values. For full
scoring, use `eval-set/eval.py`.

## Prediction shape

See `sample_predictions.json` for the exact shape. Required fields per
prediction: `scenario_id`, `finding_type`, `specific_change`, `primary_tier`,
`action_category`. Optional but used by Mid and Rich: `secondary_tier`,
`reasoning`, `evidence`, `projected_state`, `cost_impact`, `risk_assessment`.

## Scenario count by category

- Single-tier issues: 7 scenarios
- Cross-tier issues: 7 scenarios
- No-action / healthy: 1 scenario
- Diagnostic deferral: 1 scenario
- SLA review: 1 scenario
- Mild / partial optimization: 1 scenario

## License

MIT.

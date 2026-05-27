# eval-set/eval.py — full three-tier scoring

This file describes what each tier checks and how to read the output.

## Tier 1: Floor

Floor confirms the prediction is shaped like a governance recommendation.

### finding_type

The `finding_type` field must be one of the values the scenario allows. For
most scenarios the only allowed value is `issue_found`. Scenario 06 only
allows `no_issue_found`. Scenarios 15 and 17 allow `diagnostic_deferral`.

### primary_tier

Must be one of `compute`, `database`, `cache`, `network`, or null. Each
scenario has its own allowed list. For example, scenario 01 requires
`compute`. Scenario 11 accepts any of the three because all tiers are
over-provisioned.

### action_category

Must be one of the allowed values for the scenario. Some scenarios accept
multiple. Scenario 04 accepts both `query_cache_optimization` and
`pool_sizing` because both are defensible framings of the same fix.

### specific_change present

The `specific_change` text must be at least 20 characters. This is a Floor
competency check, not a quality check.

## Tier 2: Mid

Mid confirms the recommendation engages with the right evidence.

### secondary_tier

Where the scenario lists a `secondary_tier_allowed`, the prediction's
`secondary_tier` must match.

### action_keywords

Each scenario defines OR-groups of keywords. The prediction's
`specific_change`, `reasoning`, and `evidence` fields together must contain
at least one keyword from at least N of the groups. For example, scenario 01
needs keywords from two of these three groups:

- `[downsize, rightsize, scale down, ...]`
- `[t3.medium, smaller, fewer]`
- `[replica, instance count, instance size]`

The match is case-insensitive substring.

### multi_tier_evidence

Where the scenario marks `multi_tier_evidence`, the prediction's text must
mention each required tier by name. For scenario 11, the recommendation must
say "compute", "database", and "network" somewhere.

## Tier 3: Rich

Rich confirms orchestrated synthesis.

### fixture_citation

Where the scenario marks `must_cite_fixture`, the prediction must reference
at least one identifier from the named fixture in `metadata.json`. The
fixtures are:

- `top_queries`: query names from `scenario_specific_evidence.top_queries`
- `top_cache_keys`: cache key patterns
- `per_instance_breakdown`: instance IDs like `i-001`

### cost_impact_quantified

The `cost_impact` section must include at least one non-zero numeric field:
`current_monthly_usd`, `projected_monthly_usd`, `savings_monthly_usd`, or
`savings_pct`.

This check skips for `no_issue_found`, `diagnostic_deferral`, and
`sla_review`. Those scenarios do not propose a numeric change.

### projected_state_quantified

The `projected_state` section must include at least one numeric field (for
example `cpu_p95_pct_estimate` or `latency_p95_ms_estimate`).

Same skip rule as `cost_impact_quantified`.

### evidence_structured

The `evidence` section must total at least 3 bullets across
`telemetry_observations`, `infrastructure_context`, and
`correlation_observations`.

## Exit codes

- `0`: every submitted prediction passed every requested tier.
- `1`: at least one failure.
- `2`: usage error.

## JSON output

`--json` emits per-scenario per-check detail. Top-level keys are scenario
IDs. Each scenario has `floor`, `mid`, `rich`, each with a `passed` flag and
a `checks` array of `{name, passed, message, detail}` entries.

A `_totals` key at the end gives counts.

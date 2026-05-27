"""Per-scenario evaluation rubrics for deterministic scoring.

Each rubric defines what counts as a correct recommendation for one scenario.
The scorer (deterministic_scorer.py) reads these rubrics and applies pure-Python
checks — no LLM call. Same recommendation + same rubric = byte-identical score.

DESIGN PRINCIPLES (these rubrics encode them):

  1. The CORE insight is non-negotiable. The agent must reach the diagnosis
     the scenario was designed to elicit (which tier, what kind of action).

  2. DEFENSIBLE ALTERNATIVES are explicitly accepted with rationale. Where
     engineering practice admits multiple valid framings of the same fix,
     the rubric lists each acceptable enum value with a `_rationale` comment.

  3. MULTI-TIER REASONING is REQUIRED where the scenario demands it. The
     dataset's value proposition is that orchestrated multi-tier analysis
     beats single-tier analysis. Cross-tier scenarios enforce this by
     requiring the recommendation to mention all affected tiers.

  4. WORDING is FLEXIBLE; INTENT is STRICT. We don't require exact phrases.
     We require specific *concepts* (via OR-groups of synonyms) to be present.

Schema (all fields optional except `_rationale`):

    "NN": {
        "_rationale": "one-line description of what this scenario tests",

        "finding_type_allowed": ["issue_found"],   # set match
        "primary_tier_allowed": ["compute"],       # set match; null acceptable
        "secondary_tier_allowed": ["database", None],
        "action_category_allowed": ["rightsizing"],
        "_action_category_rationale": "explanation if multiple are listed",

        # Each inner list is an OR-group (any one keyword matches the group).
        # The recommendation's specific_change must trigger AT LEAST
        # `min_match` groups. Case-insensitive substring match.
        "action_keyword_groups": [
            ["downsize", "rightsize", "scale down"],
            ["t3.medium", "smaller instance"],
        ],
        "action_keyword_min_match": 2,

        # If set, the recommendation must mention `min_tiers` of the listed
        # tier names (case-insensitive substring) in its text. Enforces
        # multi-tier reasoning on cross-tier scenarios.
        "multi_tier_evidence": {
            "must_cite_tiers": ["compute", "database"],
            "min_tiers": 2,
        },

        # If set, the recommendation must cite at least one identifier
        # from the scenario's metadata.scenario_specific_evidence.<fixture>
        # (top_queries[*].name, top_cache_keys[*], or
        # per_instance_breakdown[*].instance_id).
        "must_cite_fixture": "top_queries",   # or "top_cache_keys" or "per_instance_breakdown"
    }
"""

from __future__ import annotations


# ============================================================
# Per-scenario rubrics — 18 entries
# ============================================================
RUBRICS: dict[str, dict] = {
    # ----------------------------------------------------------
    # SINGLE-TIER NEGATIVE — compute focal
    # ----------------------------------------------------------
    "01": {
        "_rationale": "Chronic underutilization of a fixed compute fleet — "
                       "agent should recognize over-provisioning and recommend rightsizing.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "action_category_allowed": ["rightsizing"],
        "action_keyword_groups": [
            ["downsize", "rightsize", "right-size", "scale down", "reduce instance"],
            ["t3.medium", "smaller", "fewer"],
            ["replica", "instance count", "instance size"],
        ],
        "action_keyword_min_match": 2,
    },

    "02": {
        "_rationale": "Compute fleet with predictable daily peak windows — "
                       "agent should recommend scheduled/predictive scaling, "
                       "not raw rightsizing.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "action_category_allowed": ["scaling_policy_change"],
        "action_keyword_groups": [
            ["scheduled scaling", "scheduled auto-scaling", "scheduled action",
             "predictive scaling", "predictive auto-scaling", "schedule-based",
             "time-based scaling", "auto scaling group", "asg"],
            ["peak", "spike", "business hours", "10:00", "10-14", "14:00",
             "daily peak", "peak hours"],
            ["increase capacity", "scale up", "additional capacity",
             "more instances", "burst"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # SINGLE-TIER NEGATIVE — database focal
    # ----------------------------------------------------------
    "03": {
        "_rationale": "Database is provisioned far above its actual load — "
                       "agent should recommend database rightsizing.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["database"],
        "action_category_allowed": ["rightsizing"],
        "action_keyword_groups": [
            ["downsize", "rightsize", "smaller instance", "scale down"],
            ["database", "db", "rds", "db.r", "db.m"],
        ],
        "action_keyword_min_match": 2,
    },

    "04": {
        "_rationale": "Database under pressure from slow queries + exhausted "
                       "connection pool. Multiple defensible action categories "
                       "(query optimization vs pool sizing) — both legitimate.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["database"],
        "action_category_allowed": ["query_cache_optimization", "pool_sizing"],
        "_action_category_rationale": (
            "The fix is two-pronged: optimize slow queries AND increase the "
            "connection pool. Either action_category framing captures a "
            "legitimate primary lens on the problem."
        ),
        "action_keyword_groups": [
            ["optimize", "tune", "improve"],
            ["slow query", "query", "sql", "index"],
            ["connection pool", "pool size", "max_connections", "increase pool"],
        ],
        "action_keyword_min_match": 2,
        "must_cite_fixture": "top_queries",
    },

    # ----------------------------------------------------------
    # SINGLE-TIER NEGATIVE — load balancer (compute OR network primary)
    # ----------------------------------------------------------
    "05": {
        "_rationale": "ALB using round-robin distribution causing uneven CPU "
                       "across instances. Both 'compute' and 'network' are "
                       "defensible primary_tier — ALB is conventionally network "
                       "infrastructure, but the symptom surfaces in compute.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute", "network"],
        "_primary_tier_rationale": (
            "ALB classification is a known ambiguity in cloud taxonomy: aws_lb "
            "is in the network AWS service family, but the diagnostic signal "
            "(uneven per-instance CPU) lives in the compute tier."
        ),
        "action_category_allowed": ["load_balancer_reconfiguration"],
        "action_keyword_groups": [
            ["least_outstanding_requests", "least-outstanding-requests",
             "least outstanding", "least-conn"],
            ["round_robin", "round-robin", "round robin"],
            ["alb", "application load balancer", "target group", "load balancer"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # NO_ISSUE — healthy
    # ----------------------------------------------------------
    "06": {
        "_rationale": "Every tier is healthy. Agent must recognize no action "
                       "is needed (restraint test).",
        "finding_type_allowed": ["no_issue_found"],
        "primary_tier_allowed": [None],
        "action_category_allowed": [None],
        "action_keyword_groups": [
            ["no action", "no change", "no issue", "no recommendation",
             "no modification", "no adjustment", "operating in healthy",
             "correctly sized", "healthy", "well-provisioned"],
        ],
        "action_keyword_min_match": 1,
    },

    # ----------------------------------------------------------
    # SINGLE-TIER NEGATIVE — cache focal
    # ----------------------------------------------------------
    "07": {
        "_rationale": "Cache hit ratio degraded, cascading to database+compute. "
                       "The fix involves cache scaling AND warming logic. Both "
                       "'query_cache_optimization' (deep) and 'pool_sizing' "
                       "(surface) framings are defensible.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["cache"],
        "action_category_allowed": ["query_cache_optimization", "pool_sizing"],
        "_action_category_rationale": (
            "Both framings capture a legitimate lens: query_cache_optimization "
            "emphasizes the root cause (cache miss patterns); pool_sizing "
            "emphasizes the implementation (scaling cluster nodes). Acceptable "
            "either way."
        ),
        "action_keyword_groups": [
            ["cache", "elasticache", "redis"],
            ["scale", "increase", "add nodes", "add cluster", "more nodes"],
            ["warming", "warm", "key design", "cache key", "hit ratio"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # CROSS-TIER NEGATIVE — database root cause, compute symptom
    # ----------------------------------------------------------
    "08": {
        "_rationale": "Slow DB queries cascade into elevated compute latency. "
                       "Multi-tier reasoning REQUIRED: the recommendation must "
                       "show the agent recognized BOTH tiers are involved.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["database"],
        "secondary_tier_allowed": ["compute", None],
        "action_category_allowed": ["query_cache_optimization", "pool_sizing",
                                     "replica_adjustment"],
        "_action_category_rationale": (
            "Three defensible categories: query_cache_optimization (fix the "
            "slow queries), pool_sizing (fix the connection bottleneck), "
            "replica_adjustment (add read replicas to absorb load)."
        ),
        "action_keyword_groups": [
            ["optimize", "slow query", "query"],
            ["read replica", "replica", "follower"],
            ["compute", "application latency", "downstream", "cascade"],
        ],
        "action_keyword_min_match": 2,
        "multi_tier_evidence": {
            "must_cite_tiers": ["database", "compute"],
            "min_tiers": 2,
        },
        "must_cite_fixture": "top_queries",
    },

    # ----------------------------------------------------------
    # CROSS-TIER NEGATIVE — compute scheduling on multi-tier app
    # ----------------------------------------------------------
    "09": {
        "_rationale": "Bimodal peak/off-peak weekday pattern on multi-tier app. "
                       "Agent should recommend scheduled scaling for off-peak "
                       "cost reduction.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "action_category_allowed": ["scaling_policy_change", "rightsizing"],
        "_action_category_rationale": (
            "Scheduled scaling is the canonical fix; static rightsizing is "
            "also defensible if the agent prefers a simpler intervention."
        ),
        "action_keyword_groups": [
            ["scheduled scaling", "predictive scaling", "time-based",
             "schedule-based", "scheduled action", "auto-scaling"],
            ["off-peak", "off-hours", "off peak", "weekend"],
            ["weekday", "weekend"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # CROSS-TIER NEGATIVE — network root cause, compute symptom
    # ----------------------------------------------------------
    "10": {
        "_rationale": "Network latency to a payment provider cascades into "
                       "compute application latency. Multi-tier reasoning "
                       "REQUIRED: agent must recognize network is the cause, "
                       "compute is the symptom — NOT scale compute.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["network"],
        "secondary_tier_allowed": ["compute", None],
        "action_category_allowed": ["network_topology_change"],
        "action_keyword_groups": [
            ["privatelink", "private link", "private-link", "vpc endpoint",
             "transit gateway", "direct connect"],
            ["vpc peering", "peering", "cross-region"],
            ["retry", "exponential backoff", "circuit breaker", "timeout"],
        ],
        "action_keyword_min_match": 2,
        "multi_tier_evidence": {
            "must_cite_tiers": ["network", "compute"],
            "min_tiers": 2,
        },
    },

    # ----------------------------------------------------------
    # CROSS-TIER NEGATIVE — all-tier over-provisioning
    # ----------------------------------------------------------
    "11": {
        "_rationale": "All three tiers (compute, database, network) are "
                       "over-provisioned. Multi-tier reasoning REQUIRED: "
                       "agent must rightsize all three, not just one.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute", "database", "network"],
        "_primary_tier_rationale": (
            "All three tiers are over-provisioned simultaneously; any of the "
            "three can be defensibly framed as primary depending on which has "
            "the largest absolute over-provisioning."
        ),
        "action_category_allowed": ["rightsizing"],
        "action_keyword_groups": [
            ["downsize", "rightsize", "right-size", "scale down", "reduce"],
            ["m5.large", "smaller instance", "fewer instance"],
        ],
        "action_keyword_min_match": 2,
        "multi_tier_evidence": {
            "must_cite_tiers": ["compute", "database", "network"],
            "min_tiers": 3,
        },
    },

    # ----------------------------------------------------------
    # MIXED — healthy compute, problematic database
    # ----------------------------------------------------------
    "12": {
        "_rationale": "Compute is correctly sized; database is over-provisioned. "
                       "Agent should rightsize ONLY the database (must not "
                       "recommend compute changes).",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["database"],
        "action_category_allowed": ["rightsizing", "pool_sizing"],
        "_action_category_rationale": (
            "Database rightsizing is the canonical fix; pool_sizing is "
            "defensible if framed as a connection-pool tuning."
        ),
        "action_keyword_groups": [
            ["downsize", "rightsize", "scale down", "smaller"],
            ["database", "db.r", "db.m", "rds"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # CROSS-TIER NEGATIVE — compute spike + database strain
    # ----------------------------------------------------------
    "13": {
        "_rationale": "Compute spike during business hours strains database. "
                       "Multi-tier reasoning REQUIRED: agent should address "
                       "both tiers (scaling policy on compute, replica or "
                       "pool change on database).",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "secondary_tier_allowed": ["database", None],
        "action_category_allowed": ["scaling_policy_change", "rightsizing",
                                     "replica_adjustment"],
        "_action_category_rationale": (
            "Three defensible framings of the multi-tier fix: scheduled scaling "
            "on compute, raw rightsizing, or adding DB read replicas."
        ),
        "action_keyword_groups": [
            ["scheduled scaling", "auto-scaling", "scale up", "rightsize"],
            ["database", "db", "read replica", "replica"],
        ],
        "action_keyword_min_match": 2,
        "multi_tier_evidence": {
            "must_cite_tiers": ["compute", "database"],
            "min_tiers": 2,
        },
    },

    # ----------------------------------------------------------
    # CROSS-TIER NEGATIVE — good performance, high cost
    # ----------------------------------------------------------
    "14": {
        "_rationale": "Multi-tier rightsizing opportunity: compute AND database "
                       "are both well over-provisioned. Multi-tier reasoning "
                       "REQUIRED.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute", "database"],
        "_primary_tier_rationale": (
            "Both tiers are over-provisioned; either is defensible as primary."
        ),
        "action_category_allowed": ["rightsizing"],
        "action_keyword_groups": [
            ["downsize", "rightsize", "scale down"],
            ["m5.large", "m5.xlarge", "smaller", "db.r"],
            ["database", "compute"],
        ],
        "action_keyword_min_match": 2,
        "multi_tier_evidence": {
            "must_cite_tiers": ["compute", "database"],
            "min_tiers": 2,
        },
    },

    # ----------------------------------------------------------
    # RELIABILITY-FOCUSED — SLA review OR deferral both defensible
    # ----------------------------------------------------------
    "15": {
        "_rationale": "99.99% SLA configured via heavy over-provisioning. "
                       "Two defensible engineering responses: aggressive "
                       "('the SLA itself may be too strict — review with "
                       "business') or conservative ('defer pending business "
                       "stakeholder consultation'). Both reach the same "
                       "operational conclusion: have an SLA-level conversation.",
        "finding_type_allowed": ["issue_found", "diagnostic_deferral"],
        "_finding_type_rationale": (
            "The aggressive read says 'this is an issue — review the SLA'. "
            "The conservative read says 'defer — need business context'. "
            "Both are correct engineering postures."
        ),
        "primary_tier_allowed": ["compute", "database", "network", None],
        "_primary_tier_rationale": (
            "For deferral framings, primary_tier may legitimately be null "
            "OR the tier with the most over-provisioning."
        ),
        "action_category_allowed": ["sla_review", None],
        "action_keyword_groups": [
            ["sla", "service level", "availability target", "99.9",
             "uptime"],
            ["review", "discuss", "business", "stakeholder", "negotiate",
             "confirm", "validate"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # SINGLE-TIER MILD — compute partial optimization
    # ----------------------------------------------------------
    "16": {
        "_rationale": "Compute has a partial optimization opportunity while "
                       "other tiers are fine. Agent should rightsize compute.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "action_category_allowed": ["rightsizing", "scaling_policy_change"],
        "action_keyword_groups": [
            ["downsize", "rightsize", "scale down", "reduce"],
            ["compute", "m5.large", "m5.xlarge"],
        ],
        "action_keyword_min_match": 2,
    },

    # ----------------------------------------------------------
    # DEFERRAL — cross-tier coupling
    # ----------------------------------------------------------
    "17": {
        "_rationale": "All three tiers' latency rises simultaneously with no "
                       "clear lead-lag. The agent MUST recognize this is "
                       "diagnostic deferral — instrumentation is needed before "
                       "any infrastructure change is safe.",
        "finding_type_allowed": ["diagnostic_deferral"],
        "primary_tier_allowed": ["compute", "database", "network", None],
        "_primary_tier_rationale": (
            "On a deferral case, primary_tier may be null OR a leading "
            "hypothesis. Either is acceptable since the whole point is the "
            "agent hasn't committed to a diagnosis yet."
        ),
        "action_category_allowed": [None],
        "action_keyword_groups": [
            ["distributed trace", "trace analysis", "observability",
             "instrumentation", "tracing", "additional"],
            ["root cause", "cause", "diagnose"],
            ["simultaneous", "lockstep", "all three", "all tier",
             "co-presence", "no lead-lag", "no clear"],
        ],
        "action_keyword_min_match": 2,
        "multi_tier_evidence": {
            "must_cite_tiers": ["compute", "database", "network"],
            "min_tiers": 3,
        },
    },

    # ----------------------------------------------------------
    # MOSTLY HEALTHY — minor compute inefficiency
    # ----------------------------------------------------------
    "18": {
        "_rationale": "Application is mostly healthy with a minor compute "
                       "inefficiency. Agent should propose a small rightsizing.",
        "finding_type_allowed": ["issue_found"],
        "primary_tier_allowed": ["compute"],
        "action_category_allowed": ["rightsizing"],
        "action_keyword_groups": [
            ["minor", "modest", "small", "slight"],
            ["downsize", "rightsize", "compute"],
        ],
        "action_keyword_min_match": 1,
    },
}


def get_rubric(scenario_id: str) -> dict | None:
    """Return the rubric dict for a scenario, or None if not defined."""
    return RUBRICS.get(scenario_id)

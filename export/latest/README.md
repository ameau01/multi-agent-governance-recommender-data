# Cloud Governance Scenario Dataset

Drop-in dataset of 18 cloud-application scenarios for downstream cloud-governance agents.
Each scenario carries 14 days of synthetic telemetry across up to 4 tiers, plus the infrastructure
definition (Terraform), scenario metadata (business context, SLA, cost baseline), and a reference
recommendation produced by Claude Opus 4.6 against the same data.

**Read first:**

- [`MANIFEST.md`](MANIFEST.md) — human-readable summary and schema documentation.
- [`INDEX.json`](INDEX.json) — machine-readable per-scenario index; parse this in code.

**Quick stats:**

- Schema version: **1.0**
- Scenarios: **18** (9 pass, 8 partial, 1 fail)
- Total telemetry records: **55,104**

Built `2026-05-26 18:43:27` by `scripts/export_passing_scenarios.sh` from `multi-agent-governance-recommender-data`.

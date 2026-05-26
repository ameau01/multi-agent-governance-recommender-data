# Export — 2026-05-26

Frozen snapshot of scenarios that passed the full data-gen pipeline
(Pass 1 → Pass 2 → splitter → validate → smoke-test → judge) under
the content-routing prompt revision.

Built by: scripts/export_passing_scenarios.sh
When:     Tue May 26 14:38:19 PDT 2026

## Scenarios included (4)

- `01` — (unavailable)
- `03` — (unavailable)
- `10` — (unavailable)
- `13` — (unavailable)

## Layout

- `scenarios/NN/` — the public deliverable for scenario NN
  (`metadata.json`, `main.tf`, 4 tier telemetry files, `correlation_evidence.json`).
- `smoke_tests/NN/` — Opus recommendation + Haiku judge verdict for NN
  (audit trail, not part of the consumer-facing dataset).

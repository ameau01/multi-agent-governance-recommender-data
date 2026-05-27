# Baselines

This file will hold scores from baseline agents once they run. Right now it
is a placeholder so the structure is clear.

## Planned baselines

The point of running these is to confirm the three-tier eval actually
separates orchestration from single-shot.

| Baseline       | Description                                                  |
|----------------|--------------------------------------------------------------|
| trivial        | Returns the same canned recommendation for every scenario    |
| random         | Picks a random allowed value for each enum field             |
| single-shot    | Frontier model, one prompt, no tools, no orchestration       |
| orchestrated   | Multi-agent setup: telemetry triage, infra mapping, synthesis|

## Expected scoring (will be filled in)

| Baseline       | Floor   | Mid     | Rich    |
|----------------|---------|---------|---------|
| trivial        | low     | 0       | 0       |
| random         | low     | 0       | 0       |
| single-shot    | 18      | high    | low     |
| orchestrated   | 18      | 18      | 18      |

The Rich tier is calibrated so that single-shot stays well under 18 and
orchestrated reaches 18. If single-shot hits 17 or 18 on Rich, the checks
need to be tightened.

## How to add a new baseline

1. Produce a `predictions.json` file with one entry per scenario.
2. Run `python eval.py --predictions your_file.json --dataset ../dataset --json > scores.json`.
3. Append your baseline name and scores to the table above.

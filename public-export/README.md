# Cloud Governance Recommender Dataset

A benchmark for AI agents that read cloud telemetry and recommend
infrastructure changes.

## What is in this repo

Two subfolders. Each is self-contained.

- `dataset/` has the 18 scenarios. Each scenario has telemetry, Terraform,
  and a hand-crafted recommendation that counts as the gold answer.
- `eval-set/` has the scoring code. It checks predictions against the
  expectations for each scenario, in three tiers (Floor, Mid, Rich).

## Quick start

```bash
# 1. Score your predictions across Floor + Mid + Rich
python eval-set/eval.py \
    --predictions your_predictions.json \
    --dataset dataset

# 2. Or run only the Floor sanity check
python dataset/eval.py --predictions your_predictions.json
```

## The three tiers

- **Floor** checks that a prediction is shaped right. Allowed `finding_type`,
  allowed `primary_tier`, allowed `action_category`. A reasonable agent
  passes Floor 18 out of 18.
- **Mid** checks that the recommendation engages with the right evidence.
  Did it mention the right tiers? Does the proposed fix use the right
  action keywords? A careful single-shot agent can pass most of Mid.
- **Rich** checks for orchestrated synthesis. Did the agent cite named
  fixtures from the telemetry? Did it quantify cost and projected state?
  Single-shot agents typically fail Rich. Orchestrated agents pass.

See `eval-set/EVAL.md` for full check definitions.

## License

MIT. See `LICENSE`.

## Version

1.0.0

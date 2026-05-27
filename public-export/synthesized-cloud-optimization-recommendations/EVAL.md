# eval.py: Floor sanity check

A minimal smoke test. It confirms your predictions parse and have the
right shape. It does NOT score recommendation quality.

For deeper scoring (keyword matching, multi-tier reasoning, fixture
citations), bring your own evaluator that compares each prediction
against the `handcrafted_recommendation.json` in the matching scenario
folder.

## Usage

```bash
python eval.py --predictions sample_predictions.json
```

## What it checks

1. The file parses as JSON.
2. There is a top-level `predictions` array.
3. Each prediction has the required fields.
4. Each `finding_type` is one of the three allowed values.
5. Each `primary_tier` is one of the allowed tier names (or null).
6. Each `action_category` is one of the allowed values.
7. Each `specific_change` is at least 20 characters.

## What it does NOT check

- Whether the recommendation engages with the right evidence.
- Whether multi-tier scenarios cite both tiers.
- Whether named fixtures from the metadata are referenced.
- Whether cost or projection numbers are reasonable.

Those checks are quality assessments. They depend on what you want to
score for and how strict you want to be. The dataset ships the gold
answers; the scoring method is up to you.

## Exit codes

- `0`: all predictions passed the Floor check.
- `1`: at least one prediction failed at least one check.
- `2`: usage error (missing file, malformed JSON).

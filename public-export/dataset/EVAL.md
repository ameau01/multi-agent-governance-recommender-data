# dataset/eval.py — Floor sanity check

A minimal check. Use this to confirm your predictions parse and have the
right shape. For Floor + Mid + Rich scoring, use `eval-set/eval.py`.

## Usage

```bash
python eval.py --predictions sample_predictions.json
```

## What it checks

1. The file parses as JSON.
2. There is a top-level `predictions` array.
3. Each prediction has the required fields.
4. Each `finding_type` is one of the allowed governance categories.
5. Each `primary_tier` is one of the allowed tier names (or null).
6. Each `action_category` is one of the allowed values.
7. Each `specific_change` is at least 20 characters.

## What it does NOT check

- Whether the recommendation engages with the right evidence.
- Whether multi-tier scenarios cite both tiers.
- Whether named fixtures are referenced.
- Whether cost or projection numbers are present.

Those checks live in `eval-set/`.

## Exit codes

- `0`: all predictions passed.
- `1`: at least one prediction failed at least one check.
- `2`: usage error (missing file, malformed JSON).

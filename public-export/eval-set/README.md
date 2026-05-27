# eval-set

Scoring code for the cloud-governance dataset. Three tiers: Floor, Mid,
Rich.

## What is here

- `eval.py`: the CLI scorer
- `tiers.py`: the check logic for Floor, Mid, Rich
- `expectations/NN/evaluation_expectations.json`: per-scenario values
  (allowed lists, keyword groups, fixture names)
- `sample_predictions.json`: a worked example of the prediction shape
- `EVAL.md`: what each check does
- `BASELINES.md`: how baseline agents score on this eval (TBD)

## Usage

```bash
python eval.py \
    --predictions your_predictions.json \
    --dataset ../dataset
```

If you cloned only this folder, you need a path to the dataset too. The
scorer reads `metadata.json` from each scenario to do the Rich fixture
check.

## Quick options

```bash
# Only Floor (parseable + on-topic)
python eval.py --tier floor --predictions x.json --dataset ../dataset

# Only Mid
python eval.py --tier mid --predictions x.json --dataset ../dataset

# Machine-readable JSON output
python eval.py --json --predictions x.json --dataset ../dataset > scores.json
```

## How the tiers map to checks

| Check                    | Floor | Mid | Rich |
|--------------------------|-------|-----|------|
| finding_type allowed     | x     |     |      |
| primary_tier allowed     | x     |     |      |
| action_category allowed  | x     |     |      |
| specific_change present  | x     |     |      |
| secondary_tier allowed   |       | x   |      |
| action keywords          |       | x   |      |
| multi-tier evidence      |       | x   |      |
| fixture citation         |       |     | x    |
| cost_impact quantified   |       |     | x    |
| projected_state quantified |     |     | x    |
| evidence structured      |       |     | x    |

A tier passes only if every check inside it passes.

## How to read the output

```
=========================================================================
   sid   floor     mid    rich  notes
  -----------------------------------------------------------------------
  01      PASS    PASS    PASS
  02      PASS    PASS    FAIL  rich:fixture_citation
  ...
  Totals: floor 18/18  mid 17/18  rich 12/18
=========================================================================
```

A failure note lists the failing check names. Use `--json` to get full
per-check detail.

## License

MIT.

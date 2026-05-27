# public-export — Design Decisions

**Purpose of this document.** A decision log for everything that shapes how the
contents of `public-export/` are organized and published. Decisions are written
in the form *options considered → what was chosen → why*. This document is the
single source of truth for design choices; implementation details and rationale
that don't affect external structure live in code comments.

This document is intentionally tight. It does NOT contain:

- The folder's actual contents (those will be the dataset and eval set).
- Empirical results from baselines (those live in `eval-set/BASELINES.md`
  once the eval is built).
- Mechanical instructions for building the export (those live in the build
  script, `scripts/build_public_export.sh`).

Last updated: 2026-05-26.

---

## 1. What `public-export/` is

`public-export/` is the staging area for two artifacts that will be published
together on Hugging Face as **a single repository with two self-contained
subfolders**:

- `dataset/` — the cloud-governance scenarios themselves (telemetry,
  infrastructure, gold-standard recommendations).
- `eval-set/` — a deterministic benchmark framework that scores predictions
  against the dataset across three tiers.

Both subfolders are designed to be usable independently by someone who clones
only one of them. Whatever overlaps between them (schemas, sample submissions,
shared docs) is duplicated rather than cross-referenced via relative paths
across folder boundaries.

The **generation pipeline** (Pass 1, Pass 2, validators, LLM-as-judge,
prompts, model names, etc.) lives in the private repository and is NOT
published. `public-export/` contains zero artifacts that would let a reader
reconstruct how the dataset was created.

---

## 2. Folder structure (final)

```
public-export/
├── README.md                          # top-level — links to both subfolders
├── LICENSE                            # MIT
├── design/                            # decision log (this folder)
│   └── DECISIONS.md                   # this file
├── dataset/                           # self-contained data product
│   ├── README.md
│   ├── DATASET_CARD.md                # HF dataset card
│   ├── LICENSE                        # MIT (duplicated for self-containment)
│   ├── eval.py                        # floor-competency sanity check
│   ├── EVAL.md                        # how to run the sanity check
│   ├── sample_predictions.json        # 2-3 scenarios showing submission shape
│   └── scenarios/
│       └── NN/                        # 01..18
│           ├── metadata.json          # sanitized
│           ├── main.tf
│           ├── *_telemetry.json       # 4 telemetry files
│           ├── correlation_evidence.json
│           └── handcrafted_recommendation.json
└── eval-set/                          # self-contained benchmark framework
    ├── README.md
    ├── LICENSE                        # MIT (duplicated)
    ├── eval.py                        # Floor + Mid + Rich deterministic eval
    ├── eval_with_judge.py             # OPTIONAL LLM-as-judge fallback
    ├── tiers.py                       # central Python module: tier semantics
    ├── BASELINES.md                   # trivial / random / single-shot / orchestrated
    ├── EVAL.md
    ├── sample_predictions.json        # mirrors dataset/sample_predictions.json
    └── expectations/
        └── NN/                        # 01..18
            └── evaluation_expectations.json   # per-scenario VALUES only
```

A `LICENSE` file is duplicated into each subfolder so a user who clones only
`dataset/` or only `eval-set/` still has the license at the top level.

---

## 3. Decision log

### D0 — Treat `public-export/` as the root for everything published

**Options.**

- A. One folder, two subfolders (`dataset/`, `eval-set/`).
- B. Two separate top-level folders at the repo root (`hf-dataset/`,
  `hf-eval/`).
- C. One folder with everything mixed together (no subfolders).

**Decision: A.** `public-export/` is the single root. `dataset/` and
`eval-set/` are siblings beneath it.

**Why.** The user wants a single Hugging Face repository so a reader sees both
artifacts in one place. Sibling subfolders make ownership and self-containment
obvious. Mixing (C) would force the eval to live next to the data and make
sanitization harder; separating to the repo root (B) would mean two HF repos,
which the user explicitly does not want.

---

### D1 — Subfolder naming: `dataset/` and `eval-set/`

**Options.**

- A. `dataset/` + `eval-set/`.
- B. `data/` + `benchmark/`.
- C. `scenarios/` + `evaluator/`.

**Decision: A** (`dataset/` and `eval-set/`).

**Why.** These are the conventional HF terms. A user landing on the HF page
will instantly understand which subfolder holds the data and which holds the
scoring code. `data/` is too generic; `benchmark/` overloads a word that often
refers to the full leaderboard.

---

### D2 — Where the gold-standard recommendation lives

**Options.**

- A1. Inside `dataset/scenarios/NN/handcrafted_recommendation.json`.
- A2. Inside `eval-set/expectations/NN/handcrafted_recommendation.json`.
- A3. Both (cross-linked).

**Decision: A1.** The handcrafted recommendation is part of the dataset; it
ships in `dataset/scenarios/NN/handcrafted_recommendation.json`.

**Why.** The recommendation is the **target**, not the scoring logic. Users
who clone only the dataset (e.g., for fine-tuning, or because they want to
build their own evaluator) need the gold standard. Users who clone only the
eval-set don't need it duplicated — `eval-set/eval.py` reads it from
`../dataset/scenarios/NN/` when both subfolders are present, and falls back
to telling the user to also clone the dataset when run standalone.

This decision was accepted **conditional on 18/18 passing the Rich tier**.
The handcrafted recommendation must be the orchestrated agent's gold output;
if any scenario can't be hand-authored to Rich-quality, the scenario itself
is reworked rather than the bar lowered.

---

### D3 — Should `dataset/` have its own `eval.py`?

**Options.**

- D3a. Yes — `dataset/eval.py` is a minimal floor-competency sanity check
  (does a prediction have the right shape and basic finding_type?).
- D3b. No — only `eval-set/eval.py` exists; `dataset/` is data-only.

**Decision: D3a.** `dataset/eval.py` exists and runs a minimal sanity check.

**Why.** A dataset published without ANY way to verify a prediction's shape
forces every downstream user to read code to figure out what they're
submitting. The dataset's `eval.py` answers one question only: "is this
output parseable and minimally on-topic?" — which is the floor competency
check. The full three-tier evaluation lives in `eval-set/`.

**What `dataset/eval.py` does.**

- Parses each prediction file (must be JSON, must have `finding_type`,
  `specific_change`, `primary_tier`).
- Validates against the schema in `dataset/sample_predictions.json`.
- Returns a single score per scenario: `parseable` (yes/no), `on_topic`
  (yes/no — finding_type is one of the allowed governance categories).

**What `dataset/eval.py` does NOT do.**

- It does not run the action-keyword check, multi-tier-evidence check, or
  fixture-citation check (those live in `eval-set/tiers.py`).
- It does not run the LLM judge.
- It does not depend on the `eval-set/` folder.

---

### D4 — Single HF repo vs. two repos vs. a packaged library

**Options.**

- A. Single HF repo with two self-contained subfolders.
- B. Two separate HF repos (one for data, one for the eval).
- C. One HF repo for the data and a separate Python package (PyPI) for the
  eval.

**Decision: A.** Single repo, two self-contained subfolders.

**Why.** The user does not have time to maintain two HF repos or publish a
Python package. Self-contained subfolders give the *appearance* of separation
(a user can clone only what they need) without the maintenance cost of two
repos.

Future migration to B or C is not blocked: each subfolder is already
self-contained, and both could be moved to separate repos later by simply
splitting the directory.

---

### D5 — Pydantic models

**Question.** The orchestration project (the agent that will be evaluated)
also needs Pydantic models for `Recommendation`, `Evidence`, etc. — should
those models be copied into `public-export/`?

**Decision: NOT in `public-export/`.** Pydantic models are an implementation
detail of two separate consumers (the private generation project, and the
public orchestration project). They are NOT part of the dataset or eval-set
contract.

**What `public-export/` exposes instead.**

- A JSON Schema document in `dataset/sample_predictions.json` plus a
  schema-by-example pattern.
- A `dataset/EVAL.md` that documents the expected fields in prose.
- No Python class definitions are published. Users in any language can
  produce a JSON file that matches the schema and run the eval.

Pydantic models for the orchestration project will be converted/copied in a
separate step in a separate repo; that work is tracked outside this
document.

---

### D6 — Tier semantics location

**Options.**

- A. Per-scenario JSON files hold all tier logic.
- B. Central Python module (`eval-set/tiers.py`) holds the logic; per-scenario
  JSON holds only the values.
- C. Hybrid — Floor in JSON, Mid + Rich in Python.

**Decision: B.** `eval-set/tiers.py` is the central Python module that
defines what Floor, Mid, and Rich mean. Per-scenario JSON files in
`eval-set/expectations/NN/evaluation_expectations.json` hold only the
*values* for that scenario (allowed `finding_type` values, action-keyword
groups, required fixture identifiers, etc.).

**Why.** Tier semantics are identical across all 18 scenarios; only the
expected values differ. Putting the logic in 18 JSON files would force
duplication of every conditional, and any tweak to a tier's definition would
require touching 18 files. The central module makes tier semantics auditable
in one place. Per-scenario JSON keeps the per-scenario values inspectable
without reading Python.

The same pattern is used by other deterministic evals (e.g., MMLU's
per-question keys are JSON; the scorer is one Python file).

---

### D7 — Sample predictions / submission format

**Options.**

- A. Include `sample_predictions.json` showing 2-3 scenarios in full.
- B. Include sample + JSON Schema (`predictions.schema.json`).
- C. Document in prose only.

**Decision: A.** Each subfolder ships a `sample_predictions.json` with 2-3
scenarios filled in (stub content, not the real gold answers). A JSON Schema
file is NOT included; the schema is documented in prose in `EVAL.md` and
demonstrated by example.

**Why.** Without a sample, first-time HF users have to reverse-engineer the
expected shape from the eval code. Including a sample makes the contract
self-evident. A full JSON Schema adds maintenance cost without much benefit
for a flat, small schema; we'll add one later if users ask for it.

The stub content in the sample is *not* the gold answer for those scenarios
— it's deliberately wrong so nobody confuses it with the real
`handcrafted_recommendation.json`.

---

### D8 — License

**Options.**

- A. Apache 2.0 for everything.
- B. MIT for everything.
- C. CC-BY-4.0 for data + Apache 2.0 for code (HF default split).
- D. Decide later.

**Decision: B.** MIT for both data and code.

**Why.** MIT is the simplest permissive license, has no patent clause to
worry about for a research dataset, and is well understood. The dataset is
synthetic (no third-party data with attribution requirements), so the
CC-BY-4.0 split doesn't add anything. Apache 2.0 would be fine but adds
boilerplate; MIT keeps the LICENSE file short.

`LICENSE` is duplicated into each subfolder so each is self-contained.

---

### D9 — Design doc scope

**Options.**

- A. Decisions only — keep this file tight.
- B. Decisions + architecture + planned baselines in one file.
- C. Multiple small docs (DECISIONS / ARCHITECTURE / EVAL_TIERS).

**Decision: A.** This file is a decision log only. Architecture is captured
by the folder tree in section 2. Empirical baselines and discriminating-power
evidence go in `eval-set/BASELINES.md` once the eval is built.

**Why.** A single tight decision log is easier to keep current than three
overlapping docs. Updates are cheaper. Anything tied to *what the eval
actually does* belongs near the eval (in `eval-set/`), not here.

---

### D10 — Reuse existing artifacts instead of re-generating

**Question.** The private generation pipeline already produced 18 gold-quality
recommendations and 18 per-scenario rubrics. Should `public-export/` use them
as-is, or re-author from scratch?

**Decision: reuse with sanitization.** No re-authoring. No new LLM passes.

**Mapping table.**

| Private artifact                          | Public-export destination                                                | How                                                              |
|-------------------------------------------|--------------------------------------------------------------------------|------------------------------------------------------------------|
| `intermediates/NN/smoke_test.json`        | `dataset/scenarios/NN/handcrafted_recommendation.json`                   | Drop `raw_model_response`, copy. No content edits.               |
| `src/qa/rubrics.py` (per-scenario dicts)  | `eval-set/expectations/NN/evaluation_expectations.json`                  | Emit each scenario's rubric dict as JSON.                        |
| `src/qa/deterministic_scorer.py`          | `eval-set/tiers.py`                                                      | Split checks into `score_floor` / `score_mid` / `score_rich`.    |
| `scenarios/NN/metadata.json`              | `dataset/scenarios/NN/metadata.json`                                     | Copy. Strip generation fields if any are present.                |
| `scenarios/NN/*_telemetry.json`           | `dataset/scenarios/NN/*_telemetry.json`                                  | Direct copy.                                                     |
| `scenarios/NN/correlation_evidence.json`  | `dataset/scenarios/NN/correlation_evidence.json`                         | Direct copy.                                                     |
| `scenarios/NN/main.tf`                    | `dataset/scenarios/NN/main.tf`                                           | Direct copy.                                                     |

**Why.** Re-authoring would discard hours of iteration that has already
produced passing recommendations. The deterministic scorer already validates
that each `smoke_test.json` meets the rubric, so the gold standard is
already proven correct against its own expectations.

**What this does NOT include.**

- Rich-tier check tightening (magnitude + cost, temporal precision) is new
  Python in `tiers.py`. The check logic is new; the gold answers it scores
  against are not.
- Baselines (trivial / random / single-shot / orchestrated) are new agent
  runs against the existing gold. Not gold-content changes.
- Sample predictions are degraded copies of real smoke_test outputs.
  Programmatic degrade, no hand-authoring.

---

## 4. Floor / Mid / Rich tier semantics

Tier definitions live in `eval-set/tiers.py` (per D6). This section is a
plain-language summary so a reader of the design doc understands what each
tier tests and why three tiers exist.

### Floor — competency

**Question.** Does the prediction look like a real cloud-governance
recommendation at all?

**Checks.**

- Valid JSON, parseable against the documented schema.
- `finding_type` is one of the allowed values for this scenario.
- `primary_tier` is one of the allowed values.
- `action_category` is one of the allowed values.

**What passes.** Almost any non-trivial agent — even a single-shot LLM
without orchestration — should pass Floor on 18/18.

**What fails.** Stub / random / "I don't know" baselines.

---

### Mid — depth

**Question.** Does the recommendation cite the right kinds of evidence and
propose actions matched to the actual problem?

**Checks (in addition to Floor).**

- Action keyword groups: the `specific_change` text contains keywords from
  N-of-M required groups (e.g., for an index-missing scenario, the text must
  mention at least one of `[create index, add index, build index]` AND one
  of `[btree, hash, gin]`).
- Multi-tier evidence: when the scenario's root cause spans two tiers
  (e.g., DB + cache), the recommendation must reference both.

**What passes.** A careful single-shot agent that actually reads the
telemetry can pass Mid on most scenarios.

**What fails.** Agents that guess based on scenario titles or that produce
generic recommendations without engaging with the evidence.

---

### Rich — orchestration

**Question.** Does the recommendation demonstrate the kind of cross-fixture
synthesis that only a multi-agent orchestration produces?

**Checks (in addition to Mid).**

- Fixture citation: the recommendation cites specific identifiers from the
  scenario's named fixtures (`top_queries`, `top_cache_keys`,
  `per_instance_breakdown`) — not generic descriptions.
- Magnitude + cost impact: the recommendation includes a quantified estimate
  tied to the cited fixtures.
- Temporal precision: the recommendation references the specific UTC time
  windows where the failure pattern is visible in telemetry.
- (Additional Rich-only checks tbd; tracked in `eval-set/BASELINES.md`
  once tuned against single-shot and orchestrated agents.)

**What passes.** Orchestrated agents that route subtasks across specialized
agents (telemetry triage, infra mapping, evidence synthesis) and feed the
named fixtures into a synthesis step.

**What fails.** Single-shot agents that don't read fixtures, and any
agent that produces narrative recommendations without quantification.

**Calibration target.** The Rich tier is tuned against two baselines:

- A strong single-shot baseline (frontier model, well-prompted, no tools)
  should score significantly under 18/18 on Rich — ideally 8-12/18.
- The orchestrated agent under development should score 18/18.

If a single-shot baseline reaches 17/18 or 18/18 on Rich, the tier is too
lenient and at least one check is tightened.

---

## 5. Sanitization rules

`public-export/` must contain ZERO trace of how the dataset was generated.
Specifically:

**Never present in `public-export/`:**

- Model names (`claude-opus-*`, `claude-sonnet-*`, `claude-haiku-*`).
- API key references, `.env` patterns, `langsmith` URLs/traces.
- Pass 1 / Pass 2 / chunker / planner / merger code or references.
- Prompt files (`prompts/pass1.txt`, `prompts/smoke_test.txt`, etc.).
- LLM-as-judge results (`smoke_test_judge.json`).
- Generation logs, cost meters, or any file in `intermediates/` or
  `logs/`.
- The string `target_recommendation` (renamed to `handcrafted_recommendation`
  everywhere).
- The word `rubric` in user-facing files (renamed to `expectations`).
- References to scenario authorship or the generation pipeline in any
  README or comment.

**Allowed to be present:**

- `handcrafted_recommendation.json` (the gold standard, presented as authored
  by hand).
- `evaluation_expectations.json` (the per-scenario expectations).
- Telemetry, infrastructure, and metadata JSON files (as the dataset
  contents).
- AWS-specific vocabulary (this is documented as a feature of the dataset,
  not hidden).

**Build-time check.** `scripts/build_public_export.sh` runs a sanitization
grep against the staging area before declaring the build successful. The
grep checks for every forbidden string above; any hit fails the build.

---

## 6. Voice and style for publish-bound content

This is a portfolio dataset. A reader landing on Hugging Face must believe a
human engineer wrote it. Long flowery prose is the easiest LLM tell. The rule
below applies to every file a reader sees.

**Applies to.**

- `public-export/README.md`
- `public-export/dataset/README.md`, `DATASET_CARD.md`, `EVAL.md`
- `public-export/eval-set/README.md`, `EVAL.md`, `BASELINES.md`
- Code comments and docstrings in `eval.py`, `tiers.py`,
  `dataset/eval.py`, `eval_with_judge.py`
- Any prose inside `handcrafted_recommendation.json` and
  `evaluation_expectations.json`
- `sample_predictions.json` comments and field descriptions

**Does NOT apply to.**

- This `DECISIONS.md` (internal design log).
- Schema field names.
- The folder tree itself.

**Rules.**

1. Short sentences. One idea per sentence. Long sentences feel generated.
2. Plain words. "Use" not "leverage". "Check" not "verify". "Make sure" not
   "ensure". "Show" not "demonstrate". "About" not "regarding". "Like" not
   "such as". "Pick" not "select".
3. No em-dashes. Use periods or commas. Em-dashes are an LLM tell.
4. No tricolons. "Fast, simple, and reliable" sounds written. Pick one or
   two adjectives.
5. Banned word list: delve, tapestry, navigate, embark, harness, robust,
   comprehensive, seamless, intricate, nuanced, underscore, highlight (as
   verb), pivotal, paramount, in the realm of, it is worth noting, plays a
   crucial role, foster, illuminate.
6. No hedging boilerplate. "It should be noted that X" becomes "X". "In
   order to X" becomes "to X".
7. Concrete over abstract. "Checks the action_category field" not
   "validates the categorical classification".
8. One verb per sentence when possible. "This module both X and Y" splits
   into two sentences.
9. Code comments stay one or two lines. Longer explanations move to a
   docstring or to `EVAL.md`.
10. No summary paragraphs at the start or end of a doc. Get to the point.
    No "this document covers..." preamble. No "in summary..." outro.
11. First person plural is fine ("we score predictions against..."). First
    person singular is fine ("I built this dataset to..."). Marketing
    voice ("empower users to...") is not.

**Test before publishing.** Read each file aloud. If it sounds like a tech
blog post, rewrite it. If it sounds like a teammate explaining the file in
Slack, ship it.

**How this is enforced.** A grep in `scripts/build_public_export.sh` checks
for the banned words. A manual review pass is required for sentence length
and tricolons (no good grep for those).

---

## 7. Versioning

Initial release: **v1.0.0**.

Subsequent releases follow semver:

- **MAJOR** — breaking change to the prediction schema or eval semantics
  (e.g., new required field, removed scenario).
- **MINOR** — new scenario, new tier check that can only be additive, new
  expectations file.
- **PATCH** — fixed typos, clarified docs, expanded allowed values for an
  existing check, no semantic change to what scores as pass/fail.

Version is recorded in `public-export/README.md` and in each subfolder's
`README.md`. The HF repo uses git tags matching the version.

---

## 8. Open questions deferred to implementation

The following are intentionally not decided in this document; they will be
decided when the corresponding code is written.

- Whether `eval-set/eval.py` accepts predictions as one big JSON file or as
  one file per scenario (will follow whichever shape is simpler in
  `sample_predictions.json` — likely one big file).
- Exact threshold values for the Rich tier "magnitude + cost impact" check.
  Tuned against baselines after the eval is built.
- Whether `eval_with_judge.py` is in the initial release or held back for
  v1.1. Lean: ship without it in v1.0, add in v1.1 once the deterministic
  eval is validated.
- Whether to publish a leaderboard. Out of scope for v1.0.

---

## 9. Change log for this document

| Date       | Change                                              |
|------------|-----------------------------------------------------|
| 2026-05-26 | Initial decision log captured.                      |
| 2026-05-26 | Added section 6: voice and style for publish-bound content. |

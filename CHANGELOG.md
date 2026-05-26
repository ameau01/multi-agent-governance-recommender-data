# Changelog

All notable changes to this project are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely.

This is a project changelog (planning and implementation milestones), not a released-product changelog. Semantic versioning is informational.

---

## [Unreleased]

Phase A — Foundations work begins here.

### Migrated — Tunable parameters now read from .env (2026-05-26)

The following parameters are now overridable via `DATAGEN_*` env vars in `.env`,
with their previous hardcoded values as defaults:

- `DATAGEN_PASS1_MODEL` (default: claude-sonnet-4-6)
- `DATAGEN_PASS2_MODEL` (default: claude-sonnet-4-6)
- `DATAGEN_SMOKE_TEST_MODEL` (default: claude-opus-4-6)
- `DATAGEN_SMOKE_TEST_JUDGE_MODEL` (default: claude-haiku-4-5-20251001)
- `DATAGEN_LLM_TEMPERATURE` (default: 0.3)
- `DATAGEN_MAX_RETRIES` (default: 3 — only applies to content failures, not auth)
- `DATAGEN_PASS1_MAX_TOKENS` (default: 64000)
- `DATAGEN_PASS2_MAX_TOKENS` (default: 64000)
- `DATAGEN_SMOKE_TEST_MAX_TOKENS` (default: 4096)
- `DATAGEN_JUDGE_MAX_TOKENS` (default: 50)
- `DATAGEN_BATCH_MODE` (default: false)

`src/generator/constants.py` is now the single source of truth — reads from
env at module import, exposes constants the rest of the codebase imports.
New CLI command `uv run python -m generator.cli config` prints the currently-
loaded values + whether each came from `.env` or default.

`.env.example` updated with all DATAGEN_* vars commented out (so the defaults
apply unless explicitly overridden). Architectural constants (RECORDS_PER_TIER,
DATA_WINDOW_START_UTC, INTERVAL_MINUTES) stay hardcoded — they're contract
invariants, not user-tunable.

### Added — .env safeguard tooling + commitment (2026-05-26)

After accidentally clobbering the user's `.env` during an earlier .gitignore
test (the contents were replaced with a 22-char placeholder `sk-ant-real-
secret-key` and not noticed until the auth error surfaced), added safeguards:

- `bin/check_env.sh` — validates `.env` length/prefix without exposing values.
  Checks that ANTHROPIC_API_KEY is real (not a placeholder, ≥50 chars,
  starts with `sk-ant-`), LANGSMITH_API_KEY is plausible if tracing is on.
  Returns non-zero exit code on failure with clear remediation guidance.
  Recommended to run before any paid command.
- Documented commitment in this CHANGELOG: assistant will not Write, Edit,
  copy, mv, cp, or echo into `.env` going forward. All future env-var
  testing is done via mocked `os.environ` inside Python test scopes,
  never by touching the user's `.env` file.

### Fixed — Anthropic SDK streaming requirement (2026-05-26)

`LLMClient.call()` was using `messages.create()`, which the Anthropic SDK
refuses for requests that may exceed 10 minutes (Pass 1 with
max_tokens=64000 hits this). Switched to `messages.stream()` with
`stream.get_final_message()`. Same response shape, no behavioral change,
no timeout cap. Added a heartbeat (`.` every 200 chunks) so long-running
Sonnet calls show progress in the log.

### Decided — Model assignments (2026-05-25)

Final model choices for the build, wired into `src/generator/constants.py`:

- **Pass 1**: Claude Sonnet 4.6 — reliable structured output and pattern adherence; fewer Phase B iteration cycles than Haiku.
- **Pass 2**: Claude Sonnet 4.6 — invariance preservation on large JSON inputs.
- **Smoke test recommendation**: Claude Opus 4.6 — strongest baseline check available; if Opus can't solve a scenario, the multi-agent system's depth is genuinely needed.
- **Smoke test LLM-as-judge**: Claude Haiku 4.5 — trivial yes/no comparison.

Estimated cost with prompt caching: ~$157 (over $150 budget by ~$7 — tight).
Estimated cost with Batch API + prompt caching: ~$79 (recommended path; $70+ headroom).

`BATCH_MODE_ENV_VAR` ("DATAGEN_BATCH_MODE") added to `constants.py` so the
forthcoming Phase B.6 Batch API code path can be toggled via env var without
touching the model assignments.

### Added — Batch API skeleton and manual oversight workflow (2026-05-25)

- **Batch API skeleton.** `src/generator/llm_client.py` gained a `BatchSubmitter`
  class (alongside the existing `LLMClient`) with `enqueue()` and
  `submit_and_wait()` methods stubbed for Phase B.6 implementation. Same models,
  same prompts, same parameters as `LLMClient` — therefore the same response
  quality. Only differences: 50% pricing, asynchronous, 5–30 min wall time.
- **Phase-level CLI commands.** `src/generator/cli.py` gained `pass1-all`,
  `pass2-all`, `validate-all`, `smoke-test-all`, plus the existing `build-all`.
  Each prints a cost + time preview and asks `Proceed? [y/N]` (skip with
  `--yes`). Each accepts `--batch` to opt into Anthropic Batches API.
- **`bin/run_oversight.sh`.** Interactive end-to-end walkthrough that runs all
  four phases with pauses for review. The recommended path for the first full
  build. Use `bash bin/run_oversight.sh --batch` for Batch API mode.
- **`bin/run_phase.sh`.** Convenience wrapper to trigger a single phase by name
  (`bash bin/run_phase.sh pass1 [--batch]`).
- **Makefile.** New targets: `oversight`, `oversight-batch`, `pass1-all`,
  `pass2-all`, `validate-all`, `smoke-test-all`, plus `-batch` variants of each.
- **Docs.** Execution guide's Phase C section updated to describe the supervised
  workflow as the recommended first-build path.

### Added — Resumable checkpoints + smoke test split (2026-05-25)

Goal: make Mac sleep, Ctrl-C, OOM, or network blips during a paid LLM run
recoverable without paying twice. Total budget impact on a clean run: zero.
Cost saving on an interrupted run: pro-rated to whatever fraction completed
before the interruption.

- **`src/generator/checkpoint.py`** (new, concrete code — not a stub):
  - `write_json_atomic(path, data)` — tmp-file-and-rename pattern; a partial
    file is never observable. Cleans up tmp on any interrupt including
    KeyboardInterrupt.
  - `write_pydantic_atomic(path, model)` — convenience for Pydantic models.
  - `is_scenario_complete(scenario_id, phase, ...)` — boolean check with
    optional Pydantic validation. Corrupt files treated as not-complete.
  - `partition_scenarios(ids, phase, ...) -> PhasePartition` —
    `(completed, remaining)` split. Used by every phase command to skip done work.
  - `checkpoint_path(scenario_id, phase, ...)` / `usage_path(...)` — canonical
    paths for per-scenario per-phase artifacts.
- **`src/qa/smoke_test.py`** refactored from one combined function into two
  separable phases:
  - **Phase 4: `smoke_test`** — `generate_smoke_test_recommendation()` per
    scenario, makes the Opus call, saves `SmokeTestRecommendation` to
    `intermediates/NN/smoke_test.json`. The expensive half (~$1.44 total).
  - **Phase 5: `smoke_test_judge`** — `judge_smoke_test_recommendation()` per
    scenario, reads saved recommendation, runs Haiku judge for
    `specific_change`, writes `SmokeTestJudgeResult` to
    `intermediates/NN/smoke_test_judge.json`. The cheap half (~$0.01 total).
  - Plus `*_all()` variants and `build_smoke_test_report()` for aggregation.
  - Recovery property: if Phase 5 is interrupted, Phase 4's Opus outputs are
    durable on disk — no Opus re-spending needed on resume.
- **`src/generator/cli.py`**:
  - New phase: `smoke-test-judge` (per-scenario) and `smoke-test-judge-all`
    (across all 18 scenarios).
  - New `--force` flag on phase-level commands — ignores existing checkpoints
    and re-runs everything.
  - `_print_phase_preview()` now shows resume reflection ("Already complete:
    12, Remaining: 6") and pro-rates cost + time estimates accordingly.
  - The `_run_phase` stub includes a concrete reference implementation in its
    `NotImplementedError` message, showing the exact resume pattern callers
    must follow.
  - `PHASE_ESTIMATES` extended with checkpoint filenames and `requires_phase`
    metadata so smoke-test-judge correctly declares its dependency on
    smoke-test having run first.
- **`bin/run_oversight.sh`** walks 5 phases instead of 4, with explicit
  callouts that all phases are resumable. New `--resume` flag for explicit
  intent (default behavior is the same — phase commands always detect and
  skip completed scenarios).
- **`Makefile`** gains `smoke-test-judge`, `smoke-test-judge-all`,
  `smoke-test-judge-all-batch`, and `resume` targets. The smoke-test-pilots
  target now also runs the judge.
- **`docs/execution-guide.md`** updated with the recovery workflow, per-scenario
  recovery commands, and the 5-phase table.

This is the largest behavioral change so far. Net effect for the user:
worst-case loss from an interruption is one in-flight scenario, not the full
phase budget.

### Restructured — Numbered per-phase scripts (2026-05-25)

The combined `bin/run_oversight.sh` walk-through was split into five
standalone per-phase scripts. The combined script still exists as an
optional all-in-one alternative. New numbered scripts (the primary path):

- `bin/01_pass1.sh` — Phase 1: Sonnet base telemetry generation
- `bin/02_pass2.sh` — Phase 2: Sonnet cross-tier correlation injection
- `bin/03_validate.sh` — Phase 3: QA validation (no LLM)
- `bin/04_smoke_test.sh` — Phase 4: Opus recommendation per scenario
- `bin/05_smoke_test_judge.sh` — Phase 5: Haiku judge on saved recommendations

Each script:
- Prints a banner with model + scenarios + cost + time + resume note.
- Wraps the corresponding `python -m generator.cli <phase>-all` invocation.
- Accepts the same `--batch`, `--yes`, `--force` flags as the CLI.
- Prints review hints (specific commands to run) after the phase completes.
- Points to the next script.

Makefile shortcuts: `make 01-pass1` through `make 05-smoke-test-judge`,
each accepting `FLAGS="..."` to pass flags through.

Deprecated: `bin/run_phase.sh` (the generic single-phase wrapper). It now
prints a deprecation notice and exits non-zero. Safe to delete with
`rm bin/run_phase.sh` from your terminal.

### Added — Environment + observability scaffolding (2026-05-25, post-skeleton)

- `.env.example` — template documenting the four required/optional env vars:
  `ANTHROPIC_API_KEY` (required), `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`,
  `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`.
- `src/generator/llm_client.py` now loads `.env` at module import via
  `python-dotenv`, and constructs the Anthropic client through
  `_make_anthropic_client()`, which conditionally wraps with
  `langsmith.wrappers.wrap_anthropic` when `LANGSMITH_TRACING=true`. Wrapping
  is fully transparent — call sites are unchanged.
- `src/generator/cli.py` calls `load_dotenv()` at module level as a defensive
  measure so env vars are populated before any subcommand dispatches.
- `LLMClient.call()` now accepts an optional `metadata: dict` parameter that
  is attached to the LangSmith trace for that call (ignored when tracing is off).

### Changed — Dependencies

- Added `python-dotenv>=1.0` for `.env` loading.
- Added `langsmith>=0.1` for tracing.

### Added — Automatic prompt caching (2026-05-25)

- Prompt templates now use a `SYSTEM:` / `USER:` section structure with optional
  `<<<CACHE>>>` markers in the USER section to designate cache breakpoints.
- `prompts/pass1.txt` restructured with one `<<<CACHE>>>` marker after the stable
  boilerplate (TIME-PATTERN RULES, HEALTHY BASELINES, OUTPUT SCHEMA, REQUIREMENTS).
  Per-scenario content (SCENARIO / BUSINESS CONTEXT / PASS 1 METRIC RANGES) is in
  the variable tail.
- `prompts/pass2.txt` restructured with two `<<<CACHE>>>` markers: after the stable
  boilerplate and after the Pass 1 JSON input. Per-scenario correlation rules are
  in the variable tail.
- `src/generator/llm_client.py` added helpers `_parse_prompt_template`,
  `_build_message_content`, and `_strip_markdown_fencing`. `LLMClient.call()`
  automatically parses prompt structure and applies `cache_control: ephemeral`
  to system + each pre-marker user block.
- Full caching strategy documented in `docs/internal/generation-methodology.md` §8.

Caching is fully automatic — call sites never touch cache markers. The prompt
template's structure dictates the layout. Expected savings:
- Pass 1: ~67% reduction in input cost on the cached portion (boilerplate
  shared across all 18 scenarios × ~5 chunks each).
- Pass 2: ~90% reduction in input cost on the Pass 1 JSON portion during
  within-scenario retries (the dominant cost during Phase B prompt iteration).

---

## [0.1.0] — 2026-05-25

### Planning complete

This release marks the end of the planning phase. The data-generation sub-project has a complete plan, full per-scenario specifications, supporting documentation for healthy baselines, generation methodology, generation conventions, and generation-side QA, plus LLM prompt scaffolds for Pass 1 and Pass 2. Implementation (Phase A) is ready to begin.

### Added — Project plan and documentation

- `README.md` — project-facing README with structure, key docs, and relationship to the agent project.
- `BUILD_PLAN.md` — execution-focused phase-by-phase plan with concrete code deliverables, file paths, and exit criteria.
- `CHANGELOG.md` (this file).
- `docs/data-generation-plan.md` — the canonical project plan; supersedes the v3 dataset doc PDF.
- `docs/REVIEW_dataset_vs_agent_alignment.md` — history of alignment reviews against the agent project (v1, v1.1, v1.2).

### Added — Internal generation materials (gitignored)

These are working materials for the pipeline. Per `.gitignore`, they are not part of the public repository.

- `docs/internal/healthy-baselines.md` — per-metric healthy ranges for every field in the v1.2 schema, time-pattern conventions, negative-scenario deviation guidance.
- `docs/internal/generation-methodology.md` — Pass 1 / Pass 2 / metadata / Terraform / QA pipeline mechanics.
- `docs/internal/generation-conventions.md` — field semantics (TopQuery.count time unit, etc.), data-window constants, SLA derivation rule.
- `docs/internal/generation-qa.md` — semantic QA checks beyond the contract's structural validation ("did we generate what we specified").
- `docs/internal/scenario-quality-smoke-test.md` — lightweight pre-handoff QA check that runs each scenario through a single LLM call and verifies the data is sufficient to reach the target recommendation ("are the scenarios solvable").
- `docs/internal/scenarios/01.spec.yaml` through `18.spec.yaml` — the 18 per-scenario specifications, re-derived from the v3 dataset doc §6 into the v1.2 contract field set.

### Added — Prompt scaffolds

- `prompts/pass1.txt` — Pass 1 (base telemetry per tier) LLM prompt template.
- `prompts/pass2.txt` — Pass 2 (correlation injection) LLM prompt template.

### Changed — Repository structure

- Moved historical reference PDFs into `docs/reference/`:
  - `docs/reference/Cloud_Governance_Dataset_Generation_Plan_v3.pdf`
  - `docs/reference/Cloud_Governance_Agent_System_Design_v1.pdf`
- Moved `REVIEW_dataset_vs_agent_alignment.md` into `docs/`.
- Updated `pyproject.toml`: real project description, declared core dependencies (`pydantic`, `jinja2`, `python-hcl2`, `pyyaml`, `anthropic`), and dev extras (`pytest`, `ruff`, `mypy`).
- Updated `.gitignore`: explicitly ignores `docs/internal/`, `intermediates/`, plus standard Python tooling/IDE/OS noise.

### Coordination — alignment with the agent project's v1.2 contract

The shared data contract is owned canonically by `cloud-governance-agent` and synced into this project. Pinned for v0.1.0:

- Contract version: `1.0.0`
- Contract spec lands at `docs/contract-spec.md` (synced verbatim from agent's `docs/12-shared-contract.md`) during Phase A.
- Pydantic package lands at `src/contracts/` during Phase A.

### Notes — what is *not* in this release

The data-gen pipeline itself (`src/generator/`, `src/qa/`) is not in this release. The scenarios under `scenarios/` are not in this release. Both are Phase A–C deliverables.

---

## Reference: project version vs. contract version

These are independent:

- **Project version** (`pyproject.toml`) tracks this project's planning and implementation milestones.
- **Contract version** (`src/contracts/version.py`) tracks the shared data contract; bumped only when the contract shape changes.

For v0.1.0 of this project, the contract is `1.0.0`.

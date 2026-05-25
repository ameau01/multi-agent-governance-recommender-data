# Changelog

All notable changes to this project are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely.

This is a project changelog (planning and implementation milestones), not a released-product changelog. Semantic versioning is informational.

---

## [Unreleased]

Phase A — Foundations work begins here.

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
- `docs/internal/generation-qa.md` — semantic QA checks beyond the contract's structural validation.
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

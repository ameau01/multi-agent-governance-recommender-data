# Cloud Governance Data Generation

> Synthetic-data generation pipeline for the Cloud Governance multi-agent recommender system.

This project produces **18 hand-crafted, contract-conformant scenario datasets** that the [`cloud-governance-agent`](https://github.com/your-org/cloud-governance-agent) project consumes for evaluation. Each scenario is reverse-engineered from a known target recommendation, giving the multi-agent system a ground-truth eval set that real cloud telemetry could not provide.

**Status:** Planning complete. Phase A (foundations) ready to start.

---

## What this project produces

For each of 18 scenarios (`01` through `18`), the pipeline emits a self-contained folder of seven files:

```
scenarios/07/
├── metadata.json              # rich scenario summary, Pydantic-validated
├── compute_telemetry.json     # 1,344 records or []
├── database_telemetry.json    # 1,344 records or []
├── cache_telemetry.json       # 1,344 records or []
├── network_telemetry.json     # 1,344 records or []
├── correlation_evidence.json  # cross-tier correlations, [] if none
└── main.tf                    # HCL infrastructure stub, generated from metadata
```

Every file validates against the **shared data contract** specified in [`docs/contract-spec.md`](docs/contract-spec.md) (synchronized from the agent project). The shape is enforced by Pydantic models in `src/contracts/`.

---

## What this project is

- A two-pass LLM-driven telemetry synthesizer (Pass 1 for per-tier base time-series, Pass 2 for cross-tier correlation injection).
- A deterministic metadata generator that builds the consumer-facing `metadata.json` from per-scenario spec YAMLs.
- A Jinja-based Terraform renderer that derives `main.tf` from the same metadata that drives telemetry — single source of truth, no metadata-vs-Terraform drift.
- A QA validator that runs both contract-level (Pydantic) and semantic (pattern frequency, Pass 2 invariance, correlation timing, etc.) checks.

---

## Why this project exists

Three reasons:

- **Ground truth.** Real cloud telemetry does not come with known-correct recommendations attached. Synthetic data with reverse-engineered targets is the only viable way to objectively evaluate a multi-agent recommender.
- **Coverage of edge cases.** The 18 scenarios deterministically exercise the behaviors that distinguish a sophisticated recommender from a naive optimization tool — restraint, diagnostic deferral, cross-tier synthesis, trade-off reasoning.
- **Decoupling from cloud account state.** A portfolio implementation must run locally on any machine without an AWS account.

---

## Project status

| Phase | Status | Window |
|---|---|---|
| Planning | ✅ Complete (2026-05-25) | — |
| **Phase A — Foundations** | ⏳ Ready to start | Days 1–3 |
| Phase B — Pipeline | ⏸ Pending | Days 4–7 |
| Phase C — Full run + handoff | ⏸ Pending | Days 8–10 |

See [`BUILD_PLAN.md`](BUILD_PLAN.md) for the execution-focused phase plan and per-phase task list.

---

## Repository structure

```
cloud-governance-data-gen/
├── README.md                                 # this file
├── BUILD_PLAN.md                             # phase-by-phase execution plan
├── CHANGELOG.md                              # change history
├── pyproject.toml                            # Python project metadata + deps
├── main.py                                   # entry point (placeholder)
├── docs/
│   ├── data-generation-plan.md               # the canonical project plan
│   ├── contract-spec.md                      # synced from agent project (Phase A)
│   ├── REVIEW_dataset_vs_agent_alignment.md  # alignment review with agent v1.2
│   └── reference/                            # historical reference materials
│       ├── Cloud_Governance_Dataset_Generation_Plan_v3.pdf
│       └── Cloud_Governance_Agent_System_Design_v1.pdf
├── prompts/                                  # LLM prompt templates
│   ├── pass1.txt
│   └── pass2.txt
├── src/                                      # implementation lands here (Phase A onward)
│   ├── contracts/                            # synced from agent project (Phase A)
│   ├── generator/                            # pass1, pass2, metadata, terraform
│   └── qa/                                   # qa_validator.py
├── scenarios/                                # OUTPUT — produced by the pipeline
│   ├── 01/
│   ├── ...
│   └── 18/
└── docs/internal/                            # NOT CHECKED IN — see .gitignore
```

**Note on `docs/internal/`.** The detailed per-scenario spec YAMLs, healthy baselines, generation methodology, generation conventions, and generation-side QA notes are working materials for the pipeline. They are intentionally not part of the public repository — see `.gitignore`.

---

## Key documentation

For someone landing on this repo, read in this order:

| Read this | To understand |
|---|---|
| [`README.md`](README.md) (this file) | What the project is and where to find things |
| [`docs/data-generation-plan.md`](docs/data-generation-plan.md) | The canonical project plan — what we produce and why |
| [`BUILD_PLAN.md`](BUILD_PLAN.md) | The execution plan — Phase A → B → C, concrete deliverables |
| [`docs/contract-spec.md`](docs/contract-spec.md) | The data contract this project produces against (synced from agent project) |
| [`docs/REVIEW_dataset_vs_agent_alignment.md`](docs/REVIEW_dataset_vs_agent_alignment.md) | History of how the contract evolved across review cycles |

---

## Relationship to the agent project

The two projects are coordinated by the shared data contract:

```
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│  cloud-governance-data-gen      │         │  cloud-governance-agent         │
│  (this project — PRODUCER)      │         │  (CONSUMER)                     │
│                                 │         │                                 │
│  Pipeline:                      │         │  Multi-agent system:            │
│   • Per-scenario specs          │         │   • Supervisor                  │
│   • Pass 1 LLM (telemetry)      │         │   • System Mapper               │
│   • Pass 2 LLM (correlations)   │         │   • Tier Specialists × 3        │
│   • Metadata generator          │ ──────► │   • Cross-Tier Evaluator        │
│   • Terraform renderer (Jinja)  │         │   • Data Service                │
│   • Semantic QA                 │         │   • Audit trail                 │
│                                 │         │                                 │
│  Output: scenarios/NN/ folders  │         │  Eval: R1–R5 rubric scoring     │
└─────────────────────────────────┘         └─────────────────────────────────┘
              ▲                                            │
              │                                            │
              └───────── shared data contract ─────────────┘
                       (canonical in agent project)
                       (synced verbatim to this project)
```

- The contract — `docs/contract-spec.md` plus `src/contracts/*.py` — is owned canonically by the agent project. This project carries a synchronized copy.
- The boundary between projects is the contract. Within that boundary, this project has full autonomy over generation conventions, prompt design, scenario narratives, healthy baselines, and pipeline mechanics.
- Contract version is `1.0.0`. Sync procedure is documented in `src/contracts/CONTRACT_SYNC.md` (lands during Phase A).

---

## Getting started (when implementation begins)

1. **Receive the contract package** from the agent project (their Phase 1 deliverable) and drop it into `src/contracts/`.
2. **Read [`BUILD_PLAN.md`](BUILD_PLAN.md)** for the phase plan.
3. **Phase A** (foundations): metadata generator + Terraform renderer + contract sanity check. No LLM yet.
4. **Phase B** (pipeline): Pass 1 generator + Pass 2 generator + QA validator. LLM-driven.
5. **Phase C** (full run + handoff): all 18 scenarios validated and committed under `scenarios/`.

---

## License

To be determined.

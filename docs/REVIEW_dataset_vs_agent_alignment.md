# Data-Gen ↔ Agent v1.2 Alignment Review

**Reviewer pass dates:**
- Initial pass: 2026-05-24 (agent v1 ↔ dataset v3)
- Re-review: 2026-05-24 (agent v1.1)
- **Current pass: 2026-05-25 (agent v1.2 + data-gen-handoff.zip)**

**Documents in scope (current):**
- `Cloud_Governance_Agent_System_Design_v1.2.pdf`
- `cloud-governance-agent-v1.2.zip` (`CHANGELOG.md`, `BUILD_PLAN.md`, `docs/02-agents.md`, `docs/03-harnesses.md`, `docs/04-data-service.md`, `docs/12-shared-contract.md`)
- `data-gen-handoff.zip` (`README.md`, `docs/contract-spec.md`)
- `Cloud_Governance_Dataset_Generation_Plan_v3.pdf` (now demoted from spec to source-of-truth narrative — see below)

This review focuses on **data generation**, per the user request.

**Framing clarification (added after first re-review):** The contract is the consumer-facing API surface — file layout, Pydantic field names and types, Data Service method names. Within that boundary, the data-gen project has full autonomy over *how* the data is produced: healthy-baseline conventions, scenario specs, two-pass mechanics, prompt design, internal QA. The patches in §5 are written with that boundary in mind: each one lives inside the data-gen repo, the consumer's API surface is untouched, and the contract stays at `1.0.0`.

---

## 1. What v1.2 changed for data generation

The v1.2 update is a substantial restructure of the dataset side, not a patch. The data-gen sub-project is no longer driven by the dataset doc v3; it is now driven by a **shared Pydantic contract** that both projects synchronize.

### Architectural shifts

| Concern | v3 dataset doc | v1.2 contract |
|---|---|---|
| Deliverable shape | One bundle JSON per scenario (Compute_Metrics / Database_Metrics / … inside one file + sidecar) | **Seven-file folder per scenario**: `metadata.json`, four `*_telemetry.json`, `correlation_evidence.json`, `main.tf` |
| Scenario IDs | Integer 1–18 | Zero-padded strings `"01"`–`"18"`; agent refers to them as `app01`–`app18` |
| Terraform stub ownership | v1 ambiguous → v1.1 said agent project → **v1.2 now data-gen project** (Jinja from metadata, single source of truth) |
| Schema enforcement | Prose schema tables | Pydantic models with `extra="forbid"`, validated on construction and on load |
| Versioning | `bundle_version: "v3"` in JSON | First-class `CONTRACT_VERSION = "1.0.0"` semver constant; mismatch is a hard failure at load time |
| Cross-project coordination | None | `docs/contract-spec.md` is a **verbatim copy** of the canonical agent doc; `CONTRACT_SYNC.md` documents the sync procedure |
| Vocabulary | "sidecar", "bundle", "input package" | "scenario metadata", "scenario folder", "app_name" |
| Cross-tier correlation | Runtime read op (`get_correlation_evidence`) | **Precomputed and stored** in `correlation_evidence.json`, plus runtime read |
| Read surface | 15 abstract operations | ~89 concrete methods, one parameter (`app_name`) each, partitioned per-caller |

### Telemetry field schema (substantially changed)

Worth calling out by tier because the v3 §6 scenario specs reference fields that no longer exist.

**Compute**
- Removed: `cpu_p90`, `memory_p50`, `memory_p90`
- Added: `network_in_p95`, `network_out_p95`, optional `instance_id` (for Scenario 5 per-instance breakdown)

**Database**
- Removed: `cpu_p90`, `slow_query_percent`
- Renamed: `connections_p95` → `db_connections_p95`
- Added: `db_connections_p50`, `db_cache_hit_ratio`, `db_io_wait_p95`

**Cache** (previously just `hit_ratio`)
- Added: `cache_evictions_per_sec`, `cache_memory_used_pct`, `cache_connections`

**Network**
- Renamed: `p95_latency_ms` → `network_p95_latency_ms`, `error_rate` → `network_error_rate`
- Added: `network_throughput_p95`

This is the single biggest practical consequence of v1.2 for the data-gen project: the existing 18-scenario narratives in v3 §6 are written in terms of `cpu_p90`, `memory_p50`, `slow_query_percent`, etc., and will not transcribe directly. See Gap B below.

---

## 2. All six items from my previous review — status under v1.2

| Item | v1.1 status | v1.2 status |
|---|---|---|
| Gap 1 — Terraform stubs ownership + bundle definition | Resolved by v1.1 vocabulary (agent owns) | **Re-resolved differently** — data-gen now owns Terraform, generated from metadata via Jinja. Cleaner than v1.1 because there is no metadata-vs-Terraform drift risk |
| Gap 2 — `per_instance_imbalance` undeclared | Half-resolved (agent side) | **Fully resolved** — renamed `per_instance_breakdown`, has its own `InstanceBreakdown` Pydantic model, lives under `ScenarioSpecificEvidence` |
| Minor 1 — `scenario_type` enum drift | Pending | **Resolved** — enum is formally declared in `enums.py`: `SINGLE_TIER_NEGATIVE`, `SINGLE_TIER_MILD_NEGATIVE`, `CROSS_TIER_NEGATIVE`, `MIXED`, `HEALTHY`, `MOSTLY_HEALTHY`, `DIAGNOSTIC_DEFERRAL`. `DIAGNOSTIC_DEFERRAL` is now a first-class scenario type |
| Minor 2 — `manifest.json` spec | Pending | **Made moot** — no top-level manifest; each scenario folder is self-describing via its own `metadata.json` |
| Minor 3 — `bundle_version` field | Pending | **Resolved** — replaced by first-class `contract_version` field on every `metadata.json`, with semver enforcement on load |
| Minor 4 — Load-balancer action whitelist | Resolved by v1.1 (agent doc) | **Now in contract** — `LOAD_BALANCER_RECONFIGURATION` is a first-class `ActionCategory` enum value |

All six prior items are resolved. The v1.2 restructure is a real improvement, not a renaming exercise.

---

## 3. New items the v1.2 restructure introduces

The v1.2 update solved the prior gaps cleanly but opened a different class of gap: **content migration**. The contract specifies the *shape* of the data, but the data-gen project needs more than shape to actually generate the 18 scenarios. The v3 dataset doc carried generation-relevant material (healthy baselines, full scenario specs, Pass 1/Pass 2 prompts, semantic QA checks) that has not been carried forward into either the contract or the handoff package.

Below, "HIGH" = blocks the data-gen team from starting code generation cleanly; "MEDIUM" = will be hit during implementation and is better answered upfront; "LOW" = doc-completeness, can be fixed later.

### Gap A — Healthy baselines per metric are not defined for the new field set (HIGH)

The Data Service exposes a `breaches` operation (returns timestamps where a metric exceeded its healthy band) for every telemetry metric. Both the generator (to know what "healthy" looks like) and the consumer (to know what counts as a breach) need the same healthy bands.

v3 §5.2 defined healthy ranges for the old field set:
- `cpu_p50: 40–60%`, `cpu_p90: 55–72%`, `memory_p50: 45–60%`, `memory_p90: 55–72%`
- `slow_query_percent: 0.5–2.5%`, `db_query_p95_latency_ms: 30–120`
- Cache: only `hit_ratio: 88–96%`

Under v1.2 the schema dropped `cpu_p90`, `memory_p50`, `memory_p90`, `slow_query_percent`, and added 8 new fields across the four tiers. The contract's per-field validators only enforce `0–100%` / non-negative — they don't define a healthy band.

**Action:** Add a "Healthy Baselines" appendix to the contract spec (or as a sibling doc in the handoff) covering every new field, including `memory_p95`, `network_in_p95`, `network_out_p95`, `db_connections_p50`, `db_cache_hit_ratio`, `db_io_wait_p95`, `cache_evictions_per_sec`, `cache_memory_used_pct`, `cache_connections`, `network_throughput_p95`. Without this, the Pass 1 generator has no grounding for "healthy" and the agent's `breaches` operation has no threshold to compare against.

### Gap B — The 18 scenario specs from v3 §6 do not transcribe to the new schema (HIGH)

This is the single biggest practical problem. The v3 dataset doc § 6 contains detailed specs for all 18 scenarios — `Business Context`, `Current Configuration`, `Key Metrics` (in terms of cpu_p90, memory_p50, slow_query_percent, etc.), `Time Pattern`, `Cross-Tier Correlation`, `Target Recommendation`, `Before/After`. These are the source-of-truth for what each scenario *means*.

After the v1.2 schema change:
- Scenarios 1, 2, 11 (compute-only): reference `cpu_p90`, `memory_p50`, `memory_p90` — all gone.
- Scenarios 3, 4, 8 (database): reference `cpu_p90`, `slow_query_percent` — both gone. Scenarios 4 and 8 are *built around* `slow_query_percent` as the primary signal.
- Cache scenario 7: written against single-field `hit_ratio` baseline; new schema has four cache fields, so the spec needs richer healthy/unhealthy ranges for evictions, memory_used_pct, connections.

The data-gen project receives the contract (shape) but not the re-derived scenario specs (content). The handoff README says "Build the metadata generator — produces the rich `metadata.json` including the narrative section," but does not say where the source-of-truth for that narrative content lives. Without per-scenario specs, the generator either has to (a) hallucinate the narrative for each scenario from scratch or (b) ingest the v3 §6 narrative and re-derive the field mappings on the fly — neither is ideal.

**Action:** Either:
- (a) Add 18 per-scenario `scenario_spec.yaml` stubs to the handoff package (one per scenario), with the v3 §6 narrative re-mapped to the new field set. Each stub would carry: business context, current configuration in `TierTopology` shape, key metric ranges in the new fields, time pattern, Pass 2 correlation spec, target recommendation. This is ~18 × 30 lines of YAML, mostly mechanical translation.
- (b) Add an explicit mapping table (v3 field → v1.2 field equivalents, with notes for fields with no clean equivalent) and explicitly designate v3 §6 as the narrative source-of-truth, leaving translation to data-gen Phase 1 work.

Option (a) is significantly safer because it forces the translation decisions to be made once, in writing, before code generation starts. Option (b) is faster but pushes ambiguity into the LLM-driven generator, which is exactly where it is hardest to debug.

### Gap C — `TopQuery.count` has no time unit (MEDIUM)

v3 used `calls_per_hour: 14000`. v1.2 has `count: int` with no time unit attached. Is `count` total over the 14-day window? Per hour? Per day?

This matters because:
- The generator needs to know what number to emit.
- The Data Layer Analyst will reason about query volume, and the absolute scale changes its conclusions.
- The R3 specificity rubric will score "optimize the top 5 queries (≈14k/hour)" against the agent's output — and the agent has to read `count` and decide whether it's enough to justify the recommendation.

**Action:** One of: docstring/comment on `count` ("total executions observed over the 14-day window"), or rename to `calls_total_14d` / `calls_per_hour` to be self-documenting.

### Gap D — `TopCacheKey.hit_count` / `miss_count` have no time unit (MEDIUM)

Same issue as Gap C, applied to cache. v3 had `traffic_share` (percent). v1.2 has raw counts with no window stated. Same fix needed.

### Gap E — Pass 1 / Pass 2 generation methodology is no longer documented (MEDIUM)

v3 §3 defined the two-pass approach in detail (Pass 1 = independent per-tier base time-series, Pass 2 = correlation injection + before/after inlining, with strict Pass 2 invariance for uncorrelated tiers). v3 §7 provided ready-to-use LLM prompt scaffolds for both passes. v3 §8.1 included a Pass 2 invariance QA check.

None of this is carried into the contract or the handoff. The handoff README mentions "Pass 1 generator" and "Pass 2 generator" in workflow step 3–4 but doesn't explain how:
- The two-pass approach maps onto the new four-separate-telemetry-files layout (does Pass 1 emit all four in one LLM call, one per tier, or one file at a time?).
- Pass 2 reads back, injects correlations, and rewrites (which files? which subset?).
- `correlation_evidence.json` is produced — by Pass 2 alongside the telemetry rewrite, or as a separate post-pass?

This is correctly outside the contract's scope (the contract governs data at rest, per §12.10). But the data-gen team will need this methodology to actually build the pipeline.

**Action:** Either preserve v3 §3 and §7 verbatim as a sibling doc in the handoff package (updated for the new file layout and field set), or state explicitly in the handoff README that the two-pass methodology is data-gen's implementation choice, with v3 §3/§7 as a recommended starting point.

### Gap F — Per-scenario correlation specifications are not carried over (MEDIUM, paired with B)

v3 §6 specified correlations per scenario very precisely. Example, Scenario 7 Pass 2: "When cache hit_ratio drops below 72%, database cpu_p90 rises by 38–45% above its Pass 1 baseline range, and application_p95_latency_ms rises by 180–250ms above its baseline. Effect appears within the same 15-min window."

The contract's `CorrelationPair` model carries `coefficient`, `lag_minutes`, `alignment_score` — post-hoc summary, not a generation specification. To produce the correlated telemetry, the data-gen pipeline needs the original "trigger → effect" specs.

If Gap B is resolved with `scenario_spec.yaml` stubs, this comes along automatically (each spec carries Pass 2 correlation instructions). If Gap B is resolved by pointing to v3 §6 as narrative source-of-truth, the correlation specs need to be explicitly preserved as part of that pointer.

**Action:** Folded into Gap B.

### Gap G — Generation-side semantic QA is not specified (MEDIUM)

v3 §8.1 defined 12+ semantic QA checks beyond pure schema validation: pattern frequency ("at least 11 of 14 days"), weekend behavior, Pass 2 invariance, correlation timing, correlation magnitude (relative to baseline), no-spurious-correlation between tiers marked `Cross-Tier Correlation: None`, sidecar field presence per scenario. v3 §8.3 even had a Python validator sketch.

The new contract's §12.6 covers structural validation (record count, timestamp continuity, cross-tier alignment, topology-vs-telemetry consistency, scenario-specific evidence presence) — necessary but not sufficient. A pipeline that passes only §12.6's checks could still ship telemetry where the "healthy" Scenario 6 looks indistinguishable from the "chronic underutilization" Scenario 1. The scenario-distinguishing checks were exactly what v3 §8 was guarding.

**Action:** Carry forward v3 §8.1 checks as a generation-side QA spec in the handoff (updated for new fields), or explicitly say "generation-side QA beyond §12.6 is the data-gen project's responsibility; v3 §8 is a recommended starting point."

### Gap H — Implementation conflict between handoff README and agent BUILD_PLAN on who writes the Pydantic models first (LOW)

- Handoff README workflow step 2: "Implement `src/contracts/*.py` as described in the spec — Pydantic models, enums, version constant. Estimated ~390 lines." This reads as "data-gen project writes their own copy from the spec."
- Agent `BUILD_PLAN.md` Phase 1: "Shared data contract package… Both this project and the data-gen project use the same models. **The agent project owns the canonical version.** Includes the sync procedure for keeping the data-gen project's copy aligned."

These are not contradictory, but they describe two different workflows. The build-plan framing is correct (one canonical Pydantic, sync to data-gen) and is also safer — independent implementation against the same spec invites subtle drift in `Field(...)` constraints.

**Action:** Update the handoff README workflow step 2 to read "Receive `src/contracts/*.py` from the agent project once it is implemented in Phase 1; do not author independently." Or have the agent project produce the Pydantic package as the first work in Phase 1 and ship an updated handoff zip including those files.

### Gap I — `metadata.json.generated_at` vs. data-window start timestamp ambiguity (LOW)

§12.6 says "The first timestamp MUST be Monday 00:00 UTC of the dataset's start week (2026-05-01 for v3 dataset; check `metadata.json.generated_at` for actual)." But `generated_at` is described as the file's generation timestamp, not the data window's start. The "for actual" wording invites confusion.

**Action:** Add a `DATA_WINDOW_START` constant to the contract (or a `metadata.json.data_window_start_utc` field), and reserve `generated_at` for pipeline-run timestamps.

### Gap J — Duplicated SLA representation in `BusinessContext` (LOW)

`BusinessContext` carries both `sla_target_description: str` and the structured `sla_target_p95_ms`, `sla_target_availability_pct`. The generator must keep them consistent; nothing in the contract enforces it.

**Action:** Either drop the description (let consumers format from the structured fields), or add a §12.6 validation rule asserting consistency.

---

## 4. Verdict

The v1.2 restructure is a substantive improvement. Every coordination gap from the prior review is cleanly resolved — most importantly, the contract is now an enforced Pydantic boundary, not a prose schema. The Terraform single-source-of-truth via data-gen Jinja is also a strictly better solution than v1.1's "agent hand-authors stubs alongside scenarios."

All the gaps below are real, but on reflection most of them are *inside the data-gen project's autonomy*, not contract-level coordination problems. The contract defines the **consumer-facing API surface** — file layout, Pydantic field names and types, Data Service method names. As long as data-gen produces files that validate against that contract, it has full discretion over *how* the data is generated (healthy baselines, scenario specs, two-pass mechanics, internal QA, prompt design). The patches below are framed that way: each one lives inside the data-gen repo, the consumer's API surface is untouched, and contract version stays at `1.0.0`.

---

## 5. Patches — all within data-gen autonomy, no contract changes

For each gap, the patch is: **what to author, where it lives, what (if anything) the consumer needs to know.**

### Gap A — Healthy baselines for the new field set

- **Classification:** Internal data-gen artifact. The contract's per-field validators only guarantee `0–100%` / non-negative; "healthy" is a generation-time semantic that data-gen owns.
- **Patch:** Author `docs/internal/healthy-baselines.md` in the data-gen repo, covering every metric in the new schema with a healthy range + a brief justification. Used by the Pass 1 generator (to know what numbers to emit for "healthy" tiers and what numbers count as "deviated" for negative scenarios) and by the generation-QA step (to confirm a "healthy" scenario stays inside the band).
- **Consumer impact:** None. The agent's Data Service has to pick its own breach thresholds for its `breaches` operation, but that's the consumer's implementation choice. Data-gen can optionally share the baselines as a coordination note (see §6) so the agent project's thresholds match — but this is informal, not contract-level.

### Gap B — 18 scenario specs in the new field set

- **Classification:** Internal data-gen artifact. These are *inputs* to the generator, not outputs the consumer sees.
- **Patch:** Author `docs/internal/scenarios/NN.spec.yaml` for each scenario `01`–`18` in the data-gen repo. Each YAML carries: business context, current configuration (in `TierTopology` shape), Pass 1 metric ranges in the new field names, time pattern, Pass 2 correlation rules, target recommendation, before/after evidence — all the things the v3 §6 narratives contain, re-mapped to the new schema. The metadata generator reads `NN.spec.yaml` and produces the consumer-facing `metadata.json`.
- **Consumer impact:** None. The consumer only ever sees `scenarios/NN/metadata.json` (the Pydantic-validated output), not the YAML spec that produced it.

### Gap C — `TopQuery.count` time unit

- **Classification:** Convention. The contract's field is `count: int`; the producer decides what unit it carries.
- **Patch:** Data-gen establishes the convention internally — recommend "total executions observed over the 14-day data window," which is the most natural reading of "top queries observed in this scenario" — and applies it consistently across all 18 scenarios. Document in `docs/internal/generation-conventions.md`.
- **Consumer impact:** The agent's Data Layer Analyst will reason over the field. To prevent misreading, data-gen should send a short coordination note to the agent project recommending they either (a) add a docstring to the `TopQuery.count` Pydantic field clarifying the unit (this is a doc-only change in the agent repo, not a contract-shape change, so no semver bump), or (b) document the convention in `04-data-service.md`. Either way, the consumer's API surface is unchanged.

### Gap D — `TopCacheKey.hit_count` / `miss_count` time unit

- **Classification:** Same as Gap C.
- **Patch:** Same convention ("total over the 14-day window"), documented in `generation-conventions.md`, same coordination note to the agent project.
- **Consumer impact:** Same as C.

### Gap E — Pass 1 / Pass 2 generation methodology

- **Classification:** Internal data-gen artifact. The contract is silent on how data is generated, and rightly so (§12.10: "Not a transport protocol… how data moves is the consumer's concern" — by symmetry, how data is *produced* is the producer's concern).
- **Patch:** Author `docs/internal/generation-methodology.md` carrying v3 §3 (two-pass rationale) updated for the new four-separate-telemetry-files layout, plus `prompts/pass1.txt` and `prompts/pass2.txt` as the actual prompt scaffolds. Decide and document the operational details (does Pass 1 emit one tier per LLM call or all four at once; does Pass 2 produce `correlation_evidence.json` alongside the telemetry rewrite or in a third post-pass).
- **Consumer impact:** None.

### Gap F — Per-scenario correlation specifications

- **Classification:** Folded into Gap B. The scenario spec YAMLs carry the Pass 2 correlation rules ("when cache_hit_ratio drops below 72%, db_query_p95_latency_ms rises 180–250ms within same 15-min window" → a small structured block in `01.spec.yaml`).
- **Patch:** Same artifact as Gap B.
- **Consumer impact:** None. The consumer sees the *result* — correlated telemetry plus `correlation_evidence.json` — never the spec that drove the correlation.

### Gap G — Generation-side semantic QA

- **Classification:** Internal data-gen artifact. The contract's §12.6 specifies what the consumer's Input Harness will check on load. Generation-side QA — pattern frequency, weekend behavior, Pass 2 invariance, correlation timing, no-spurious-correlation between uncorrelated tiers — is what *the producer* runs before shipping to make sure scenarios are distinguishable from each other.
- **Patch:** Author `docs/internal/generation-qa.md` carrying v3 §8.1 checks updated for the new fields. Implement as a `qa_validator.py` in the data-gen repo, run after Pass 2 emits each scenario folder, fail the pipeline if any check fails.
- **Consumer impact:** None. The consumer trusts the contract validation; the semantic QA is data-gen's own quality gate.

### Gap H — Pydantic implementation conflict (handoff README vs. agent BUILD_PLAN)

- **Classification:** Workflow alignment between the two projects. No contract impact either way.
- **Patch:** Pick one workflow and update the handoff README to match. The build plan's framing is safer — "agent project writes canonical Pydantic in Phase 1, then ships to data-gen via the handoff package" — because it eliminates the risk of two independent implementations drifting on subtle `Field(...)` constraints. Recommend updating the data-gen handoff README workflow step 2 to read "Receive `src/contracts/*.py` from the agent project once it is implemented; do not author independently."
- **Consumer impact:** None.

### Gap I — `generated_at` vs. data-window-start ambiguity

- **Classification:** Convention. The contract has both `metadata.json.generated_at: datetime` and the validation rule "first telemetry timestamp must be Monday 00:00 UTC of the start week (2026-05-01 for v3)." Two separate timestamps; the wording in §12.6 ("check `metadata.json.generated_at` for actual") invited confusion, but the producer can simply pick the convention.
- **Patch:** Data-gen pins the data-window start as a constant in `docs/internal/generation-conventions.md`: `DATA_WINDOW_START_UTC = "2026-05-01T00:00:00Z"` (Monday). Pass 1 always emits 1344 records starting at that timestamp. `metadata.json.generated_at` records the actual pipeline-run time. The two fields stay distinct; the contract is satisfied; the consumer's behavior is unchanged.
- **Consumer impact:** None.

### Gap J — Duplicated SLA representation in `BusinessContext`

- **Classification:** Generation rule. The contract carries both `sla_target_description: str` and structured `sla_target_p95_ms: int` / `sla_target_availability_pct: float`. The producer is responsible for emitting consistent values; the consumer reads whichever it prefers.
- **Patch:** Generation rule in `generation-conventions.md`: always derive `sla_target_description` from the structured fields using a fixed format (e.g., `f"{availability_pct}% availability, P95 < {p95_ms}ms"`). Unit test in the QA validator confirms the derivation across all 18 scenarios.
- **Consumer impact:** None.

---

## 6. Coordination notes back to the agent project

The only items where the consumer needs to be aware of a producer-side convention are the two field-semantics conventions (Gaps C and D). These do *not* require a contract change — only a clarification on the consumer's side that matches the producer's chosen interpretation. A short note from data-gen to the agent team, suggesting they either add docstrings to those Pydantic fields or document the conventions in `04-data-service.md`, closes the loop. Everything else stays inside the data-gen repo.

---

## 7. Recommended structure under the data-gen repo

```
cloud-governance-data-gen/
├── docs/
│   ├── contract-spec.md              # synced from agent project (read-only)
│   └── internal/                     # NEW — everything below is data-gen-owned
│       ├── healthy-baselines.md      # Gap A
│       ├── generation-methodology.md # Gap E
│       ├── generation-conventions.md # Gaps C, D, I, J
│       ├── generation-qa.md          # Gap G
│       └── scenarios/
│           ├── 01.spec.yaml          # Gap B (+ F)
│           ├── 02.spec.yaml
│           ├── …
│           └── 18.spec.yaml
├── src/
│   ├── contracts/                    # synced from agent project (Phase 1 deliverable)
│   ├── generator/                    # pass1.py, pass2.py, terraform.py, metadata.py
│   └── qa/                           # qa_validator.py
├── prompts/
│   ├── pass1.txt
│   └── pass2.txt
└── scenarios/                        # output — what the consumer reads
    ├── 01/
    │   ├── metadata.json
    │   ├── compute_telemetry.json
    │   ├── …
    │   └── main.tf
    └── …
```

Nothing in `docs/internal/`, `src/generator/`, `src/qa/`, or `prompts/` ever leaves the data-gen repo. The consumer only ever reads from `scenarios/NN/`. Contract version stays at `1.0.0`.

---

## 8. Net assessment

With this framing, the data-gen project can move forward independently. The work to produce `docs/internal/*` and the scenario YAMLs is roughly a day of careful translation (mechanical re-mapping of v3 §6 narratives to the new field set), and it unblocks Phase 1 code generation entirely. No contract change. No coordination dependency on the agent project beyond receiving the Pydantic package from Phase 1.

If you'd like, I can draft the actual `healthy-baselines.md` and one or two sample `scenarios/NN.spec.yaml` files in the repo so you have worked examples to validate the approach against before scaling to all 18.

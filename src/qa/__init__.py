"""Generation-side QA — structural, semantic, and smoke-test layers.

Two modules:
    qa_validator.py — runs contract validation + the 10 semantic checks
                      from docs/internal/generation-qa.md. Gates whether a
                      scenario folder is committed to `scenarios/NN/`.

    smoke_test.py   — runs the lightweight single-LLM-call solvability check
                      from docs/internal/scenario-quality-smoke-test.md.
                      Pre-handoff sanity check; doesn't gate scenarios.
"""

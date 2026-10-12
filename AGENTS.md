# Codex instructions

Read docs/V1_SPEC.md and docs/V2_SPEC.md before implementation. V1 remains the authoritative execution/account/data contract; V2_SPEC.md authorizes comparison/period/cost-analysis, section 8 preparation/HTML, and section 9 independent acquisition, full-range quality selection, fixed historical study and report diagnostics. Preserve the accepted Funding contract and V1 regressions.

- Baseline 324acadd has 316 accepted tests. Implement docs/V2_SPEC.md section 9 in four locally committed stages. Preserve legacy canonical identity/selection (including four-window early stop), Funding/native timing and fixed scope/tolerance, independent annualized-null audit, account contracts and compare/study atomic determinism/default 52/211 file counts. New official quality scanning covers every month of [2024-03-01,2026-08-01) including missing tails before any strategy run. No optimization, new strategies or unrelated stages; no automatic push.
- Keep this a small offline Python CLI. Do not add ML, optimization, web services, databases, live exchange access, or unrelated abstractions.
- Inspect the existing QuantForge market-data schemas before adapting them. Reuse only verified data or small isolated conversion logic; do not copy the old research architecture or treat its synthetic simulator as a historical execution engine.
- Data, signal timing, order sequencing, fills, costs, account equity, and metric definitions must match the spec. Add deterministic tests for each.
- Synthetic fixtures are for correctness tests only. Never present their output as historical strategy performance.
- Preserve data provenance and disclose that periods already examined in QuantForge are not independent out-of-sample evidence.

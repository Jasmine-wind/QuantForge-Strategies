# Codex instructions

Read docs/V1_SPEC.md and docs/V2_SPEC.md before implementation. V1 remains the authoritative execution/account/data contract; V2_SPEC.md authorizes the comparison/period/cost-analysis and section 8 independent official-archive preparation/offline HTML extensions. Preserve the accepted Funding contract and V1 regressions.

- V1 and V2 stages 1/2 are complete. Implement only docs/V2_SPEC.md section 8: independent official raw-archive preparation and standalone offline HTML browsing. Preserve all 245 tests, fixed six-month selection/completeness, Funding/native timing, independent annualized-null audit and compare/study atomic determinism/default file counts. No search, optimization or unrelated stages.
- Keep this a small offline Python CLI. Do not add ML, optimization, web services, databases, live exchange access, or unrelated abstractions.
- Inspect the existing QuantForge market-data schemas before adapting them. Reuse only verified data or small isolated conversion logic; do not copy the old research architecture or treat its synthetic simulator as a historical execution engine.
- Data, signal timing, order sequencing, fills, costs, account equity, and metric definitions must match the spec. Add deterministic tests for each.
- Synthetic fixtures are for correctness tests only. Never present their output as historical strategy performance.
- Preserve data provenance and disclose that periods already examined in QuantForge are not independent out-of-sample evidence.

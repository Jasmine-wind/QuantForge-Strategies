# Codex instructions

Read docs/V1_SPEC.md and docs/V2_SPEC.md before implementation. V1 remains the authoritative execution/account/data contract; V2_SPEC.md authorizes only the current comparison/period/cost-analysis extension. Preserve the accepted Funding contract and V1 regressions.

- V1 and V2 stage 1 are complete. Implement only V2 stage 2 in docs/V2_SPEC.md: fixed earliest non-overlapping six-month windows (maximum four), shared assumptions, independent window accounts and atomic study output. Preserve stage-1 compare/12-month selection and the independent annualized-null audit regression. Do not add search, optimization or unrelated stages.
- Keep this a small offline Python CLI. Do not add ML, optimization, web services, databases, live exchange access, or unrelated abstractions.
- Inspect the existing QuantForge market-data schemas before adapting them. Reuse only verified data or small isolated conversion logic; do not copy the old research architecture or treat its synthetic simulator as a historical execution engine.
- Data, signal timing, order sequencing, fills, costs, account equity, and metric definitions must match the spec. Add deterministic tests for each.
- Synthetic fixtures are for correctness tests only. Never present their output as historical strategy performance.
- Preserve data provenance and disclose that periods already examined in QuantForge are not independent out-of-sample evidence.

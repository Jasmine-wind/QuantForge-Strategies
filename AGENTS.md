# Codex instructions

Read docs/V1_SPEC.md before implementation. It is the authoritative V1 product and backtest contract.

- Implement the milestones in the order given in the spec: first an end-to-end EMA backtest, then Bollinger Bands.
- Keep this a small offline Python CLI. Do not add ML, optimization, web services, databases, live exchange access, or unrelated abstractions.
- Inspect the existing QuantForge market-data schemas before adapting them. Reuse only verified data or small isolated conversion logic; do not copy the old research architecture or treat its synthetic simulator as a historical execution engine.
- Data, signal timing, order sequencing, fills, costs, account equity, and metric definitions must match the spec. Add deterministic tests for each.
- Synthetic fixtures are for correctness tests only. Never present their output as historical strategy performance.
- Preserve data provenance and disclose that periods already examined in QuantForge are not independent out-of-sample evidence.

# Aftermath runtime overlay gates

Current status: **read-only shadow pilot**.

Catalog status: **0 enabled strategies**. The Rooster shadow canary is an
offline fixture-backed test harness, not a deployable package. Its source lives
outside the pinned upstream strategy tree, and upstream Rooster remains
`needs-field-mapping` until wallet-to-account resolution and the supervisor
contract are complete.

Implemented:

- Typed reads for markets, prices, candles, funding, account capabilities,
  account/position summaries, and pending CCXT orders.
- Deterministic market-ID resolution and capability checks.
- Human-read versus native/B9 unit separation.
- Allowlisted transport injection and no-network fixtures.
- Snapshot-before-delta stream reconciliation state.
- Rooster scanner data mapping and shadow signal emission.
- Exact preservation of the pinned upstream strategy tree; downstream canary
  code is isolated under `aftermath-overlay/shadow/harness/`, outside every
  upstream strategy-discovery glob.

Price/size denominations are pinned per endpoint field in
`aftermath_runtime.models.FIELD_DENOMINATIONS`; value magnitude is never used to
guess units. Funding rates are preserved as raw API values with each market's
`fundingFrequencyMs`. They are not annualized or treated as cross-market
comparable by this overlay.

`get_candles` assumes the preview's observed bucket-start timestamp semantics
and clamps requested ranges to its injected current clock before excluding an
open bucket. Because the pinned schema does not explicitly say bucket start
versus close, that ambiguity is a machine-readable blocking drift entry.

Not implemented:

- Transaction preview/build, PTB composition, or semantic PTB inspection.
- Agent/admin wallet signing, `signingDigest`, sponsor signatures, or Sui
  submission.
- Collateral allocation/deallocation, leverage changes, order placement,
  cancellation, TWAP, native SL/TP, or stop editing.
- Execution reconciliation, durable runtime supervisor, DSL exits, local
  ratchet state, heartbeat cancellation, or dead-man switch.
- WebSocket/SSE network clients. Only the fail-closed resync state model exists.
- Authenticated writes of any kind.

Release remains blocked until the OpenAPI/live `/markets` response mismatch is
resolved and multi-market (including sub-dollar), stream reconnect, sponsored
signature, PTB validation, and explicitly authorized non-production write
tests pass. Unsupported or unavailable markets must stay blocked; a strategy
must never silently substitute a ticker.

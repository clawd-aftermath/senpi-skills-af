# Aftermath runtime overlay gates

Current status: **read-only shadow pilot**.

Contract source: V2-preview OpenAPI plus pinned
`AftermathFinance/skills@5b614db62dcd2e58f442e93661f608fe7b073c32`
(`aftermath-perpetuals` v3.0.0). The branch name alone is not trusted; offline
validation checks internal pin/manifest consistency. A separate no-fetch source
check recomputes the six digests from the pinned git object and verifies branch
ancestry.

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
- V3 candle-history resolutions and the general-updates `marketCandles`
  subscription shape.
- Exact native BigInt handling for fields documented as trailing-`n` strings;
  numeric native account IDs remain distinct from CCXT capability object IDs.
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

The pinned skill additionally requires any future execution runtime to sign
`signingDigest` rather than `transactionBytes`, reconcile ambiguous submits
before retry, serialize coin/gas-object-sensitive operations, explicitly
allocate isolated collateral, parse HTTP-200 preview error unions, use
`integratorId`/`integratorFee` and the v3 SL/TP fields, and implement heartbeat
cancellation because the API has no built-in dead-man switch. None of those
requirements is represented as implemented here.

Release remains blocked until the OpenAPI/live `/markets` response mismatch and
the native BigInt request/response integer-versus-trailing-`n` mismatches are
resolved, and multi-market (including sub-dollar), stream reconnect, sponsored
signature, PTB validation, and explicitly authorized non-production write tests
pass. Unsupported or unavailable markets must stay blocked; a strategy must
never silently substitute a ticker.

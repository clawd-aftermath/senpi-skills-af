# Aftermath strategy coverage

This downstream starts fail-closed. A source package is runnable only when its
generated classification is `supported`. The current coverage generator enables
none: the fixture-backed reader and shadow scanner do not supply a durable
supervisor, account resolver, or execution runtime.

The generated `catalog/blocked.json` is authoritative for current reasons.
The Rooster shadow canary does not override these classifications; it proves
only fixture-backed read normalization and signal parity:

- `needs-field-mapping`: the scanner thesis may be portable, but its consumed
  account/market fields still require an explicit Aftermath adapter.
- `needs-derived-data`: the package consumes Senpi leaderboard, discovery,
  audit, or cross-asset-flow data with no Aftermath source.
- `blocked-market`: the declared or ranked universe is not available. At the
  pinned preview snapshot, only BTC was active. Universe-ranking strategies
  never reduce themselves silently to one market.
- `blocked-runtime-semantics`: sizing, multi-leg lifecycle, or other supervisor
  behavior cannot safely retain its Hyperliquid meaning on Aftermath.

`albatross` and `crane` retain their upstream blocks. `caribou`, `dire`,
`hydra`, and `spider` are quarantined instead of rewriting their source:
fraction-valued margin settings conflict with percent-valued Runtime 3 signals.
Changing those values in the upstream tree would alter strategy semantics, so a
future port must make the sizing basis explicit in `aftermath/v1`.

Regenerate and verify:

```bash
python3 tools/generate_coverage.py
python3 tools/generate_coverage.py --check
```

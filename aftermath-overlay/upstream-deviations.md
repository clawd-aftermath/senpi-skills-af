# Upstream deviations

Base: `Senpi-ai/senpi-skills@c3ef08a670581cd20a9d80df17d36f13266605ae`.

No file under `strategies/` is modified by this overlay. The repository's MIT
license and per-file Apache-2.0 notices remain unchanged.

## Intentional downstream behavior

1. All 99 source packages are inventoried, including all 125 runtime instances.
2. Catalogs are generated from source manifests plus explicit coverage rules;
   generated catalogs are never hand-edited.
3. The source invariant is strict:
   `source packages == enabled packages + blocked packages`.
4. Only an exact active-market mapping can unblock a package. A dynamic or
   multi-asset universe is blocked when the venue has one active market.
5. Hyperliquid/Senpi runtime calls are forbidden in any runnable Aftermath
   package. The source corpus may retain them for provenance.
6. The four upstream margin defects are quarantined, not silently corrected:
   `caribou`, `dire`, `hydra`, and `spider`.
7. The five BTC market-technical candidates have explicit field matrices. A
   field without a semantically exact V2 mapping is a gap, not a guessed alias.

## Contract drift note

The pinned OpenAPI SHA is recorded in `provenance.json`. The contract fixture is
a manual transcription tied to that observed SHA; because the full spec body is
not vendored, it cannot machine-detect later upstream drift. Likewise, the BTC
market list is an observation-dated offline snapshot, not a claim about the
current live venue.

The overlay's
route-neutral cancel-and-place input deliberately keeps account identity in a
separate typed account reference. It rejects stray `accountId` and
`accountCapId` keys in the generic order body, preventing the ambiguous payload
shape found in the legacy PR. The HTTP adapter is responsible for placing the
validated reference into the schema shape required by its pinned OpenAPI.

No script in this overlay performs a network request, authenticates, signs, or
submits a transaction.

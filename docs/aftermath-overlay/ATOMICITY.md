# Atomicity: what is one transaction, and what is not

One-operation-per-transaction is the shallow-port failure mode. Every route
below was verified present in the live V2 OpenAPI document
(251 paths / 342 schemas, fetched 2026-07-28).

Where the API offers a multi-operation primitive, the runtime uses it. Where a
step must observe a fill before the next step can be decided, it stays
sequential — forcing atomicity there would change the semantics, not improve
them.

## Now ONE transaction

| operation | route | why it matters |
|---|---|---|
| requote / reprice / modify a quote | `account/transactions/cancel-and-place-orders` | A split cancel-then-place leaves the strategy **unquoted** (adverse selection on the other side) or **double-quoted** (twice the intended size) in between, and can partially fail. Every requote path in the runtime uses this route; `place-limit-order` is reserved for opening a quote that does not exist yet. |
| a whole ladder | `account/transactions/place-scale-order` | N rungs in one transaction instead of N transactions. A partially-placed ladder is a skewed book the strategy did not intend. |
| stop-loss + take-profit together | `account/transactions/place-sl-tp-orders` | Both legs land or neither does. A position protected on one side only is worse than an unprotected one, because it looks protected. |
| several stop orders | `account/transactions/place-stop-orders` | Takes `stopOrders[]`. |
| cancel across several markets | `account/transactions/cancel-orders` | `marketIdsToData` is a map, so a cancel-all is one transaction. This is what the kill switch and SIGINT/SIGTERM handlers use. |
| edit / cancel stops | `account/transactions/edit-stop-orders`, `cancel-stop-orders` | Batched. |
| TWAP create / edit / cancel | `account/transactions/create-twap-orders`, `edit-twap-orders`, `cancel-twap-orders` | New in v3.0.0. |
| onboarding | `transactions/create-account` (`txKind` + `deferShare`) then `deposit-collateral` and `allocate-collateral` extending the same `txKind` | See below. |

### `shouldAbortOnMissingId` is set deliberately, per path

- **requote → `true`.** If an order we meant to cancel has already filled, the
  whole transaction aborts. Placing a fresh quote on top of a fill the strategy
  has not observed is how a position doubles silently.
- **cancel-all → `false`.** A kill switch must succeed even when some orders
  have already filled or expired. Aborting there would leave live exposure.

### The composed onboarding PTB

`create-account` accepts `txKind` (a base64 Sui `TransactionKind` to extend) and
`deferShare`. With `deferShare = true` the response carries **deferred PTB
argument references** — `{accountArg, adminCapArg, sharePolicyArg,
collateralCoinType}` — not just `{txKind}` (skills `gotchas.md` §12). The
inspection gate asserts they are present rather than assuming the simple shape.

The chain is: create-account → deposit-collateral (`txKind` = the previous
result) → allocate-collateral (`txKind` = the previous result). It succeeds or
fails as a unit, instead of stranding an operator with an account and no
collateral, or collateral allocated to nothing.

**Honest limitation.** Threading the deferred `accountArg` into the deposit step
requires composing the PTB with a Sui SDK: the deposit builder identifies the
account by `accountId`, which does not exist until the create-account command
executes on chain. `ExecutionClient.build_onboarding_ptb` builds and inspects
the create-account kind and returns the deferred references attached; the Sui
PTB composition itself is the caller's, and is **not implemented in this
repository** — implementing it would require a signing path, which this work
explicitly excludes.

## Still SEVERAL transactions, and why

| operation | steps | reason |
|---|---|---|
| `strategy_close` (full teardown) | cancel-orders → reduce-only market order → withdraw-collateral | The withdrawable amount is not known until the closing fill is realised. A single call would have to guess it. The runtime refuses the one-shot call rather than guessing. |
| deposit → allocate, post-onboarding | 2 | Allocation size normally depends on state observed after the deposit settles. Both are available as `txKind`-composable steps if a caller genuinely knows both amounts up front. |
| leverage change → resize | 2 | `set-leverage` changes the position's margin requirement; the resulting free collateral must be re-read before sizing the next order. |
| deposits under concurrency | serialised, 1 at a time | Not an atomicity question but an object-version one: parallel deposits race on Sui coin objects and fail with version/equivocation errors. `SerialGate` refuses re-entrancy rather than queueing, so a concurrency bug in a strategy surfaces instead of hiding. |
| withdraw across accounts | 1 per account | `transfer-collateral` moves between two accounts atomically; withdrawing from several to a wallet does not batch. |

## What is never one transaction here

**Submission.** No submit route (`/api/ccxt/submit/*` or otherwise) appears in
any transport allowlist in this repository, and `ptb.submit()` raises. The
pipeline stops at an inspected transaction:

```
build  →  preview gate  →  INSPECT  →  (would sign)  →  reconcile
```

`sign_inspected()` accepts only an `InspectedTx`, and the only way to obtain one
is `inspect()`. The gate token is cleared after validation so it cannot be
harvested off an instance and reused. There is no path from a raw builder
response to a signature that skips inspection.

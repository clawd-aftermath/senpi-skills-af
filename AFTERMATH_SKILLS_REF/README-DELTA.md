# Delta: the vendored skills name a retired host

**Read this before copying any URL out of this directory.**

## The discrepancy

The vendored skills document V2-only features — TWAP orders, scale orders,
`cancel-and-place`, `clientOrderId`, `triggerPriceType`, `integratorId`,
`priorityTakerFee`, the `marketCandles` subscription — and are correct about all
of them.

They are wrong about exactly one thing: **the host**.

At the pinned commit `5b614db` the skills reference the retired v1 API host in
**22 places** under `skills/`, and **zero** places reference the live host.

| file | lines |
|---|---|
| `skills/api/SKILL.md` | 22, 24 |
| `skills/api/gotchas.md` | 3, 92 |
| `skills/api/native.md` | 7, 381, 382 |
| `skills/api/ccxt.md` | 7, 60, 64, 175, 176 |
| `skills/api/monitoring-patterns.md` | 12, 143, 153 |
| `skills/api/auxiliary-endpoints.md` | 348, 349 |
| `skills/api/safety-and-risk.md` | 128, 379 |
| `skills/api/sdk-reference.md` | 255 |
| `skills/api/scripts/check_api_changes.py` | 16 |
| `skills/api/.api-spec-state.json` | 2 |

(The vendored `README.md` adds two more, outside `skills/`.)

Two of those are especially easy to copy by accident:

* `monitoring-patterns.md:12` — `const BASE_URL = "https://aftermath.finance";`
  reads like the one line you are meant to lift into a client.
* `safety-and-risk.md:128` — the `max-order-size` `fetch()` example, in the file
  whose *patterns* this runtime deliberately conforms to.

The WebSocket examples (`ccxt.md:60,64`, `monitoring-patterns.md:143,153`) carry
the same host with a `wss://` scheme.

## The same trap is in the OpenAPI document

This is not only a skills problem. The live spec's own `servers` block still
lists the retired host first, described as the "Production server", with a
`testnet.` sibling. Any standard generator — `openapi-typescript`,
`openapi-generator`, `swagger-codegen` — bakes the first server entry in as the
default base URL, and the generated client then talks to a dead API while
looking entirely correct.

**If you generate code from the spec, strip or override `servers` first.**

## What is actually true

* The live API is **`https://v2-preview.aftermath.finance`**.
* Despite the hostname, that is **production mainnet**, not a preview or a
  testbed. It is the relaunch API.
* The legacy host **no longer serves the API at all** (confirmed 2026-07-28).
* The live spec is 251 paths / 342 schemas. The retired v1 spec was 159 / 268.

## How this repository handles it

1. The vendored files are **not edited**. Patching them would silently diverge
   from upstream and make the next sync a merge conflict instead of a diff.
2. The host is defined **exactly once**, in `aftermath_runtime/config.py` as
   `DEFAULT_API_BASE_URL`, overridable through `AF_API_BASE_URL`. Every call
   site reads it from there.
3. `aftermath_runtime.config.assert_not_retired_host()` fails closed if the
   configured host resolves to the retired domain, and every transport calls it
   at construction.
4. `tests/test_host_discipline.py` **fails** if any non-vendored file in the
   tree references the bare host without the `v2-preview.` prefix. This
   directory is the only exemption, and the test asserts that the exemption is
   still needed — if upstream fixes the URLs, the test tells you the carve-out
   can go.

Take their patterns. Never their URLs.

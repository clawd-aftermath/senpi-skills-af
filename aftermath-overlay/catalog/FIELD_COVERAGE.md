# Generated field coverage

Exact mappings and explicit gaps for the initial BTC candidates.

## coyote

Sources: `strategies/coyote/main/scanners/scan.py`

| Consumed source field | Aftermath V2 mapping or gap | Status |
| --- | --- | --- |
| `ctx.wallet` | gap: resolve a Sui wallet to one explicit numeric accountId before scanning | `gap` |
| `ctx.state.last / ctx.state.append / len(ctx.state)` | runtime-local durable scanner state; no HTTP route | `runtime-local` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.accountValue` | POST /api/perpetuals/accounts/positions -> accounts[].totalEquityUsd | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalMarginUsed` | gap: no exact aggregate; positions[].collateralUsd is isolated per-position collateral | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalNtlPos` | gap: an explicit net/absolute aggregation policy is required for positions[].quoteAssetNotionalAmount | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.szi` | POST /api/perpetuals/accounts/positions -> accounts[].positions[].baseAssetAmount | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.coin` | accounts[].positions[].marketId joined to POST /api/perpetuals/markets -> markets[].metadata.symbol or markets[].marketParams.baseAssetSymbol | `mapped-transform` |
| `market_get_asset_data.data.candles.4h[].c` | POST /api/perpetuals/market/candle-history -> candles[].close using resolution=4h and explicit fromTimestamp/toTimestamp | `mapped-transform` |
| `market_get_asset_data.success` | POST /api/perpetuals/market/candle-history HTTP status/error union is converted to a fail-closed adapter result; the V2 response has no success envelope | `mapped-transform` |
| `inputs.dispersionUniverse ranked across BTC/ETH/SOL/HYPE` | gap: only BTC was active in the retired preview fixture snapshot; dispersion must fail closed and may not collapse to one market | `gap` |

## gecko

Sources: `strategies/gecko/main/scanners/scan.py`

| Consumed source field | Aftermath V2 mapping or gap | Status |
| --- | --- | --- |
| `ctx.wallet` | gap: resolve a Sui wallet to one explicit numeric accountId before scanning | `gap` |
| `ctx.state.last / ctx.state.append` | runtime-local durable scanner state; no HTTP route | `runtime-local` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.{assetPositions,asset_positions}[].position.szi` | POST /api/perpetuals/accounts/positions -> accounts[].positions[].baseAssetAmount | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.{assetPositions,asset_positions}[].position.coin` | accounts[].positions[].marketId joined to POST /api/perpetuals/markets -> markets[].metadata.symbol or markets[].marketParams.baseAssetSymbol | `mapped-transform` |
| `market_get_asset_data.data.candles.{15m,1h,4h}[].{o,h,l,c,v}` | POST /api/perpetuals/market/candle-history -> candles[].{open,high,low,close,volume}; adapter converts to o/h/l/c/v strings for each resolution | `mapped-transform` |
| `market_get_asset_data.data.{funding,funding_rate,fundingRate,current_funding}` | gap: POST /api/perpetuals/market/funding-history exposes history[].longFundingRate and history[].shortFundingRate; one directionless scalar is not semantically exact | `gap` |
| `market_get_asset_data.data.funding.{rate,current}` | gap: choose long/short rate and settlement-interval normalization explicitly from funding-history before mapping | `gap` |
| `market_get_asset_data.data.{asset_context,context}.{max_leverage,maxLeverage}` | gap: the pinned V2 response has no field with identical venue-max-leverage semantics | `gap` |

## koala

Sources: `strategies/koala/main/scanners/scan.py`

| Consumed source field | Aftermath V2 mapping or gap | Status |
| --- | --- | --- |
| `ctx.wallet` | gap: resolve a Sui wallet to one explicit numeric accountId before scanning | `gap` |
| `ctx.state.last / ctx.state.append / len(ctx.state)` | runtime-local durable scanner state; no HTTP route | `runtime-local` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.accountValue` | POST /api/perpetuals/accounts/positions -> accounts[].totalEquityUsd | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalMarginUsed` | gap: no exact aggregate; positions[].collateralUsd is isolated per-position collateral | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalNtlPos` | gap: an explicit net/absolute aggregation policy is required for positions[].quoteAssetNotionalAmount | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.szi` | POST /api/perpetuals/accounts/positions -> accounts[].positions[].baseAssetAmount | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.coin` | accounts[].positions[].marketId joined to POST /api/perpetuals/markets -> markets[].metadata.symbol or markets[].marketParams.baseAssetSymbol | `mapped-transform` |
| `inputs.asset` | POST /api/perpetuals/markets -> exact metadata.symbol / marketParams.baseAssetSymbol resolution; ambiguity is an error | `mapped-transform` |

## rooster

Sources: `strategies/rooster/main/scanners/scan.py`

| Consumed source field | Aftermath V2 mapping or gap | Status |
| --- | --- | --- |
| `ctx.wallet` | gap: resolve a Sui wallet to one explicit numeric accountId before scanning | `gap` |
| `ctx.state.last / ctx.state.append / len(ctx.state)` | runtime-local durable scanner state; no HTTP route | `runtime-local` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.accountValue` | POST /api/perpetuals/accounts/positions -> accounts[].totalEquityUsd | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalMarginUsed` | gap: no exact aggregate; positions[].collateralUsd is isolated per-position collateral and must not be relabeled | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalNtlPos` | gap: derive only after an explicit absolute-vs-net notional policy from positions[].quoteAssetNotionalAmount | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.szi` | POST /api/perpetuals/accounts/positions -> accounts[].positions[].baseAssetAmount | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.coin` | accounts[].positions[].marketId joined to POST /api/perpetuals/markets -> markets[].metadata.symbol or markets[].marketParams.baseAssetSymbol | `mapped-transform` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.marginUsed` | POST /api/perpetuals/accounts/positions -> accounts[].positions[].collateralUsd | `mapped-transform` |
| `market_get_asset_data.data.candles.{15m,4h}[].{o,h,l,c,v}` | POST /api/perpetuals/market/candle-history -> candles[].{open,high,low,close,volume}; adapter converts to o/h/l/c/v strings per requested resolution | `mapped-transform` |
| `market_get_asset_data.success` | POST /api/perpetuals/market/candle-history HTTP status/error union is converted to a fail-closed adapter result; the V2 response has no success envelope | `mapped-transform` |

## terrapin

Sources: `strategies/terrapin/u1/scanners/scan.py`, `strategies/terrapin/u2/scanners/scan.py`, `strategies/terrapin/u3/scanners/scan.py`, `strategies/terrapin/u4/scanners/scan.py`

| Consumed source field | Aftermath V2 mapping or gap | Status |
| --- | --- | --- |
| `ctx.wallet` | gap: each unit wallet must resolve to one explicit numeric Aftermath accountId; four wallets may not share hidden cross-margin assumptions | `gap` |
| `ctx.state.append` | runtime-local durable scanner state; no HTTP route | `runtime-local` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.accountValue` | POST /api/perpetuals/accounts/positions -> accounts[].totalEquityUsd | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalMarginUsed` | gap: no exact aggregate; positions[].collateralUsd is isolated per-position collateral | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.marginSummary.totalNtlPos` | gap: an explicit net/absolute aggregation policy is required for positions[].quoteAssetNotionalAmount | `gap` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.szi` | POST /api/perpetuals/accounts/positions -> accounts[].positions[].baseAssetAmount | `mapped` |
| `strategy_get_clearinghouse_state.data.{main,xyz}.assetPositions[].position.coin` | accounts[].positions[].marketId joined to POST /api/perpetuals/markets -> markets[].metadata.symbol or markets[].marketParams.baseAssetSymbol | `mapped-transform` |
| `market_get_asset_data.data.candles.<candleInterval>[].{o,h,l,c,v}` | POST /api/perpetuals/market/candle-history -> candles[].{open,high,low,close,volume}; adapter converts to o/h/l/c/v strings using explicit resolution/fromTimestamp/toTimestamp | `mapped-transform` |
| `market_get_asset_data.success` | POST /api/perpetuals/market/candle-history HTTP status/error union is converted to a fail-closed adapter result; the V2 response has no success envelope | `mapped-transform` |
| `inputs.unitIndex across u1/u2/u3/u4` | runtime-local instance identity; PTB atomic multi-unit lifecycle is a later runtime gate | `runtime-local` |

Generated from `field-mappings/*.json`; do not hand-edit.

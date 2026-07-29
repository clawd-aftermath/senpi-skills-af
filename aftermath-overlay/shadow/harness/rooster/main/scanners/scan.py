"""ROOSTER — Aftermath read-only pre-session-open scanner.

Copyright 2026 Senpi (https://senpi.ai) — Apache-2.0.
Aftermath shadow-port modifications copyright 2026 Aftermath Finance.

This preserves upstream's clock gate, scoring, signal schema, and session
dedup.  Venue reads use ``ctx.venue`` and a numeric ``ctx.account_id``.  The
scanner has no order, PTB, signing, or submission capability.
"""

from __future__ import annotations

import sys
import time

import scoring

_DEFAULT_ASSETS = ["BTC"]
_DEFAULT_OPENS = ["13:30", "08:00"]


def _get_account(ctx):
    """Return ``(equity_usd, held_symbols)`` from fresh Aftermath account state."""
    try:
        account = ctx.venue.get_account(ctx.account_id)
    except Exception as exc:  # noqa: BLE001 - read failure skips the tick
        print(f"[rooster.scan] Aftermath account read failed: {exc!r}", file=sys.stderr)
        return 0.0, set(), "account_read_failed"
    held = set()
    try:
        for position in account.positions:
            if scoring._f(position.base_amount) == 0:
                continue
            held.add(ctx.venue.require_market(position.market_id).symbol.upper())
    except Exception as exc:  # noqa: BLE001 - unresolved position market is unsafe
        print(
            f"[rooster.scan] position market normalization failed: {exc!r}",
            file=sys.stderr,
        )
        return 0.0, set(), "position_market_unavailable"
    # marginPct is declared against available collateral, matching upstream's
    # withdrawable-percent sizing rather than total equity.
    return scoring._f(account.available_collateral_usd), held, None


def _candles(ctx, asset, now_ms, inputs):
    """Return upstream's canonical short-key 15m/4h candle maps."""
    window = int(inputs.get("windowBars", 3))
    baseline = int(inputs.get("baselineBars", 16))
    prior = int(inputs.get("priorRangeBars", 24))
    bars_15m = max(window + baseline, window + prior) + 2
    try:
        ctx.venue.require_market(asset, ("candles", "account", "positions"))
        candles_15m = ctx.venue.get_candles(
            asset,
            "15m",
            now_ms - bars_15m * 15 * 60 * 1000,
            now_ms,
        )
        candles_4h = ctx.venue.get_candles(
            asset,
            "4h",
            now_ms - 8 * 4 * 60 * 60 * 1000,
            now_ms,
        )
    except Exception as exc:  # noqa: BLE001 - read failure skips the asset
        print(f"[rooster.scan] Aftermath candle read failed for {asset}: {exc!r}", file=sys.stderr)
        return None
    return {
        "15m": [candle.as_scanner_dict() for candle in candles_15m],
        "4h": [candle.as_scanner_dict() for candle in candles_4h],
    }


def _load_fired(ctx):
    if ctx.state is None or len(ctx.state) == 0:
        return {}
    fired = (ctx.state.last() or {}).get("fired", {})
    return dict(fired) if isinstance(fired, dict) else {}


def scan(inputs, ctx):
    now = time.time()
    now_ms = int(now * 1000)
    assets = inputs.get("assets", _DEFAULT_ASSETS)
    opens = inputs.get("sessionOpensUtc", _DEFAULT_OPENS)
    pre_open_minutes = int(inputs.get("preOpenMinutes", 45))
    min_score = float(inputs.get("minScore", 5))
    base_margin_pct = float(inputs.get("marginPctBase", 12))
    max_slots = int(inputs.get("maxSlots", 1))
    lev_default = int(inputs.get("leverageDefault", 3))
    lev_min = int(inputs.get("leverageMin", 2))
    lev_max = int(inputs.get("leverageMax", 5))

    minute_of_day = int((now // 60) % 1440)
    phase, open_minute, mins_to_open = scoring.session_phase(
        minute_of_day, opens, pre_open_minutes
    )
    if phase != "pre_open":
        print(
            f"[rooster.scan] IDLE — {minute_of_day // 60:02d}:"
            f"{minute_of_day % 60:02d} UTC is outside every pre-open window",
            file=sys.stderr,
        )
        return []

    session_key = f"{int(now // 86400)}:{open_minute}"
    fired = {key: value for key, value in _load_fired(ctx).items() if now - value < 172800}
    available_collateral_usd, held, skip_reason = _get_account(ctx)
    if available_collateral_usd <= 0:
        print(
            "[rooster.scan] WAITING — no available collateral / unsafe read",
            file=sys.stderr,
        )
        if ctx.state is not None:
            try:
                ctx.state.append(
                    {
                        "fired": fired,
                        "result": {
                            "ts": now,
                            "session": session_key,
                            "emitted": 0,
                            "mode": "shadow",
                            "skipReason": skip_reason or "no_available_collateral",
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[rooster.scan] state append failed: {exc!r}", file=sys.stderr
                )
        return []
    open_slots = max_slots - len(held)
    if open_slots <= 0:
        print(f"[rooster.scan] slots full ({len(held)}/{max_slots})", file=sys.stderr)
        return []

    candidates = []
    scanned = 0
    for asset in assets:
        if not asset:
            continue
        symbol = asset.upper()
        if symbol in held or f"{session_key}:{symbol}" in fired:
            continue
        scanned += 1
        candles = _candles(ctx, asset, now_ms, inputs)
        if not candles:
            continue
        thesis = scoring.build_thesis(
            asset,
            candles["15m"],
            candles["4h"],
            mins_to_open,
            inputs,
        )
        if thesis and thesis["score"] >= min_score:
            candidates.append(thesis)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    leverage = max(lev_min, min(lev_default, lev_max))
    signals = []
    for thesis in candidates[:open_slots]:
        margin_pct = round(
            scoring.margin_tier_pct(thesis["score"], base_margin_pct), 4
        )
        fired[f"{session_key}:{thesis['coin'].upper()}"] = now
        signals.append(
            {
                "asset": thesis["coin"],
                "direction": thesis["direction"],
                "marginPct": margin_pct,
                "leverage": leverage,
                "data": {
                    key: value
                    for key, value in {
                        "score": thesis["score"],
                        "leverage": leverage,
                        "direction": thesis["direction"],
                        "reasons": thesis["reasons"][:8],
                        "driftPct": thesis["drift_pct"],
                        "volRatio": thesis["vol_ratio"],
                        "rangePos": thesis["range_pos"],
                        "trend4h": thesis["trend_4h"],
                        "minutesToOpen": thesis["minutes_to_open"],
                        "sessionOpenUtc": (
                            f"{open_minute // 60:02d}:{open_minute % 60:02d}"
                        ),
                        "heldAssets": sorted(held),
                    }.items()
                    if value is not None
                },
            }
        )

    print(
        f"[rooster.scan] {'SHADOW' if signals else 'WAITING'} — "
        f"{mins_to_open}m to open; scanned={scanned} emitted={len(signals)}",
        file=sys.stderr,
    )
    if ctx.state is not None:
        try:
            ctx.state.append(
                {
                    "fired": fired,
                    "result": {
                        "ts": now,
                        "session": session_key,
                        "scanned": scanned,
                        "emitted": len(signals),
                        "minutesToOpen": mins_to_open,
                        "mode": "shadow",
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[rooster.scan] state append failed: {exc!r}", file=sys.stderr)
    return signals

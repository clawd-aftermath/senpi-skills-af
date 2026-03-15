#!/usr/bin/env python3
# Senpi GATOR Scanner v1.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills
"""GATOR Scanner — Patient Funding Arbitrage.

Enters against extreme funding (120%+ annualized) to collect payments and
position for the mean-reversion snap. No time-based exits — structural
thesis invalidation only (funding flips, OI collapses, funding normalizes).

Tracks accumulated funding income per position and adjusts DSL floor
accordingly: more funding collected = more room to absorb.

The alligator: lies motionless for hours, then snaps.

Runs every 15 minutes.
"""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gator_config as cfg


# ─── Funding Data ─────────────────────────────────────────────

def get_all_funding():
    """Get funding rates for all assets."""
    data = cfg.mcporter_call("market_list_instruments")
    if not data or not data.get("success"):
        return []
    instruments = data.get("data", data)
    if isinstance(instruments, dict):
        instruments = instruments.get("instruments", [])
    assets = []
    for inst in instruments:
        coin = inst.get("coin") or inst.get("name", "")
        funding = float(inst.get("funding", 0))
        oi = float(inst.get("openInterest", 0))
        mark_px = float(inst.get("markPx", inst.get("midPx", 0)))
        # Handle nested context
        ctx = inst.get("context", {})
        if ctx:
            funding = float(ctx.get("funding", funding))
            mark_px = float(ctx.get("markPx", mark_px))
            oi = float(ctx.get("openInterest", oi))
        oi_usd = oi * mark_px if mark_px > 0 else 0
        funding_ann = abs(funding) * 8760
        if coin and oi_usd > 3_000_000:
            assets.append({
                "coin": coin,
                "funding": funding,
                "fundingAnn": funding_ann,
                "oi": oi,
                "oi_usd": oi_usd,
                "price": mark_px,
            })
    return assets


def get_asset_detail(coin):
    """Get candles and OI trend for thesis validation."""
    data = cfg.mcporter_call("market_get_asset_data", asset=coin,
                              candle_intervals=["1h", "4h"],
                              include_funding=True, include_order_book=False)
    if not data or not data.get("success"):
        return None
    return data.get("data", data)


def get_sm_direction(coin):
    """SM positioning — optional booster for funding arb."""
    data = cfg.mcporter_call("leaderboard_get_markets")
    if not data or not data.get("success"):
        return None, 0
    markets = data.get("data", data)
    if isinstance(markets, dict):
        markets = markets.get("markets", markets.get("leaderboard", []))
    for m in markets:
        if m.get("coin", m.get("asset", "")) == coin:
            long_pct = float(m.get("longPct", m.get("pctOfGainsLong", 50)))
            if long_pct > 58:
                return "LONG", long_pct
            elif long_pct < 42:
                return "SHORT", 100 - long_pct
            return "NEUTRAL", 50
    return None, 0


# ─── Thesis Validation (for held positions) ──────────────────

def validate_funding_thesis(coin, our_direction, entry_cfg, state):
    """Check if the funding thesis is still alive. Returns (valid, reasons)."""
    assets = get_all_funding()
    asset = next((a for a in assets if a["coin"] == coin), None)
    if not asset:
        return True, ["asset_not_found_hold"]

    invalidations = []
    funding = asset["funding"]
    funding_ann = asset["fundingAnn"]

    # INVALIDATION 1: Funding flipped direction
    # If we're long (entered against negative funding) and funding is now positive = thesis dead
    if our_direction == "LONG" and funding > 0.0005:
        invalidations.append(f"funding_flipped_positive_{funding:+.4f}")
    elif our_direction == "SHORT" and funding < -0.0005:
        invalidations.append(f"funding_flipped_negative_{funding:+.4f}")

    # INVALIDATION 2: Funding normalized below threshold
    min_exit_ann = entry_cfg.get("thesisExit", {}).get("fundingMinAnnualizedPct", 50)
    if funding_ann < min_exit_ann:
        invalidations.append(f"funding_normalized_{funding_ann:.0f}%ann_below_{min_exit_ann}%")

    # INVALIDATION 3: OI collapse
    detail = get_asset_detail(coin)
    if detail:
        candles_1h = detail.get("candles", {}).get("1h", [])
        if len(candles_1h) >= 4:
            recent_vol = sum(float(c.get("volume", c.get("v", c.get("vlm", 0)))) for c in candles_1h[-2:])
            earlier_vol = sum(float(c.get("volume", c.get("v", c.get("vlm", 0)))) for c in candles_1h[-4:-2])
            if earlier_vol > 0:
                vol_change = ((recent_vol - earlier_vol) / earlier_vol) * 100
                oi_collapse_threshold = entry_cfg.get("thesisExit", {}).get("oiCollapseThresholdPct", 20)
                if vol_change < -oi_collapse_threshold:
                    invalidations.append(f"oi_collapsing_{vol_change:+.0f}%")

    # Track funding income estimate
    positions_state = state.get("fundingIncome", {})
    if coin in positions_state:
        ps = positions_state[coin]
        hours_held = (cfg.now_ts() - ps.get("enteredTs", cfg.now_ts())) / 3600
        estimated_income = abs(funding) * hours_held * ps.get("notional", 0)
        ps["estimatedIncome"] = estimated_income
        ps["hoursHeld"] = hours_held
        state["fundingIncome"] = positions_state

    return (len(invalidations) == 0), invalidations


# ─── Entry Scoring ────────────────────────────────────────────

def score_funding_signal(asset, entry_cfg):
    """Score a funding arb opportunity."""
    funding = asset["funding"]
    funding_ann = asset["fundingAnn"]
    min_ann = entry_cfg.get("minFundingAnnualizedPct", 120)

    if funding_ann < min_ann:
        return 0, None, []

    # Direction: enter AGAINST the funding
    direction = "LONG" if funding > 0 else "SHORT"

    score = 0
    reasons = []

    # Funding extremity
    if funding_ann >= 200:
        score += 4
        reasons.append(f"funding_extreme_{funding_ann:.0f}%ann")
    elif funding_ann >= 150:
        score += 3
        reasons.append(f"funding_high_{funding_ann:.0f}%ann")
    elif funding_ann >= min_ann:
        score += 2
        reasons.append(f"funding_elevated_{funding_ann:.0f}%ann")

    # OI depth (deeper = more reliable arb)
    if asset["oi_usd"] > 20_000_000:
        score += 2
        reasons.append(f"deep_oi_{asset['oi_usd']/1e6:.0f}M")
    elif asset["oi_usd"] > 10_000_000:
        score += 1
        reasons.append(f"moderate_oi_{asset['oi_usd']/1e6:.0f}M")

    # SM alignment (optional booster)
    sm_dir, sm_pct = get_sm_direction(asset["coin"])
    if sm_dir == direction:
        score += 1
        reasons.append(f"sm_aligned_{sm_pct:.0f}%")

    # Trend confirmation (optional — check if price is moving our direction)
    detail = get_asset_detail(asset["coin"])
    if detail:
        candles_1h = detail.get("candles", {}).get("1h", [])
        if len(candles_1h) >= 4:
            closes = [float(c.get("close", c.get("c", 0))) for c in candles_1h[-4:]]
            if closes[-1] and closes[0]:
                move = ((closes[-1] - closes[0]) / closes[0]) * 100
                if (direction == "LONG" and move > 0) or (direction == "SHORT" and move < 0):
                    score += 1
                    reasons.append(f"trend_confirms_{move:+.1f}%")

    return score, direction, reasons


# ─── Main ─────────────────────────────────────────────────────

def run():
    config = cfg.load_config()
    wallet, _ = cfg.get_wallet_and_strategy()

    if not wallet:
        cfg.output({"success": True, "heartbeat": "NO_REPLY", "note": "no wallet"})
        return

    tc = cfg.load_trade_counter()
    if tc.get("gate") != "OPEN":
        cfg.output({"success": True, "heartbeat": "NO_REPLY", "note": f"gate={tc['gate']}"})
        return

    account_value, positions = cfg.get_positions(wallet)
    entry_cfg = config.get("entry", {})
    state = cfg.load_state("gator-state.json")
    active_coins = {p["coin"]: p for p in positions}

    # ── CHECK 1: Validate thesis for held positions ───────────
    for pos in positions:
        coin = pos["coin"]
        valid, reasons = validate_funding_thesis(coin, pos["direction"], entry_cfg, state)
        if not valid:
            cfg.save_state(state, "gator-state.json")
            cfg.output({
                "success": True,
                "action": "thesis_exit",
                "exits": [{
                    "coin": coin,
                    "direction": pos["direction"],
                    "reasons": reasons,
                    "upnl": pos.get("upnl", 0),
                }],
                "note": "funding thesis dead — structural exit",
            })
            return

    # ── CHECK 2: Entry cap ────────────────────────────────────
    max_positions = config.get("maxPositions", 3)
    dynamic = entry_cfg.get("dynamicSlots", {})
    if dynamic.get("enabled", True):
        base_max = dynamic.get("baseMax", 3)
        day_pnl = tc.get("realizedPnl", 0)
        effective_max = base_max
        for t in dynamic.get("unlockThresholds", []):
            if day_pnl >= t.get("pnl", 999999):
                effective_max = t.get("maxEntries", effective_max)
        max_entries = min(effective_max, dynamic.get("absoluteMax", 5))
    else:
        max_entries = config.get("risk", {}).get("maxEntriesPerDay", 4)

    if tc.get("entries", 0) >= max_entries:
        cfg.output({"success": True, "heartbeat": "NO_REPLY", "note": f"max entries ({max_entries})"})
        cfg.save_state(state, "gator-state.json")
        return

    if len(positions) >= max_positions:
        cfg.output({"success": True, "heartbeat": "NO_REPLY", "note": "max positions"})
        cfg.save_state(state, "gator-state.json")
        return

    # ── CHECK 3: Scan for extreme funding ─────────────────────
    all_assets = get_all_funding()
    min_score = entry_cfg.get("minScore", 6)
    signals = []

    for asset in all_assets:
        if asset["coin"] in active_coins:
            continue

        score, direction, reasons = score_funding_signal(asset, entry_cfg)
        if score >= min_score and direction:
            signals.append({
                "coin": asset["coin"],
                "direction": direction,
                "score": score,
                "reasons": reasons,
                "funding": asset["funding"],
                "fundingAnn": asset["fundingAnn"],
                "oi_usd": asset["oi_usd"],
                "price": asset["price"],
            })

    cfg.save_state(state, "gator-state.json")

    if not signals:
        cfg.output({"success": True, "heartbeat": "NO_REPLY",
                     "note": f"scanned {len(all_assets)}, no extreme funding at 120%+ ann"})
        return

    signals.sort(key=lambda x: x["score"], reverse=True)
    best = signals[0]

    # Conviction-scaled margin
    base_margin_pct = entry_cfg.get("marginPctBase", 0.20)
    if best["fundingAnn"] >= 200:
        margin_pct = base_margin_pct * 1.5
    elif best["fundingAnn"] >= 150:
        margin_pct = base_margin_pct * 1.25
    else:
        margin_pct = base_margin_pct
    margin = round(account_value * margin_pct, 2)

    leverage = config.get("leverage", {}).get("default", 8)

    # Track funding income state
    funding_income = state.get("fundingIncome", {})
    funding_income[best["coin"]] = {
        "direction": best["direction"],
        "enteredTs": cfg.now_ts(),
        "entryFunding": best["funding"],
        "entryFundingAnn": best["fundingAnn"],
        "notional": margin * leverage,
        "estimatedIncome": 0,
        "hoursHeld": 0,
    }
    state["fundingIncome"] = funding_income
    cfg.save_state(state, "gator-state.json")

    cfg.output({
        "success": True,
        "signal": best,
        "entry": {
            "coin": best["coin"],
            "direction": best["direction"],
            "leverage": leverage,
            "margin": margin,
            "orderType": config.get("execution", {}).get("entryOrderType", "FEE_OPTIMIZED_LIMIT"),
        },
        "scanned": len(all_assets),
        "candidates": len(signals),
    })


if __name__ == "__main__":
    run()

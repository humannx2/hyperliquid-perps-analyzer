# events/expected_move.py
# ─────────────────────────────────────────────────────────────────
# Estimate an "expected move" around an upcoming event (e.g. next
# earnings release). Two methods blended:
#
#   A. Statistical (random-walk proxy):
#        expected_pct = ATR14_daily / price × sqrt(days_to_event) × 100
#      Lower bound / honest baseline using realized vol.
#
#   B. Historical earnings-move baseline (per ticker):
#        For each of the last K earnings dates we have candles for,
#        compute |close(T+1) - close(T-1)| / close(T-1) × 100.
#        Use the median as the anchored expectation.
#
# Final reported move = max(A, B) — whichever is larger, because
# earnings-driven moves usually outrun pure random-walk.
#
# Inputs come from HL candleSnapshot (daily) + events.fetcher
# earnings_history. No implied-vol / options data is used — we're
# explicit that this is a realized-vol proxy.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import math
import subprocess
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

HL = "https://api.hyperliquid.xyz/info"


def _candles(coin: str, interval: str, lb_ms: int) -> list[tuple]:
    now = int(time.time() * 1000)
    payload = {"type": "candleSnapshot", "req": {
        "coin": coin, "interval": interval,
        "startTime": now - lb_ms, "endTime": now,
    }}
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", HL,
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=15,
        )
        arr = json.loads(r.stdout)
        return [(int(c["t"]), float(c["o"]), float(c["h"]),
                 float(c["l"]), float(c["c"]), float(c["v"])) for c in arr]
    except Exception:
        return []


def _atr_daily(candles: list[tuple], n: int = 14) -> float:
    if len(candles) < n + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][2], candles[i][3], candles[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def _statistical_move_pct(price: float, atr_daily: float, days: int) -> float:
    if price <= 0 or atr_daily <= 0 or days <= 0:
        return 0.0
    return (atr_daily / price) * math.sqrt(days) * 100


def _candle_at_or_before(candles: list[tuple], ts_ms: int) -> tuple | None:
    best = None
    for c in candles:
        if c[0] <= ts_ms:
            best = c
        else:
            break
    return best


def _candle_at_or_after(candles: list[tuple], ts_ms: int) -> tuple | None:
    for c in candles:
        if c[0] >= ts_ms:
            return c
    return None


def _historical_earnings_moves(coin: str, earnings_history: list[dict]) -> list[float]:
    """
    For each past earnings period in `earnings_history` (Finnhub format has a
    `period` key as 'YYYY-MM-DD'), return the 2-day move |close(T+1) -
    close(T-1)| / close(T-1) × 100 using HL daily candles.
    """
    if not earnings_history:
        return []
    # Fetch 400 daily candles (~13 months) — enough for 4 quarters
    candles = _candles(coin, "1d", 400 * 24 * 3600 * 1000)
    if len(candles) < 30:
        return []
    moves: list[float] = []
    for row in earnings_history:
        period = row.get("period")
        if not period:
            continue
        try:
            d = datetime.fromisoformat(period)
        except Exception:
            continue
        ts = int(d.timestamp() * 1000)
        prev = _candle_at_or_before(candles, ts - 24 * 3600 * 1000)
        nxt = _candle_at_or_after(candles, ts + 24 * 3600 * 1000)
        if not prev or not nxt or prev[4] <= 0:
            continue
        pct = abs(nxt[4] - prev[4]) / prev[4] * 100
        # Clamp absurd values (HL sometimes has stub bars around listing)
        if 0 < pct < 50:
            moves.append(pct)
    return moves


def expected_move_for_event(coin: str, price: float, days_to_event: int,
                             earnings_history: list[dict] | None = None) -> dict:
    """
    Blend statistical + historical-earnings baselines.
    Returns:
      {
        "days_to_event": N,
        "current_price": X,
        "atr_daily": A,
        "statistical_pct": S,        # random-walk proxy
        "historical_earnings_pct": H, # median of prior earnings moves, or None
        "historical_n": len(moves_used),
        "expected_pct": max(S, H),   # single headline number
        "lower_band": price * (1 - pct/100),
        "upper_band": price * (1 + pct/100),
        "method": "max(statistical, historical)",
      }
    """
    if days_to_event is None:
        days_to_event = 1
    days = max(1, int(days_to_event))

    # Statistical side
    d_candles = _candles(coin, "1d", 120 * 24 * 3600 * 1000)
    atr_d = _atr_daily(d_candles, 14) if d_candles else 0.0
    stat_pct = _statistical_move_pct(price, atr_d, days)

    # Historical side
    hist_moves = _historical_earnings_moves(coin, earnings_history or [])
    hist_pct = None
    if hist_moves:
        sorted_m = sorted(hist_moves)
        mid = len(sorted_m) // 2
        hist_pct = (sorted_m[mid] if len(sorted_m) % 2
                    else (sorted_m[mid - 1] + sorted_m[mid]) / 2)

    expected = max(stat_pct, hist_pct or 0.0)
    return {
        "days_to_event": days,
        "current_price": price,
        "atr_daily": atr_d,
        "statistical_pct": round(stat_pct, 2),
        "historical_earnings_pct": round(hist_pct, 2) if hist_pct else None,
        "historical_n": len(hist_moves),
        "expected_pct": round(expected, 2),
        "lower_band": round(price * (1 - expected / 100), 2) if expected else price,
        "upper_band": round(price * (1 + expected / 100), 2) if expected else price,
        "method": "max(statistical, historical)",
    }

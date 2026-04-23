#!/usr/bin/env python3
"""
events/preview.py
────────────────────────────────────────────────────────────────────
CLI to inspect the event calendar for one or more tickers without
spinning up the full TickerWorker loop.

Usage:
  python3 events/preview.py NVDA TSLA
  python3 events/preview.py --all                # every ticker in config
  python3 events/preview.py --macro              # just the macro calendar
  python3 events/preview.py NVDA --days 30       # custom lookahead
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from events.fetcher import get_earnings_calendar, get_macro_calendar, upcoming_for_symbol
from events.expected_move import expected_move_for_event
from config.tickers import TICKERS


def _last_price(coin: str) -> float:
    payload = {"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "15m",
        "startTime": int(time.time() * 1000) - 6 * 3600 * 1000,
        "endTime": int(time.time() * 1000),
    }}
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "https://api.hyperliquid.xyz/info",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=10,
        )
        arr = json.loads(r.stdout)
        return float(arr[-1]["c"]) if arr else 0.0
    except Exception:
        return 0.0


def preview_symbol(symbol: str, days: int) -> None:
    cfg = TICKERS.get(symbol, {})
    coin = cfg.get("hl_asset", f"xyz:{symbol}")
    bundle = upcoming_for_symbol(symbol, days=days)
    print(f"\n═══ {symbol} ═══")
    ner = bundle.get("next_earnings")
    if ner:
        print(f"  Next earnings: {ner['date']} ({ner.get('hour') or '?'})  "
              f"EPS est={ner.get('eps_estimate')}  "
              f"in {bundle.get('days_to_earnings')}d")
    else:
        print("  No earnings in window.")

    hist = bundle.get("earnings_history") or []
    if hist:
        print("  Earnings history:")
        for h in hist:
            print(f"    {h['period']:10s}  actual={h.get('eps_actual'):>6}  "
                  f"est={h.get('eps_estimate'):>6}  surprise={h.get('surprise_pct')}")

    if ner and bundle.get("days_to_earnings") is not None:
        price = _last_price(coin)
        em = expected_move_for_event(coin, price, bundle["days_to_earnings"], hist)
        print(f"  Expected move (±): {em['expected_pct']:.2f}%  "
              f"band ${em['lower_band']:.2f} – ${em['upper_band']:.2f}")
        print(f"    statistical: {em['statistical_pct']:.2f}%  "
              f"historical: {em.get('historical_earnings_pct')}%  "
              f"(n={em['historical_n']} quarters)")


def preview_macro(days: int) -> None:
    rows = get_macro_calendar(days)
    print(f"\n═══ Macro — next {days}d ({len(rows)} events) ═══")
    for r in rows[:40]:
        print(f"  {r.get('time','')[:16]}  {r.get('country',''):3s}  {r.get('event','')}  "
              f"prev={r.get('prev')} est={r.get('estimate')}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("symbols", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--macro", action="store_true")
    p.add_argument("--days", type=int, default=14)
    args = p.parse_args()

    if args.macro:
        preview_macro(args.days)
        return

    syms = args.symbols or (list(TICKERS.keys()) if args.all else ["NVDA"])
    for s in syms:
        preview_symbol(s.upper(), args.days)


if __name__ == "__main__":
    main()

# test_full_flow.py
# ─────────────────────────────────────────────────────────────────
# Multi-ticker dry run. Tests first N tickers with a forced
# threshold breach — no need to wait for real market moves.
#
# Usage:
#   python3 test_full_flow.py           # tests first 3 tickers
#   python3 test_full_flow.py NVDA TSLA # tests specific tickers
# ─────────────────────────────────────────────────────────────────

import sys
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from datetime import datetime, timedelta, timezone
from core.condition_engine import evaluate_condition, should_alert
from agents.agent1_news import fetch_news
from agents.agent2_oi import build_oi_report_for_ticker
from agents.agent3_causality import run_causality_analysis
from notifiers.sheets import log_alert
from config.tickers import TICKERS

IST = timezone(timedelta(hours=5, minutes=30))


def run_scenario(symbol: str, cfg: dict):
    print(f"\n{'='*60}")
    print(f"DRY RUN — {symbol} ({cfg.get('full_name', symbol)})")
    print(f"{'='*60}")

    now = datetime.now(IST)
    threshold = cfg["price_change_threshold_pct"]
    fake_start = 100.0
    fake_current = fake_start * (1 + (threshold + 0.5) / 100)

    # Forced C1: price up + OI up
    price_trigger = {
        "asset": symbol,
        "current_price": fake_current,
        "window_start_price": fake_start,
        "price_change_pct": threshold + 0.5,
        "triggered_at": now,
        "trigger_source": "price",
        "volume_trigger": None,
    }

    oi_snapshot = {
        "current_oi": 320000.0,
        "baseline_oi": 300000.0,
        "oi_change_pct": 6.7,
        "direction": "up",
    }

    fake_ctx = {
        "funding": "0.00000625",
        "dayNtlVlm": "35000000",
        "premium": "-0.0001",
        "openInterest": "320000",
        "markPx": str(round(fake_current, 4)),
    }

    print(f"\n[1] Condition classification")
    condition = evaluate_condition(price_trigger, oi_snapshot)
    if condition is None:
        print("    No condition matched — check price/OI directions.")
        return
    print(f"    {condition['condition_id']} — {condition['label']}")

    print(f"\n[2] Agent 1 — news (live SerpAPI call)")
    news_report = fetch_news(symbol, cfg.get("full_name", symbol))
    print(f"    has_news={news_report['has_news']} | {len(news_report['articles'])} articles")
    print(f"    Summary: {news_report['summary'][:250]}...")

    print(f"\n[3] Agent 2 — OI report")
    oi_report = build_oi_report_for_ticker(oi_snapshot, None, fake_ctx)
    print(f"    {oi_report['interpretation'][:150]}...")

    print(f"\n[4] Alert gate")
    alert = should_alert(condition, news_report)
    print(f"    Should alert: {alert}")

    if alert:
        print(f"\n[5] Agent 3 — causality (live LLM call)")
        causality = run_causality_analysis(price_trigger, news_report, oi_report, condition)
        print(f"    Verdict    : {causality.get('verdict')}")
        print(f"    Confidence : {causality.get('confidence')}")
        print(f"    Driver     : {causality.get('primary_driver')}")
        print(f"    Reasoning  : {causality.get('reasoning')}")

        print(f"\n[6] Google Sheets — tab: {cfg['sheets_tab']}")
        log_alert(price_trigger, oi_report, condition, causality, news_report,
                  sheets_tab=cfg["sheets_tab"])
        print(f"    Logged.")
    else:
        print("    Suppressed by alert rules.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_symbols = [s.upper() for s in sys.argv[1:] if s.upper() in TICKERS]
        if not test_symbols:
            print(f"Unknown tickers. Available: {list(TICKERS.keys())}")
            sys.exit(1)
    else:
        test_symbols = list(TICKERS.keys())[:3]

    print(f"Testing: {test_symbols}")
    for sym in test_symbols:
        run_scenario(sym, TICKERS[sym])

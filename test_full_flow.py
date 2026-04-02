import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from datetime import datetime, timedelta, timezone
from core.condition_engine import evaluate_condition, should_alert
from agents.agent1_news import fetch_news
from agents.agent2_oi import build_oi_report
from agents.agent3_causality import run_causality_analysis
from notifiers.sheets import log_alert

IST = timezone(timedelta(hours=5, minutes=30))

def run_scenario(name: str, price_trigger: dict | None, volume_trigger: dict | None, oi_snapshot: dict):
    print(f"\n================ {name} ================")
    if price_trigger is None and volume_trigger is None:
        print("No trigger fired (expected for no-trigger scenario).")
        return

    if price_trigger is None and volume_trigger is not None:
        price_trigger = {
            "asset": "NVDA",
            "current_price": 0.0,
            "window_start_price": 0.0,
            "price_change_pct": 0.0,
            "triggered_at": datetime.now(IST),
            "trigger_source": "volume",
            "volume_trigger": volume_trigger,
        }
    elif price_trigger is not None:
        price_trigger["trigger_source"] = "price+volume" if volume_trigger else "price"
        price_trigger["volume_trigger"] = volume_trigger

    print("--- Step 2: Evaluating condition ---")
    condition = evaluate_condition(price_trigger, oi_snapshot)
    print(f"Condition: {condition}")
    if condition is None:
        print("No condition matched. Stopping this scenario.")
        return

    print("--- Step 3: Agent 1 - News ---")
    news_report = fetch_news()
    print(f"Has news: {news_report['has_news']} | Articles: {len(news_report['articles'])}")

    print("--- Step 4: Agent 2 - OI Report ---")
    oi_report = build_oi_report(oi_snapshot)
    print(f"Interpretation: {oi_report['interpretation']}")

    print("--- Step 5: Should alert? ---")
    alert = should_alert(condition, news_report)
    print(f"Alert: {alert}")

    if alert:
        print("--- Step 6: Agent 3 - Causality ---")
        causality = run_causality_analysis(price_trigger, news_report, oi_report, condition)
        print(f"Verdict   : {causality.get('verdict')}")
        print(f"Confidence: {causality.get('confidence')}")
        print(f"Driver    : {causality.get('primary_driver')}")
        print(f"Reasoning : {causality.get('reasoning')}")

        print("--- Step 7: Logging to Google Sheets ---")
        log_alert(price_trigger, oi_report, condition, causality, news_report)
        print("Done — check your Google Sheet!")
    else:
        print("Alert suppressed by condition rules.")


if __name__ == "__main__":
    oi_snapshot = {
        "current_oi": 329000.0,
        "baseline_oi": 310000.0,
        "oi_change_pct": 6.1,
        "direction": "up",
    }

    run_scenario(
        name="Price-only trigger",
        price_trigger={
            "asset": "NVDA",
            "current_price": 175.86,
            "window_start_price": 171.57,
            "price_change_pct": 2.5,
            "triggered_at": datetime.now(IST),
        },
        volume_trigger=None,
        oi_snapshot=oi_snapshot,
    )

    run_scenario(
        name="Volume-only trigger",
        price_trigger=None,
        volume_trigger={
            "asset": "NVDA",
            "current_volume": 180000000.0,
            "window_start_volume": 160000000.0,
            "volume_change_pct": 12.5,
            "triggered_at": datetime.now(IST),
        },
        oi_snapshot=oi_snapshot,
    )

    run_scenario(
        name="Price+Volume trigger",
        price_trigger={
            "asset": "NVDA",
            "current_price": 175.86,
            "window_start_price": 171.57,
            "price_change_pct": 2.5,
            "triggered_at": datetime.now(IST),
        },
        volume_trigger={
            "asset": "NVDA",
            "current_volume": 180000000.0,
            "window_start_volume": 160000000.0,
            "volume_change_pct": 12.5,
            "triggered_at": datetime.now(IST),
        },
        oi_snapshot=oi_snapshot,
    )

    run_scenario(
        name="No trigger",
        price_trigger=None,
        volume_trigger=None,
        oi_snapshot=oi_snapshot,
    )

# agents/agent3_causality.py
# ─────────────────────────────────────────────────────────────────
# Updated for multi-ticker:
# - Asset name comes from price_trigger["asset"] not global ASSET
# - Volume section added to prompt so LLM reasons about it explicitly
# - primary_driver now includes "volume" as possible value
# - Backward compatible with existing single-ticker main.py
# ─────────────────────────────────────────────────────────────────

import os
import json
import logging
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from config.settings import LLM_PROVIDER, OPENROUTER_API_KEY, OPENROUTER_MODEL, ASSET

logger = logging.getLogger(__name__)


def _build_volume_section(price_trigger: dict) -> str:
    """Build volume context section for the LLM prompt."""
    volume_trigger = price_trigger.get("volume_trigger")
    if not volume_trigger:
        return "## Volume\nNo volume threshold breach this tick."

    return (
        f"## Volume\n"
        f"- 24h notional volume: ${volume_trigger.get('current_volume', 0):,.0f}\n"
        f"- Window start volume: ${volume_trigger.get('window_start_volume', 0):,.0f}\n"
        f"- Volume added in window: ${volume_trigger.get('window_delta', 0):,.0f}\n"
        f"- Volume change: {volume_trigger.get('volume_change_pct', 0):+.2f}%\n"
        f"- Volume threshold breached: yes"
    )


def _build_prompt(price_trigger: dict, news_report: dict, oi_report: dict, condition: dict) -> str:
    # Use asset from trigger (multi-ticker aware), fall back to global ASSET
    asset = price_trigger.get("asset", ASSET)
    trigger_source = price_trigger.get("trigger_source", "price")
    volume_section = _build_volume_section(price_trigger)

    price_pct = price_trigger.get("price_change_pct", 0.0)
    if price_pct != 0.0:
        price_section = (
            f"## Price move\n"
            f"- Current price: {price_trigger['current_price']:.4f}\n"
            f"- Price change: {price_pct:+.2f}% in the last 5 minutes\n"
            f"- Window start price: {price_trigger['window_start_price']:.4f}\n"
            f"- Trigger source: {trigger_source}"
        )
    else:
        price_section = (
            f"## Price move\n"
            f"- No price threshold breach (triggered by volume only)\n"
            f"- Trigger source: {trigger_source}"
        )

    vol_change_line = ""
    if condition.get("volume_change_pct") is not None:
        vol_change_line = f"\n- Volume change: {condition['volume_change_pct']:+.2f}%"

    return f"""You are a quantitative trading analyst. Analyze the following market data for {asset} perpetual futures on Hyperliquid and identify the most likely causal explanation.

{price_section}

## Condition
- {condition['condition_id']} — {condition['label']}: {condition['description']}
- OI change: {condition['oi_change_pct']:+.2f}%{vol_change_line}

## Open Interest
{oi_report['interpretation']}

{volume_section}

## Recent News
{news_report['summary']}

Respond ONLY with a JSON object, no markdown, no preamble:
{{
  "verdict": "one sentence causal explanation",
  "confidence": "high" or "medium" or "low",
  "primary_driver": "news" or "oi_flow" or "volume" or "technical" or "unknown",
  "flags": ["short flag strings"],
  "reasoning": "2-3 sentence explanation"
}}"""


def _call_openrouter(prompt: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.2,
        },
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def run_causality_analysis(price_trigger, news_report, oi_report, condition) -> dict:
    prompt = _build_prompt(price_trigger, news_report, oi_report, condition)
    try:
        if LLM_PROVIDER == "openrouter":
            raw = _call_openrouter(prompt)
        else:
            logger.error(f"[Agent3] Unknown LLM_PROVIDER: {LLM_PROVIDER}")
            return _fallback_verdict()

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw.strip())
        asset = price_trigger.get("asset", ASSET)
        logger.info(f"[Agent3/{asset}] Verdict: {result.get('verdict')} | confidence={result.get('confidence')}")
        return result

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 401:
            logger.error("[Agent3] OpenRouter auth failed (401). Check OPENROUTER_API_KEY.")
        else:
            logger.error(f"[Agent3] LLM HTTP error ({status}): {e}")
        return _fallback_verdict()
    except Exception as e:
        logger.error(f"[Agent3] LLM call failed: {e}")
        return _fallback_verdict()


def _fallback_verdict() -> dict:
    return {
        "verdict": "Unable to determine causality — LLM call failed.",
        "confidence": "low",
        "primary_driver": "unknown",
        "flags": ["agent3_error"],
        "reasoning": "The causality agent encountered an error. Manual review recommended.",
    }

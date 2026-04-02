# agents/agent2_oi.py
# ─────────────────────────────────────────────────────────────────
# Agent 2: Builds a structured OI report from the OITracker snapshot
# and fetches additional context (funding rate, 24hr volume) from HL.
# ─────────────────────────────────────────────────────────────────

import requests
import logging
from config.settings import ASSET
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def fetch_asset_context(asset: str) -> dict | None:
    """
    Fetch full asset context from HL: mark price, OI, funding rate, 24h volume.
    """
    try:
        payload = {"type": "metaAndAssetCtxs"}
        resp = requests.post(HL_INFO_URL, json=payload, timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()

        meta = data[0]
        asset_ctxs = data[1]

        for i, info in enumerate(meta["universe"]):
            if info["name"].upper() == asset.upper():
                ctx = asset_ctxs[i]
                return {
                    "mark_price": float(ctx.get("markPx", 0)),
                    "open_interest": float(ctx.get("openInterest", 0)),
                    "funding_rate": float(ctx.get("funding", 0)),
                    "volume_24h": float(ctx.get("dayNtlVlm", 0)),
                    "premium": float(ctx.get("premium", 0)),
                }
        return None
    except Exception as e:
        logger.error(f"[Agent2] Error fetching asset context: {e}")
        return None


def build_oi_report(oi_snapshot: dict) -> dict:
    """
    Combines OITracker snapshot with live HL context into a full OI report.

    Returns:
    {
        "current_oi": float,
        "baseline_oi": float,
        "oi_change_pct": float,
        "oi_direction": str,
        "funding_rate": float,
        "volume_24h": float,
        "premium": float,
        "interpretation": str,   # human-readable summary for LLM
    }
    """
    ctx = fetch_asset_context(ASSET)

    report = {
        "current_oi": oi_snapshot["current_oi"],
        "baseline_oi": oi_snapshot["baseline_oi"],
        "oi_change_pct": oi_snapshot["oi_change_pct"],
        "oi_direction": oi_snapshot["direction"],
        "funding_rate": ctx["funding_rate"] if ctx else 0.0,
        "volume_24h": ctx["volume_24h"] if ctx else 0.0,
        "premium": ctx["premium"] if ctx else 0.0,
    }

    # Build a readable interpretation string
    oi_dir = oi_snapshot["direction"]
    oi_pct = oi_snapshot["oi_change_pct"]
    funding = report["funding_rate"]
    funding_str = f"{funding * 100:.4f}%"
    funding_bias = "bullish" if funding > 0 else "bearish" if funding < 0 else "neutral"

    report["interpretation"] = (
        f"Open interest has moved {oi_pct:+.2f}% over the past 3 hours ({oi_dir}). "
        f"Current OI: {report['current_oi']:.2f}. "
        f"Funding rate: {funding_str} ({funding_bias} bias). "
        f"24h notional volume: ${report['volume_24h']:,.0f}. "
        f"Basis premium: {report['premium']:.4f}."
    )

    logger.info(f"[Agent2] OI report built: {report['interpretation']}")
    return report

# agents/agent2_oi.py
# ─────────────────────────────────────────────────────────────────
# Updated for multi-ticker: build_oi_report_for_ticker() accepts
# the ctx dict already fetched by ticker_worker — no extra API call.
# Original build_oi_report() kept intact for backward compatibility
# with existing single-ticker main.py.
# ─────────────────────────────────────────────────────────────────

import logging
import requests
from config.settings import ASSET, HL_PERP_DEX
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def build_oi_report_for_ticker(
    oi_snapshot: dict,
    volume_trigger: dict | None,
    ctx: dict,
) -> dict:
    """
    Multi-ticker entry point. Builds OI report from pre-fetched ctx —
    no additional HL API call needed since ticker_worker already has it.

    Args:
        oi_snapshot:    From ticker_worker._update_oi()
        volume_trigger: Volume trigger dict or None
        ctx:            Raw asset ctx from HL metaAndAssetCtxs response
    """
    funding = float(ctx.get("funding") or 0.0)
    volume_24h = float(ctx.get("dayNtlVlm") or 0.0)
    premium = float(ctx.get("premium") or 0.0)

    report = {
        "current_oi": oi_snapshot["current_oi"],
        "baseline_oi": oi_snapshot["baseline_oi"],
        "oi_change_pct": oi_snapshot["oi_change_pct"],
        "oi_direction": oi_snapshot["direction"],
        "funding_rate": funding,
        "volume_24h": volume_24h,
        "premium": premium,
    }

    oi_pct = oi_snapshot["oi_change_pct"]
    oi_dir = oi_snapshot["direction"]
    funding_bias = "bullish" if funding > 0 else "bearish" if funding < 0 else "neutral"

    vol_line = ""
    if volume_trigger:
        vol_line = (
            f" Volume added ${volume_trigger.get('window_delta', 0):,.0f} notional in window "
            f"({volume_trigger.get('volume_change_pct', 0):+.2f}% above baseline)."
        )

    report["interpretation"] = (
        f"OI moved {oi_pct:+.2f}% over the past 3 hours ({oi_dir}). "
        f"Current OI: {report['current_oi']:.2f}. "
        f"Funding: {funding * 100:.4f}% ({funding_bias} bias). "
        f"24h notional volume: ${volume_24h:,.0f}. "
        f"Basis premium: {premium:.4f}."
        f"{vol_line}"
    )

    logger.info(f"[Agent2] {report['interpretation'][:100]}...")
    return report


def fetch_asset_context(asset: str) -> dict | None:
    """Fetch full asset context from HL (used by single-ticker build_oi_report)."""
    try:
        payload = {"type": "metaAndAssetCtxs"}
        if HL_PERP_DEX:
            payload["dex"] = HL_PERP_DEX
        resp = requests.post(HL_INFO_URL, json=payload, timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()

        expected_names = {asset.upper()}
        if HL_PERP_DEX:
            expected_names.add(f"{HL_PERP_DEX}:{asset}".upper())

        for i, info in enumerate(data[0]["universe"]):
            if info["name"].upper() in expected_names:
                ctx = data[1][i]
                return {
                    "funding": ctx.get("funding", 0),
                    "dayNtlVlm": ctx.get("dayNtlVlm", 0),
                    "premium": ctx.get("premium", 0),
                    "openInterest": ctx.get("openInterest", 0),
                    "markPx": ctx.get("markPx", 0),
                }
        return None
    except Exception as e:
        logger.error(f"[Agent2] Error fetching asset context: {e}")
        return None


def build_oi_report(oi_snapshot: dict) -> dict:
    """
    Single-ticker entry point — kept for backward compatibility
    with existing main.py. Fetches ctx itself.
    """
    ctx = fetch_asset_context(ASSET) or {}
    return build_oi_report_for_ticker(oi_snapshot, None, ctx)

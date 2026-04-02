import logging
from collections import deque
from datetime import datetime, timedelta, timezone

import requests
import urllib3

from config.settings import (
    ASSET,
    VOLUME_CHANGE_THRESHOLD_PCT,
    VOLUME_WINDOW_MINUTES,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
IST = timezone(timedelta(hours=5, minutes=30))


def fetch_notional_volume_24h(asset: str) -> float | None:
    """Fetch the current 24h notional volume (dayNtlVlm) for an asset."""
    try:
        payload = {"type": "metaAndAssetCtxs"}
        resp = requests.post(HL_INFO_URL, json=payload, timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()

        meta = data[0]
        asset_ctxs = data[1]

        for i, info in enumerate(meta["universe"]):
            if info["name"].upper() == asset.upper():
                return float(asset_ctxs[i].get("dayNtlVlm", 0))

        logger.warning(f"Asset '{asset}' not found in HL universe for volume.")
        return None
    except Exception as e:
        logger.error(f"Error fetching 24h notional volume: {e}")
        return None


class VolumeMonitor:
    """
    Tracks rolling 24h notional volume snapshots and triggers when the %
    change from window baseline breaches threshold.
    """

    def __init__(self):
        self.window_seconds = VOLUME_WINDOW_MINUTES * 60
        self.threshold_pct = VOLUME_CHANGE_THRESHOLD_PCT
        self.history: deque = deque()

    def _prune_old(self):
        cutoff = datetime.now(IST) - timedelta(seconds=self.window_seconds)
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()

    def tick(self) -> dict | None:
        """
        Returns a trigger dict if threshold is breached, else None.
        {
            "asset": str,
            "current_volume": float,
            "window_start_volume": float,
            "volume_change_pct": float,
            "triggered_at": datetime,
        }
        """
        volume = fetch_notional_volume_24h(ASSET)
        if volume is None:
            return None

        now = datetime.now(IST)
        self.history.append((now, volume))
        self._prune_old()

        if len(self.history) < 2:
            logger.debug(
                f"[VolumeMonitor] Tick — volume={volume:.2f}, history too short to evaluate."
            )
            return None

        window_start_volume = self.history[0][1]
        if window_start_volume == 0:
            logger.warning("[VolumeMonitor] Baseline volume is 0. Skipping threshold check.")
            return None

        change_pct = ((volume - window_start_volume) / window_start_volume) * 100

        logger.info(
            f"[VolumeMonitor] {ASSET} volume24h={volume:.2f} | "
            f"window_start={window_start_volume:.2f} | Δ={change_pct:+.2f}%"
        )

        if abs(change_pct) >= self.threshold_pct:
            logger.info(f"[VolumeMonitor] THRESHOLD BREACHED — Δ={change_pct:+.2f}%")
            return {
                "asset": ASSET,
                "current_volume": volume,
                "window_start_volume": window_start_volume,
                "volume_change_pct": change_pct,
                "triggered_at": now,
            }

        return None

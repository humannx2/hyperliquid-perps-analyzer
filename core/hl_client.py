import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import HL_PERP_DEX

logger = logging.getLogger(__name__)

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def _build_session() -> requests.Session:
    """
    Build a shared HTTP session for Hyperliquid calls.
    - trust_env=False prevents accidental proxy hijacking from shell env.
    - Retry handles transient transport failures at scale.
    """
    session = requests.Session()
    session.trust_env = False

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST"]),
        raise_on_status=False,
    )
    # Keep pool size above concurrent worker count to avoid
    # "Connection pool is full, discarding connection" warnings.
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=32,
        pool_maxsize=32,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def fetch_meta_and_asset_ctxs() -> list | None:
    """
    Fetch Hyperliquid [meta, assetCtxs] payload.
    Returns None on failure.
    """
    try:
        payload = {"type": "metaAndAssetCtxs"}
        if HL_PERP_DEX:
            payload["dex"] = HL_PERP_DEX

        resp = _SESSION.post(HL_INFO_URL, json=payload, timeout=10, verify=False)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching Hyperliquid metaAndAssetCtxs: {e}")
        return None


def fetch_candles(coin: str, interval: str, lookback_ms: int) -> list[tuple]:
    """
    Fetch HL candles as list of (t, o, h, l, c, v) tuples.
    Used by realtime technicals. Returns [] on failure — callers
    must tolerate empty history.
    """
    import time
    now_ms = int(time.time() * 1000)
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": now_ms - lookback_ms,
            "endTime": now_ms,
        },
    }
    try:
        resp = _SESSION.post(HL_INFO_URL, json=payload, timeout=10, verify=False)
        resp.raise_for_status()
        arr = resp.json()
        if not isinstance(arr, list):
            return []
        return [
            (int(c["t"]), float(c["o"]), float(c["h"]),
             float(c["l"]), float(c["c"]), float(c["v"]))
            for c in arr
        ]
    except Exception as e:
        logger.warning(f"fetch_candles({coin}, {interval}) failed: {e}")
        return []

# events/fetcher.py
# ─────────────────────────────────────────────────────────────────
# Pulls two kinds of calendar data:
#
#   1. Per-ticker earnings calendar (next earnings date, EPS/rev
#      estimates, prior surprise). Source: Finnhub.
#   2. Macro-event calendar (FOMC, CPI, NFP, PPI, GDP, unemployment,
#      retail sales, etc.). Source: Finnhub /calendar/economic.
#
# Results are cached to `events/cache/<YYYY-MM-DD>.json` for 24h —
# calendar data doesn't change intra-day and this keeps API usage
# inside Finnhub's free tier (60 req/min).
#
# Env vars:
#   FINNHUB_API_KEY         free at finnhub.io; required for live data
#   EVENTS_LOOKAHEAD_DAYS   default 14 — how far ahead to fetch
#   EVENTS_CACHE_DIR        default events/cache
#
# If FINNHUB_API_KEY is missing, every getter returns an empty list
# — callers should treat events as optional metadata, not a hard
# dependency.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_CACHE_TTL = 24 * 3600  # 24h

# A conservative allowlist so we don't surface noise (every minor PMI print).
# Weight high → push notification worthy; medium → inline context.
HIGH_IMPACT = {
    # US macro
    "fomc", "federal funds rate", "cpi", "core cpi", "ppi", "core ppi",
    "non-farm payrolls", "nfp", "unemployment rate", "gdp", "retail sales",
    "pce", "core pce", "michigan consumer sentiment",
    "ism manufacturing", "ism services",
    "jackson hole", "powell",
}


# ── Cache helpers ────────────────────────────────────────────────

def _cache_dir() -> Path:
    d = Path(os.environ.get("EVENTS_CACHE_DIR", "events/cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.json"


def _cache_get(key: str) -> dict | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
    except Exception:
        return None
    if time.time() - payload.get("_ts", 0) > _CACHE_TTL:
        return None
    return payload.get("data")


def _cache_put(key: str, data) -> None:
    _cache_path(key).write_text(json.dumps({"_ts": time.time(), "data": data}))


# ── Finnhub calls ────────────────────────────────────────────────

def _finnhub_get(path: str, params: dict) -> dict | None:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        logger.info("[events] FINNHUB_API_KEY not set — skipping fetch.")
        return None
    params = dict(params)
    params["token"] = key
    try:
        r = requests.get(f"{_BASE}{path}", params=params, timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.warning(f"[events] Finnhub {path} HTTP {status}: {e}")
    except Exception as e:
        logger.warning(f"[events] Finnhub {path} error: {e}")
    return None


# ── Public API ───────────────────────────────────────────────────

def get_earnings_calendar(days: int | None = None) -> list[dict]:
    """Return list of upcoming earnings rows (symbol, date, epsEstimate, etc.)."""
    lookahead = days or int(os.environ.get("EVENTS_LOOKAHEAD_DAYS", 14))
    today = date.today()
    key = f"earnings_{today.isoformat()}_{lookahead}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    data = _finnhub_get("/calendar/earnings", {
        "from": today.isoformat(),
        "to": (today + timedelta(days=lookahead)).isoformat(),
    })
    rows: list[dict] = []
    if data and isinstance(data.get("earningsCalendar"), list):
        for r in data["earningsCalendar"]:
            rows.append({
                "symbol": (r.get("symbol") or "").upper(),
                "date": r.get("date"),
                "hour": r.get("hour"),  # bmo | amc | dmh
                "eps_estimate": r.get("epsEstimate"),
                "eps_actual": r.get("epsActual"),
                "revenue_estimate": r.get("revenueEstimate"),
                "quarter": r.get("quarter"),
                "year": r.get("year"),
            })
    _cache_put(key, rows)
    return rows


def get_macro_calendar(days: int | None = None) -> list[dict]:
    """Return upcoming high-impact macro events."""
    lookahead = days or int(os.environ.get("EVENTS_LOOKAHEAD_DAYS", 14))
    today = date.today()
    key = f"macro_{today.isoformat()}_{lookahead}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    data = _finnhub_get("/calendar/economic", {
        "from": today.isoformat(),
        "to": (today + timedelta(days=lookahead)).isoformat(),
    })
    rows: list[dict] = []
    if data and isinstance(data.get("economicCalendar"), list):
        for r in data["economicCalendar"]:
            event = (r.get("event") or "").lower()
            # Finnhub provides an `impact` field on paid plans; on free tier
            # we filter by the allowlist of event name keywords.
            impact = (r.get("impact") or "").lower()
            high = impact == "high" or any(k in event for k in HIGH_IMPACT)
            if not high:
                continue
            rows.append({
                "country": r.get("country"),
                "event": r.get("event"),
                "time": r.get("time"),
                "impact": r.get("impact") or "high-by-keyword",
                "actual": r.get("actual"),
                "estimate": r.get("estimate"),
                "prev": r.get("prev"),
            })
    _cache_put(key, rows)
    return rows


def get_earnings_history(symbol: str, limit: int = 4) -> list[dict]:
    """Finnhub /stock/earnings — last N reported quarters with surprise %."""
    symbol = symbol.upper()
    key = f"earnings_hist_{symbol}"
    cached = _cache_get(key)
    if cached is not None:
        return cached[:limit]
    data = _finnhub_get("/stock/earnings", {"symbol": symbol})
    rows: list[dict] = []
    if isinstance(data, list):
        for r in data[:limit]:
            rows.append({
                "period": r.get("period"),
                "eps_actual": r.get("actual"),
                "eps_estimate": r.get("estimate"),
                "surprise_pct": r.get("surprisePercent"),
            })
    _cache_put(key, rows)
    return rows


def upcoming_for_symbol(symbol: str, days: int | None = None) -> dict:
    """
    Merge earnings + macro into a single bundle for one ticker.
    Returns:
      {
        "symbol": "NVDA",
        "next_earnings": {date, hour, eps_estimate, ...} | None,
        "days_to_earnings": int | None,
        "earnings_history": [...],
        "macro_events": [...],   # filtered to US for US tickers; all otherwise
      }
    """
    symbol = symbol.upper()
    cal = get_earnings_calendar(days)
    macro = get_macro_calendar(days)
    hist = get_earnings_history(symbol)

    mine = [e for e in cal if e["symbol"] == symbol]
    mine.sort(key=lambda r: r["date"] or "")
    next_er = mine[0] if mine else None
    dte = None
    if next_er and next_er.get("date"):
        try:
            dte = (datetime.fromisoformat(next_er["date"]).date() - date.today()).days
        except Exception:
            dte = None

    return {
        "symbol": symbol,
        "next_earnings": next_er,
        "days_to_earnings": dte,
        "earnings_history": hist,
        "macro_events": macro,
    }

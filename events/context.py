# events/context.py
# ─────────────────────────────────────────────────────────────────
# Thin facade for ticker_worker: given (symbol, coin, price), return a
# single `event_context` dict with:
#   - next earnings date + days away
#   - expected move ± band around current price
#   - relevant upcoming high-impact macro events
#   - a pre-rendered human-readable string for Telegram
#
# Everything is optional: if FINNHUB_API_KEY is unset, returns a
# `{"enabled": False, ...}` dict the caller can ignore.
#
# Env:
#   EVENTS_CONTEXT_ENABLED   default true — master switch
#   EVENTS_PRE_EARNINGS_DAYS default 5 — show earnings only when within N days
#   EVENTS_MACRO_HORIZON_DAYS default 3 — show macro only when within N days
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import os
from datetime import datetime, date, timezone
from pathlib import Path

from events.fetcher import upcoming_for_symbol
from events.expected_move import expected_move_for_event

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _macro_within(macro_events: list, max_days: int) -> list:
    """Keep only macro events happening within max_days from today."""
    kept = []
    today = date.today()
    for e in macro_events:
        t = e.get("time") or ""
        try:
            d = datetime.fromisoformat(t.replace("Z", "+00:00")).date()
        except Exception:
            try:
                d = datetime.strptime(t[:10], "%Y-%m-%d").date()
            except Exception:
                continue
        dte = (d - today).days
        if 0 <= dte <= max_days:
            e2 = dict(e); e2["days_away"] = dte
            kept.append(e2)
    kept.sort(key=lambda x: x.get("days_away", 99))
    return kept


def _render(ctx: dict) -> str:
    parts = []
    ner = ctx.get("next_earnings")
    dte = ctx.get("days_to_earnings")
    em = ctx.get("expected_move") or {}
    if ner and dte is not None and dte >= 0:
        hour_map = {"bmo": "before open", "amc": "after close", "dmh": "during market"}
        when = hour_map.get(ner.get("hour", ""), ner.get("hour", ""))
        when_str = f" ({when})" if when else ""
        eps = ner.get("eps_estimate")
        eps_str = f"  •  EPS est ${eps}" if eps is not None else ""
        parts.append(f"📅 <b>Earnings in {dte}d</b> — {ner.get('date')}{when_str}{eps_str}")
        if em.get("expected_pct"):
            parts.append(
                f"   Expected move: <b>±{em['expected_pct']:.2f}%</b> "
                f"(${em['lower_band']:.2f} – ${em['upper_band']:.2f})  "
                f"[stat {em.get('statistical_pct', 0):.1f}% / hist {em.get('historical_earnings_pct') or '—'}% over {em.get('historical_n', 0)}q]"
            )
    macro = ctx.get("macro_events_soon") or []
    for e in macro[:3]:
        label = e.get("event") or "event"
        d_str = f"in {e.get('days_away')}d" if e.get("days_away") is not None else "soon"
        parts.append(f"🏛️ <b>{label}</b> — {e.get('country') or '?'} {d_str}")
    if not parts:
        return ""
    return "\n".join(parts)


def get_event_context(symbol: str, hl_asset: str, current_price: float) -> dict:
    """
    Called by ticker_worker when assembling alert payload. Never raises;
    returns `{"enabled": False}` on any error so alerting is not blocked.
    """
    if not _env_bool("EVENTS_CONTEXT_ENABLED", True):
        return {"enabled": False, "reason": "disabled"}
    try:
        pre_er = _env_int("EVENTS_PRE_EARNINGS_DAYS", 5)
        macro_horizon = _env_int("EVENTS_MACRO_HORIZON_DAYS", 3)

        bundle = upcoming_for_symbol(symbol)
        ctx: dict = {
            "enabled": True,
            "symbol": symbol,
            "next_earnings": None,
            "days_to_earnings": bundle.get("days_to_earnings"),
            "expected_move": None,
            "macro_events_soon": _macro_within(bundle.get("macro_events") or [], macro_horizon),
        }
        ner = bundle.get("next_earnings")
        dte = bundle.get("days_to_earnings")

        if ner and dte is not None and 0 <= dte <= pre_er:
            ctx["next_earnings"] = ner
            em = expected_move_for_event(
                hl_asset, current_price, dte, bundle.get("earnings_history") or []
            )
            ctx["expected_move"] = em

        ctx["rendered"] = _render(ctx)
        return ctx
    except Exception as e:
        logger.warning(f"[events/{symbol}] get_event_context failed: {e}")
        return {"enabled": False, "reason": str(e)}

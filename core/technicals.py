# core/technicals.py
# ─────────────────────────────────────────────────────────────────
# Live technical outlook attached to every realtime alert.
#
# Computes five deterministic strategies per ticker from HL candles:
#   1. EMA Ribbon (20/50/200)  — trend
#   2. RSI(14)                  — momentum / mean-reversion
#   3. Donchian 20-period       — breakout
#   4. ATR(14) bands            — volatility stops/targets
#   5. MACD(12,26,9)            — momentum crossover
#
# No LLM involved. Indicator labels, entry/stop/TP levels, and
# confluence verdict all derive from raw prices. Safe in the
# hot path — one HL candleSnapshot call per alert (15m window
# lookback, same session the main loop uses).
#
# Env flag:
#   TECHNICALS_ENABLED   default true — master switch
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import math
import os

from core.hl_client import fetch_candles

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


# ── Pure-python indicators ────────────────────────────────────────

def _ema(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _ema_series(vals: list[float], n: int) -> list[float | None]:
    if len(vals) < n:
        return [None] * len(vals)
    k = 2 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    e = sum(vals[:n]) / n
    out.append(e)
    for v in vals[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0: g += d
        else: l -= d
    ag, al = g / n, l / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))


def _atr(cs: list[tuple], n: int = 14) -> float | None:
    if len(cs) < n + 1:
        return None
    trs = []
    for i in range(1, len(cs)):
        h, l, pc = cs[i][2], cs[i][3], cs[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def _macd(closes: list[float]):
    if len(closes) < 35:
        return None, None, None
    e12 = _ema_series(closes, 12)
    e26 = _ema_series(closes, 26)
    macd_line = [(a - b) if (a is not None and b is not None) else None
                 for a, b in zip(e12, e26)]
    valid = [x for x in macd_line if x is not None]
    if len(valid) < 9:
        return None, None, None
    sig = _ema_series(valid, 9)
    last_macd = valid[-1]; last_sig = sig[-1]
    return last_macd, last_sig, last_macd - last_sig


# ── Strategy evaluators ───────────────────────────────────────────

def _ema_ribbon(price, e20, e50, e200, atr):
    if not (e20 and e50 and e200):
        return "⚪ insufficient data", "—", 0
    if e20 > e50 > e200 and price > e20:
        # Use &gt; so Telegram HTML parser doesn't mistake the math for tags
        return ("🟢 BULL — EMA20&gt;50&gt;200 stacked, price above",
                f"pullback entry ${e20:.2f}, target ${price + 2 * atr:.2f}",
                +1)
    if e20 < e50 < e200 and price < e20:
        return ("🔴 BEAR — EMA20&lt;50&lt;200 stacked, price below",
                f"bounce short ${e20:.2f}, target ${price - 2 * atr:.2f}",
                -1)
    return (f"🟡 MIXED — EMA20 ${e20:.2f} / 50 ${e50:.2f} / 200 ${e200:.2f}",
            "wait for alignment", 0)


def _rsi_signal(price, rsi, atr):
    if rsi is None:
        return "⚪ n/a", "—", 0
    if rsi > 70:
        return (f"🔴 OVERBOUGHT RSI {rsi:.0f}",
                f"mean-reversion short, target ${price - atr:.2f}", -1)
    if rsi < 30:
        return (f"🟢 OVERSOLD RSI {rsi:.0f}",
                f"bounce long, target ${price + atr:.2f}", +1)
    if 50 <= rsi <= 65:
        return (f"🟢 HEALTHY MOMENTUM RSI {rsi:.0f}",
                f"continuation toward ${price + 1.5 * atr:.2f}", +1)
    if 35 <= rsi < 50:
        return (f"🟡 WEAK MOMENTUM RSI {rsi:.0f}",
                "watch for break above 50", 0)
    return (f"🟡 RSI {rsi:.0f}", "neutral", 0)


def _donchian(price, hi20, lo20):
    if not hi20 or not lo20:
        return "⚪ n/a", "—", 0
    if price >= hi20 * 0.998:
        return (f"🟢 BREAKOUT — at 20p high ${hi20:.2f}",
                f"measured move → ${hi20 + (hi20 - lo20):.2f}", +1)
    if price <= lo20 * 1.002:
        return (f"🔴 BREAKDOWN — at 20p low ${lo20:.2f}",
                f"measured move → ${lo20 - (hi20 - lo20):.2f}", -1)
    mid = (hi20 + lo20) / 2
    return (f"🟡 IN RANGE ${lo20:.2f}–${hi20:.2f}",
            f"fade extremes, mid ${mid:.2f}", 0)


def _atr_bands(price, atr):
    return (
        f"ATR(14) = ${atr:.2f} ({atr / price * 100:.1f}% of price)",
        f"stop ${price - 1.5 * atr:.2f} • TP1 ${price + 2 * atr:.2f} • TP2 ${price + 4 * atr:.2f}",
        0,  # ATR is a framework, not directional
    )


def _macd_signal(macd_v, macd_s, hist):
    if macd_v is None:
        return "⚪ n/a", "—", 0
    if hist > 0 and macd_v > 0:
        return (f"🟢 BULL — MACD {macd_v:.2f} &gt; signal, hist +{hist:.2f}",
                "momentum building, continuation likely", +1)
    if hist < 0 and macd_v < 0:
        return (f"🔴 BEAR — MACD {macd_v:.2f} &lt; signal, hist {hist:.2f}",
                "momentum weakening", -1)
    if hist > 0:
        return (f"🟡 TURNING UP — hist +{hist:.2f}",
                "early bullish signal", 0)
    return (f"🟡 TURNING DOWN — hist {hist:.2f}",
            "early bearish signal", 0)


# ── Public API ────────────────────────────────────────────────────

def get_technical_outlook(coin: str, price: float) -> dict:
    """
    Build the technical outlook dict for a single ticker. Safe: returns
    `{"enabled": False}` on insufficient data so callers never break.
    """
    if not _env_bool("TECHNICALS_ENABLED", True):
        return {"enabled": False, "reason": "disabled"}
    try:
        # 15m: ~2 days of bars is plenty for EMA200 + Donchian + RSI + MACD
        c15 = fetch_candles(coin, "15m", 7 * 24 * 3600 * 1000)
        c1d = fetch_candles(coin, "1d", 180 * 24 * 3600 * 1000)
        if len(c15) < 50:
            return {"enabled": False, "reason": "insufficient 15m history"}

        closes15 = [c[4] for c in c15]
        e20 = _ema(closes15, 20); e50 = _ema(closes15, 50); e200 = _ema(closes15, 200)
        rsi_v = _rsi(closes15, 14)
        atr_v = _atr(c15, 14) or price * 0.01
        hi20 = max(c[2] for c in c15[-20:])
        lo20 = min(c[3] for c in c15[-20:])
        macd_v, macd_s, macd_h = _macd(closes15)

        # Daily regime
        d_e50 = d_e200 = d_rsi = None
        regime = None
        if c1d:
            dc = [c[4] for c in c1d]
            d_e50 = _ema(dc, 50); d_e200 = _ema(dc, 200); d_rsi = _rsi(dc, 14)
            if d_e50 and d_e200:
                if price > d_e50 > d_e200:
                    regime = "🟢 golden-cross regime (bullish bias)"
                elif price < d_e50 < d_e200:
                    regime = "🔴 death-cross regime (bearish bias)"
                else:
                    regime = f"🟡 transitional (EMA50 ${d_e50:.2f} / 200 ${d_e200:.2f})"

        s1 = _ema_ribbon(price, e20, e50, e200, atr_v)
        s2 = _rsi_signal(price, rsi_v, atr_v)
        s3 = _donchian(price, hi20, lo20)
        s4 = _atr_bands(price, atr_v)
        s5 = _macd_signal(macd_v, macd_s, macd_h)

        # 24h change from 15m candles (96 bars ≈ 24h)
        chg24 = None
        if len(c15) >= 96:
            chg24 = (price / c15[-96][4] - 1) * 100

        bull = sum(1 for s in (s1, s2, s3, s4, s5) if s[2] > 0)
        bear = sum(1 for s in (s1, s2, s3, s4, s5) if s[2] < 0)
        if bull >= 3:
            confluence = f"🟢 <b>{bull}/5 BULLISH</b> — confluence strong"
        elif bear >= 3:
            confluence = f"🔴 <b>{bear}/5 BEARISH</b> — confluence strong"
        else:
            confluence = f"⚪ <b>MIXED</b> ({bull} bull / {bear} bear)"

        ctx = {
            "enabled": True,
            "price": price,
            "change_24h_pct": round(chg24, 2) if chg24 is not None else None,
            "atr": atr_v,
            "rsi": rsi_v,
            "rsi_daily": d_rsi,
            "ema20": e20, "ema50": e50, "ema200": e200,
            "ema50_daily": d_e50, "ema200_daily": d_e200,
            "donchian_high": hi20, "donchian_low": lo20,
            "macd": macd_v, "macd_signal_line": macd_s, "macd_hist": macd_h,
            "regime": regime,
            "strategies": {
                "ema_ribbon": {"label": s1[0], "target": s1[1], "score": s1[2]},
                "rsi":        {"label": s2[0], "target": s2[1], "score": s2[2]},
                "donchian":   {"label": s3[0], "target": s3[1], "score": s3[2]},
                "atr_bands":  {"label": s4[0], "target": s4[1], "score": s4[2]},
                "macd":       {"label": s5[0], "target": s5[1], "score": s5[2]},
            },
            "confluence": confluence,
        }
        ctx["rendered"] = _render(ctx)
        return ctx
    except Exception as e:
        logger.warning(f"get_technical_outlook({coin}) failed: {e}")
        return {"enabled": False, "reason": str(e)}


def _render(ctx: dict) -> str:
    s = ctx["strategies"]
    chg = ctx.get("change_24h_pct")
    chg_s = f"({chg:+.2f}% 24h)" if chg is not None else ""
    daily_rsi = ctx.get("rsi_daily")
    daily_rsi_s = f" • Daily RSI {daily_rsi:.0f}" if daily_rsi is not None else ""
    lines = [
        f"💲 <b>${ctx['price']:.2f}</b> {chg_s}",
    ]
    if ctx.get("regime"):
        lines.append(f"<b>Daily:</b> {ctx['regime']}{daily_rsi_s}")
    lines.append("<b>Timeframes:</b> scalp 15–60m · intraday 1–4h · swing 2–10d")
    lines.append("<b>Top 5 strategies:</b>")
    lines.append(f"1. <b>EMA Ribbon</b> — {s['ema_ribbon']['label']}")
    lines.append(f"   → {s['ema_ribbon']['target']}")
    lines.append(f"2. <b>RSI(14)</b> — {s['rsi']['label']}")
    lines.append(f"   → {s['rsi']['target']}")
    lines.append(f"3. <b>Donchian 20p</b> — {s['donchian']['label']}")
    lines.append(f"   → {s['donchian']['target']}")
    lines.append(f"4. <b>ATR(14) bands</b> — {s['atr_bands']['label']}")
    lines.append(f"   → {s['atr_bands']['target']}")
    lines.append(f"5. <b>MACD(12,26,9)</b> — {s['macd']['label']}")
    lines.append(f"   → {s['macd']['target']}")
    lines.append(f"<b>Confluence:</b> {ctx['confluence']}")
    return "\n".join(lines)

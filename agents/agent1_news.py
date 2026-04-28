# agents/agent1_news.py
# ─────────────────────────────────────────────────────────────────
# Updated for multi-ticker: fetch_news() now accepts symbol and
# full_name as params so each ticker gets targeted news search.
# Backward compatible — defaults to ASSET from settings if called
# without args (existing single-ticker main.py still works).
# ─────────────────────────────────────────────────────────────────

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import logging
from datetime import datetime, timezone
from config.settings import ASSET, OPENROUTER_API_KEY, OPENROUTER_MODEL, SERP_API_KEY

logger = logging.getLogger(__name__)


def _truncate_on_sentence(text: str, max_len: int) -> str:
    """
    Truncate only at sentence boundaries to avoid mid-sentence chops.
    If no boundary exists within max_len, keep full text.
    """
    if len(text) <= max_len:
        return text
    window = text[:max_len]
    end = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if end == -1:
        return text
    return text[: end + 1]


def _summarize_articles(articles: list, symbol: str, full_name: str) -> str:
    if not articles:
        return "No recent news found."
    if not OPENROUTER_API_KEY:
        logger.warning(f"[Agent1/{symbol}] OPENROUTER_API_KEY missing. Falling back to headlines.")
        return "\n".join(f"- {a['title']} [{a['source']}]" for a in articles[:5])

    context_parts = []
    for i, a in enumerate(articles[:8]):
        part = f"Article {i+1} [{a['source']}] [{a['published_at'][:16]}]\nTitle: {a['title']}"
        if a.get("snippet"):
            part += f"\nSnippet: {a['snippet']}"
        context_parts.append(part)

    prompt = f"""You are a financial news analyst for {symbol} ({full_name}).

STRICT RULES — violating any of these is a failure:
- Use ONLY facts present in the Articles section below.
- Do NOT invent prices, percentages, analyst names, or events that are not written in the articles.
- Do NOT predict future price direction unless an article explicitly states one.
- Every factual sentence must end with a citation in the form [N] where N is the article number.
- If articles are empty, off-topic, or sparse, reply with exactly: {{"summary": "No clear catalyst.", "sentiment": "neutral", "cited_sources": []}}
- Do NOT mention any ticker other than {symbol}.

Articles:
{chr(10).join(context_parts)}

Return ONLY a JSON object, no markdown, no preamble:
{{
  "summary": "3-4 sentence prose summary with [N] citations",
  "sentiment": "bullish" or "bearish" or "mixed" or "neutral",
  "cited_sources": [list of article indices you cited, e.g. [1, 3, 5]]
}}"""

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.1,
            },
            timeout=20,
            verify=False,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        summary, cited = _parse_summary_json(raw, symbol)
        return _validate_summary(summary, cited, articles, symbol)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 401:
            logger.warning(f"[Agent1/{symbol}] OpenRouter auth failed (401). Check OPENROUTER_API_KEY.")
        else:
            logger.warning(f"[Agent1/{symbol}] LLM HTTP error ({status}): {e}")
        return "\n".join(f"- {a['title']} [{a['source']}]" for a in articles[:5])
    except Exception as e:
        logger.warning(f"[Agent1/{symbol}] LLM summarization failed: {e}")
        return "\n".join(f"- {a['title']} [{a['source']}]" for a in articles[:5])


def _parse_summary_json(raw: str, symbol: str) -> tuple[str, list]:
    """Strip code fences, parse JSON, extract summary + cited_sources."""
    import json, re
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        obj = json.loads(s)
        return str(obj.get("summary", "")).strip(), list(obj.get("cited_sources") or [])
    except Exception:
        logger.warning(f"[Agent1/{symbol}] Non-JSON LLM response; using raw as summary.")
        return s, []


def _validate_summary(summary: str, cited: list, articles: list, symbol: str) -> str:
    """
    Post-hoc hallucination checks:
    - If articles were empty but LLM produced a non-trivial summary → discard (fabrication).
    - If any citation index is out of range → strip summary of those markers and flag.
    - If summary mentions a ticker symbol other than `symbol` → flag (log, don't reject).
    """
    import re
    if not articles:
        if summary and "no clear catalyst" not in summary.lower():
            logger.warning(f"[Agent1/{symbol}] FABRICATION GUARD: 0 articles but LLM produced summary; discarding.")
            return "No recent news found."
        return summary or "No recent news found."

    n = len(articles)
    bad_cites = [c for c in cited if not isinstance(c, int) or c < 1 or c > n]
    if bad_cites:
        logger.warning(f"[Agent1/{symbol}] Out-of-range citations {bad_cites}; stripping.")
        summary = re.sub(r"\[\s*\d+\s*\]", lambda m: m.group(0) if (m.group(0).strip("[] ").isdigit() and 1 <= int(m.group(0).strip("[] ")) <= n) else "", summary)

    other_tickers = set(re.findall(r"\b[A-Z]{2,5}\b", summary)) - {symbol, "AI", "CEO", "US", "USA", "SEC", "FDA", "EPS", "Q1", "Q2", "Q3", "Q4", "UBS", "JPM", "AI5", "AI6"}
    if other_tickers:
        logger.info(f"[Agent1/{symbol}] Note: summary mentions other tokens {other_tickers} (may be valid e.g. peer companies).")

    return summary


def fetch_news(symbol: str = ASSET, full_name: str = "") -> dict:
    """
    Fetch and summarize news for a specific ticker.

    Args:
        symbol:    Ticker symbol, e.g. "NVDA", "TSLA"
        full_name: Company name for richer search, e.g. "Nvidia", "Tesla"
                   Falls back to symbol if not provided.
    """
    if not full_name:
        full_name = symbol

    articles = []

    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine": "google_news",
                "q": f"{symbol} {full_name} stock",
                "hl": "en",
                "gl": "us",
                "num": 10,
                "api_key": SERP_API_KEY,
            },
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("news_results", []):
            pub_raw = item.get("date", "")
            try:
                pub_time = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
            except Exception:
                pub_time = datetime.now(tz=timezone.utc)

            source = item.get("source", "")
            if isinstance(source, dict):
                source = source.get("name", "")

            articles.append({
                "title": item.get("title", ""),
                "source": source,
                "published_at": pub_time.isoformat(),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })

        logger.info(f"[Agent1/{symbol}] SerpAPI: {len(articles)} articles found.")

    except Exception as e:
        logger.warning(f"[Agent1/{symbol}] SerpAPI failed: {e}")

    has_news = len(articles) > 0
    logger.info(f"[Agent1/{symbol}] Summarizing via LLM...")
    summary = _summarize_articles(articles, symbol, full_name)
    logger.info(f"[Agent1/{symbol}] Summary: {_truncate_on_sentence(summary, 120)}")

    return {
        "has_news": has_news,
        "articles": articles[:10],
        "summary": summary,
    }

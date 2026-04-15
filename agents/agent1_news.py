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

    prompt = f"""You are a financial news analyst focused on short-term trading signals for {symbol} ({full_name}).

Below are recent news articles. Provide:
1. A 3-4 sentence summary of the key stories and catalysts
2. Overall sentiment: bullish / bearish / mixed / neutral
3. Any specific risks, numbers, or events a trader should know

Articles:
{chr(10).join(context_parts)}

Respond in plain prose. No bullet points. No headers. Be direct and specific."""

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
                "max_tokens": 400,
                "temperature": 0.2,
            },
            timeout=20,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
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
    logger.info(f"[Agent1/{symbol}] Summary: {summary[:120]}...")

    return {
        "has_news": has_news,
        "articles": articles[:10],
        "summary": summary,
    }

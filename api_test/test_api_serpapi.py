import argparse
import os
import sys

import requests
from dotenv import load_dotenv

URL = "https://serpapi.com/search"


def main() -> int:
    parser = argparse.ArgumentParser(description="Test SerpAPI connectivity.")
    parser.add_argument("--query", default="NVDA stock", help="News query to test.")
    parser.add_argument("--ignore-proxy", action="store_true", help="Ignore HTTP(S)_PROXY env vars.")
    args = parser.parse_args()

    load_dotenv(".env")
    key = os.getenv("SERP_API_KEY")
    if not key:
        try:
            from config.settings import SERP_API_KEY as CFG_SERP_API_KEY
            key = (CFG_SERP_API_KEY or "").strip()
        except Exception:
            key = ""
    if not key:
        print("FAIL SerpAPI | SERP_API_KEY missing")
        return 1

    session = requests.Session()
    if args.ignore_proxy:
        session.trust_env = False

    try:
        resp = session.get(
            URL,
            params={
                "engine": "google_news",
                "q": args.query,
                "hl": "en",
                "gl": "us",
                "num": 3,
                "api_key": key,
            },
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("error"):
            print(f"FAIL SerpAPI | API error: {payload['error']}")
            return 1
        count = len(payload.get("news_results", []) or [])
        print(f"PASS SerpAPI | status={resp.status_code} | news_results={count}")
        return 0
    except Exception as e:
        print(f"FAIL SerpAPI | {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

URL = "https://openrouter.ai/api/v1/chat/completions"


def main() -> int:
    parser = argparse.ArgumentParser(description="Test OpenRouter connectivity.")
    parser.add_argument("--model", default=None, help="Override model name.")
    parser.add_argument("--ignore-proxy", action="store_true", help="Ignore HTTP(S)_PROXY env vars.")
    args = parser.parse_args()

    load_dotenv(".env")
    key = os.getenv("OPENROUTER_API_KEY")
    model = args.model or os.getenv("OPENROUTER_MODEL")
    if not key or not model:
        try:
            from config.settings import OPENROUTER_API_KEY as CFG_OPENROUTER_API_KEY, OPENROUTER_MODEL as CFG_OPENROUTER_MODEL
            key = key or (CFG_OPENROUTER_API_KEY or "").strip()
            model = model or (CFG_OPENROUTER_MODEL or "").strip()
        except Exception:
            pass

    if not key:
        print("FAIL OpenRouter | OPENROUTER_API_KEY missing")
        return 1
    if not model:
        print("FAIL OpenRouter | OPENROUTER_MODEL missing")
        return 1

    session = requests.Session()
    if args.ignore_proxy:
        session.trust_env = False

    try:
        resp = session.post(
            URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with: OK"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=20,
            verify=False,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"PASS OpenRouter | status={resp.status_code} | reply={msg[:80]}")
        return 0
    except Exception as e:
        print(f"FAIL OpenRouter | {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

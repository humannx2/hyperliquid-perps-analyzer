import argparse
import sys

import requests

URL = "https://api.hyperliquid.xyz/info"


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Hyperliquid API connectivity.")
    parser.add_argument("--ignore-proxy", action="store_true", help="Ignore HTTP(S)_PROXY env vars.")
    args = parser.parse_args()

    session = requests.Session()
    if args.ignore_proxy:
        session.trust_env = False

    try:
        resp = session.post(URL, json={"type": "metaAndAssetCtxs"}, timeout=12, verify=False)
        resp.raise_for_status()
        data = resp.json()
        universe_size = len(data[0].get("universe", [])) if isinstance(data, list) and data else 0
        print(f"PASS Hyperliquid | status={resp.status_code} | universe_size={universe_size}")
        return 0
    except Exception as e:
        print(f"FAIL Hyperliquid | {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

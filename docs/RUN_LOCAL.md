# Run the service NOW (laptop, no cloud)

Three options ranked by setup effort. Use these while your Oracle Cloud VM is being provisioned.

## Option 1 — Live watcher (lightest, ~30 seconds)

Push real Telegram alerts on any HL price move ≥ threshold. Doesn't need SerpAPI / OpenRouter / Sheets — only Telegram + (optionally) Finnhub.

```bash
cd hyperliquid-perps-analyzer

export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export FINNHUB_API_KEY="..."        # optional but recommended for event tags

python3 tools/live_watch.py --timeout 7200 --threshold 0.5
# 2-hour session, fires when any ticker moves ≥0.5% in 60 min
```

Stop with Ctrl-C. The script sends a startup banner + an exit summary to the channel.

For a long-running version on your laptop, run it in `tmux`:

```bash
tmux new -s hl
python3 tools/live_watch.py --timeout 86400 --threshold 0.7   # 24h
# Ctrl-B then D to detach. tmux attach -t hl to come back.
```

## Option 2 — Full pipeline (`main.py`)

Same code that runs on production. Needs all the upstream credentials.

```bash
# 1. Fill .env
cp deploy/oracle/.env.example .env
nano .env

# 2. (For Google Sheets) drop the service-account JSON next to the project
cp ~/Downloads/credentials.json .

# 3. Install deps once
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Smoke test
python3 tests/qa_hallucination.py     # 22 / 22 should pass
python3 events/preview.py --monthly --days 30 --telegram

# 5. Run the worker
python3 main.py
```

## Option 3 — Generate the report + dashboard, no live worker

If you only want the historical view + the dashboard, no pipeline needed.

```bash
python3 analysis/historical_report.py --days 7 --telegram

# View in browser
open dashboard/index.html
```

The dashboard also runs locally via Python's built-in static server:

```bash
cd dashboard
python3 -m http.server 8080
# open http://localhost:8080
```

## Notes

- The watcher (Option 1) and `main.py` (Option 2) write to `eval/alerts.jsonl`. You can run the dashboard alongside either to see new signals as they're appended (call `analysis/historical_report.py` again to refresh `dashboard/report.json`).
- Anything you launch on the laptop dies when the laptop sleeps / loses power. For 24/7 reliability use the Oracle host (see `docs/HOSTING_ORACLE.md`).

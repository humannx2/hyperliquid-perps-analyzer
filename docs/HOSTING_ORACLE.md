# Hosting on Oracle Cloud Always Free

End-to-end runbook to deploy `hyperliquid-perps-analyzer` on the **Oracle Cloud Always Free** tier. Cost: **$0/month, forever**. The Ampere A1 ARM instance you'll provision is far more capacity than the worker needs (4 vCPU / 24 GB max; we'll use 1 vCPU / 6 GB).

---

## 1. Prerequisites

- Oracle Cloud account (free signup at https://cloud.oracle.com — credit card required for verification, never charged on Always Free).
- An SSH key pair on your laptop. Generate if needed:
  ```bash
  ssh-keygen -t ed25519 -C "hl-analyzer" -f ~/.ssh/hl_analyzer
  ```
- Your secret values ready:
  - `SERP_API_KEY`
  - `OPENROUTER_API_KEY`
  - `OPENROUTER_MODEL` (e.g. `deepseek/deepseek-chat`)
  - `GOOGLE_SHEET_ID` and a Google service-account JSON file
  - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
  - `FINNHUB_API_KEY`

---

## 2. Provision the VM

In the Oracle Cloud Console:

1. **Compute → Instances → Create instance**.
2. **Name:** `hl-analyzer`.
3. **Image:** *Canonical Ubuntu 22.04 (Aarch64 / ARM)* — search for "Ubuntu 22.04" and pick the ARM variant.
4. **Shape:** **Ampere A1 (VM.Standard.A1.Flex)** — Always Free.
   - OCPUs: `1`
   - Memory: `6 GB` (room to grow; can stay on Always Free up to 4 OCPU / 24 GB).
5. **Networking:** keep defaults. A public IPv4 will be assigned.
6. **SSH keys:** paste the contents of `~/.ssh/hl_analyzer.pub`.
7. **Boot volume:** default 47 GB is fine.
8. **Region:** pick the one closest to your timezone (e.g. **Mumbai (`ap-mumbai-1`)** for low latency to IST).
9. Click **Create**. Wait ~60 seconds for state to become **Running**, then copy the **Public IP**.

---

## 3. First SSH

```bash
ssh -i ~/.ssh/hl_analyzer ubuntu@<PUBLIC_IP>
```

If this hangs, the Oracle VCN security list is blocking port 22. Add an ingress rule for TCP 22 from your IP in **Networking → Virtual Cloud Networks → \[your-vcn\] → Default Security List → Add Ingress Rules**.

---

## 4. System setup (run on the VM)

```bash
sudo timedatectl set-timezone Asia/Kolkata

sudo apt update && sudo apt -y upgrade
sudo apt -y install python3-pip python3-venv git
```

Optional but recommended log rotation safeguard for the alerts JSONL:

```bash
sudo tee /etc/logrotate.d/hl-analyzer >/dev/null <<'EOF'
/home/ubuntu/hyperliquid-perps-analyzer/eval/alerts.jsonl {
  weekly
  rotate 8
  compress
  missingok
  notifempty
  copytruncate
}
EOF
```

---

## 5. Clone and install

```bash
cd ~
git clone https://github.com/kushagra93/hyperliquid-perps-analyzer.git
cd hyperliquid-perps-analyzer

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 6. Configure secrets

Copy the env template:

```bash
cp deploy/oracle/.env.example .env
nano .env   # paste real values
```

Upload your Google service-account JSON. From your laptop:

```bash
scp -i ~/.ssh/hl_analyzer ~/Downloads/credentials.json \
    ubuntu@<PUBLIC_IP>:~/hyperliquid-perps-analyzer/credentials.json
```

Then on the VM:

```bash
chmod 600 .env credentials.json
```

Smoke test before launching the long-running worker:

```bash
python3 events/preview.py --monthly --days 30        # exercises Finnhub + HL
python3 -c "from notifiers.telegram import send_message; \
            send_message('<b>🟢 Oracle host online — env verified.</b>')"
python3 tests/qa_hallucination.py                    # 22/22 should be green
```

---

## 7. Install the systemd service

```bash
sudo cp deploy/oracle/hl-analyzer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hl-analyzer
```

Verify:

```bash
systemctl status hl-analyzer        # should show active (running)
journalctl -u hl-analyzer -f        # tail live logs
```

You should see, within ~60s of startup, the multi-ticker tick log lines, and Telegram alerts will start landing the moment any ticker breaches its threshold.

---

## 8. Operations

| Task | Command |
|---|---|
| Tail live logs | `journalctl -u hl-analyzer -f` |
| Last 200 lines | `journalctl -u hl-analyzer -n 200 --no-pager` |
| Restart worker | `sudo systemctl restart hl-analyzer` |
| Stop worker | `sudo systemctl stop hl-analyzer` |
| Disable auto-start | `sudo systemctl disable hl-analyzer` |
| Pull latest code | `cd ~/hyperliquid-perps-analyzer && git pull && sudo systemctl restart hl-analyzer` |
| Edit env | `nano .env && sudo systemctl restart hl-analyzer` |
| Run QA on the host | `cd ~/hyperliquid-perps-analyzer && source .venv/bin/activate && python3 tests/qa_hallucination.py` |
| Backtest (52d) | `cd ~/hyperliquid-perps-analyzer && source .venv/bin/activate && python3 backtest/run_backtest.py --days 52` |
| Monthly review push | `python3 events/preview.py --monthly --days 30 --telegram` |

---

## 9. State persistence

The systemd unit's `WorkingDirectory=/home/ubuntu/hyperliquid-perps-analyzer` means:

- `.state.json` (rolling histories + cooldown timers) is rewritten every tick.
- `eval/alerts.jsonl` (one line per alert) appends forever — logrotate handles weekly rotation.
- `events/cache/*.json` (24h Finnhub cache) regenerates on its own.

A reboot of the VM will resume the worker with all rolling windows intact (`from_state()` rehydrates each TickerWorker on startup).

---

## 10. Cost guardrails

- The Ampere A1 instance is **Always Free** — Oracle never charges on this shape unless you exceed 4 OCPU / 24 GB across all your A1 instances.
- Outbound network: 10 TB/month free. This worker does ~5 MB/day → trivial.
- Block storage: 200 GB free total. 47 GB boot volume leaves headroom.
- Monitor your **Cost Analysis** dashboard for the first month if paranoid.

---

## 11. Tearing down

If you ever decide to stop:

```bash
sudo systemctl disable --now hl-analyzer
```

To delete the VM entirely: Oracle Console → Compute → Instances → terminate. Block volumes can also be deleted from **Block Storage**.

---

## Troubleshooting

**`systemctl status hl-analyzer` shows `failed`:**
- `journalctl -u hl-analyzer -n 100 --no-pager` for the traceback. Most common: missing env var caught by `validate_runtime_settings()`. Fix `.env`, restart.

**No Telegram alerts firing despite real moves:**
- Verify bot token and chat ID by sending a test message directly:
  ```bash
  curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
       -d "chat_id=$TELEGRAM_CHAT_ID&text=ping"
  ```
- Confirm `TELEGRAM_STRONG_ONLY` is not silently filtering your alerts.

**Finnhub returns 429:**
- Free tier is 60 req/min. The 24h cache normally keeps us under. If hammered, increase `EVENTS_CACHE_TTL_SECONDS` in code or set `EVENTS_CONTEXT_ENABLED=false` temporarily.

**ARM-specific package failures during pip install:**
- Most pure-Python deps work fine. If `cryptography` complains, run:
  ```bash
  sudo apt -y install build-essential libffi-dev libssl-dev rustc cargo
  ```
  then retry `pip install -r requirements.txt`.

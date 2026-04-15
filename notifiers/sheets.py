# notifiers/sheets.py
# ─────────────────────────────────────────────────────────────────
# Updated for multi-ticker:
# - log_alert() accepts sheets_tab param (per-ticker tab name)
# - Worksheets are created automatically and cached after first access
#   so the gspread client is only authorized once per process
# - Backward compatible: sheets_tab defaults to GOOGLE_SHEET_TAB
#   from settings so existing single-ticker main.py still works
# ─────────────────────────────────────────────────────────────────

import gspread
import logging
from datetime import datetime, timedelta, timezone
from google.oauth2.service_account import Credentials
from config.settings import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_TAB,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Timestamp (IST)",
    "Ticker",
    "Trigger Source",
    "Current Price",
    "Price Δ%",
    "OI Δ%",
    "Volume 24h",
    "Volume Δ%",
    "Condition",
    "Condition Label",
    "Primary Driver",
    "Confidence",
    "Verdict",
    "Flags",
    "News Summary",
    "Reasoning",
]

IST = timezone(timedelta(hours=5, minutes=30))

# Module-level cache — shared across all tickers in the same process
_sheet_client = None
_ws_cache: dict[str, gspread.Worksheet] = {}


def _get_client() -> gspread.Client:
    global _sheet_client
    if _sheet_client is None:
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
        _sheet_client = gspread.authorize(creds)
    return _sheet_client


def _get_worksheet(tab: str) -> gspread.Worksheet:
    global _ws_cache
    if tab in _ws_cache:
        return _ws_cache[tab]

    client = _get_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    try:
        ws = sheet.worksheet(tab)
    except gspread.WorksheetNotFound:
        try:
            ws = sheet.add_worksheet(title=tab, rows=2000, cols=20)
            logger.info(f"[Sheets] Created worksheet: {tab}")
        except Exception:
            # Another process may have created the tab concurrently.
            ws = sheet.worksheet(tab)

    if not ws.row_values(1):
        ws.append_row(HEADERS, value_input_option="RAW")
        logger.info(f"[Sheets/{tab}] Headers written.")

    _ws_cache[tab] = ws
    return ws


def log_alert(
    price_trigger: dict,
    oi_report: dict,
    condition: dict,
    causality: dict,
    news_report: dict,
    sheets_tab: str = GOOGLE_SHEET_TAB,
):
    """
    Appends one alert row to the specified Google Sheets tab.

    Args:
        sheets_tab: Tab name for this ticker. Defaults to GOOGLE_SHEET_TAB
                    from settings (backward compatible with single-ticker setup).
    """
    try:
        ws = _get_worksheet(sheets_tab)
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        flags_str = ", ".join(causality.get("flags", []))

        volume_trigger = price_trigger.get("volume_trigger") or {}
        vol_24h = oi_report.get("volume_24h", "")
        vol_delta_pct = volume_trigger.get("volume_change_pct", "")

        row = [
            now,
            price_trigger.get("asset", sheets_tab),
            price_trigger.get("trigger_source", "price"),
            round(price_trigger.get("current_price", 0), 4),
            round(price_trigger.get("price_change_pct", 0), 3),
            round(oi_report.get("oi_change_pct", 0), 3),
            round(vol_24h, 0) if isinstance(vol_24h, (int, float)) else "",
            f"{vol_delta_pct:+.2f}%" if isinstance(vol_delta_pct, (int, float)) else "",
            condition["condition_id"],
            condition["label"],
            causality.get("primary_driver", ""),
            causality.get("confidence", ""),
            causality.get("verdict", ""),
            flags_str,
            news_report.get("summary", "")[:500],
            causality.get("reasoning", ""),
        ]

        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(
            f"[Sheets/{sheets_tab}] Row appended — "
            f"{condition['condition_id']} | {causality.get('verdict','')[:60]}"
        )

    except Exception as e:
        logger.error(f"[Sheets/{sheets_tab}] Failed: {e}")

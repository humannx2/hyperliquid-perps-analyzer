import argparse
import os
import sys

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Google Sheets connectivity.")
    parser.add_argument("--sheet-id", default=None, help="Override GOOGLE_SHEET_ID.")
    parser.add_argument("--creds", default=None, help="Override GOOGLE_CREDENTIALS_FILE.")
    args = parser.parse_args()

    load_dotenv(".env")

    sheet_id = args.sheet_id or os.getenv("GOOGLE_SHEET_ID")
    creds_file = args.creds or os.getenv("GOOGLE_CREDENTIALS_FILE")
    if not sheet_id or not creds_file:
        try:
            from config.settings import GOOGLE_SHEET_ID as CFG_GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_FILE as CFG_GOOGLE_CREDENTIALS_FILE
            sheet_id = sheet_id or (CFG_GOOGLE_SHEET_ID or "").strip()
            creds_file = creds_file or (CFG_GOOGLE_CREDENTIALS_FILE or "").strip()
        except Exception:
            pass

    if not sheet_id:
        print("FAIL GoogleSheets | GOOGLE_SHEET_ID missing")
        return 1
    if not creds_file:
        print("FAIL GoogleSheets | GOOGLE_CREDENTIALS_FILE missing")
        return 1
    if not os.path.exists(creds_file):
        print(f"FAIL GoogleSheets | Credentials file not found: {creds_file}")
        return 1

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        print(f"PASS GoogleSheets | title={sheet.title}")
        return 0
    except Exception as e:
        print(f"FAIL GoogleSheets | {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

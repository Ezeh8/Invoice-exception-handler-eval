"""
send_escalation_report.py — reads the most recent run's escalations,
writes each one as a row in a Google Sheet, and posts a short summary
to Slack with a link to the Sheet.

Requires in .env:
  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
  GOOGLE_SHEET_ID=<the long ID from the Sheet's URL>

Requires google_credentials.json (service account key) in this folder.

Run with: python3 send_escalation_report.py
"""

import glob
import json
import os

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
CREDS_FILE = "google_credentials.json"


STATE_FILE = ".last_sent_run_marker"


def get_latest_run_entries():
    log_files = sorted(glob.glob("escalation_log/*.jsonl"))
    if not log_files:
        raise RuntimeError("No escalation log files found. Run the test suite first.")

    with open(log_files[-1]) as f:
        lines = [json.loads(line) for line in f if line.strip()]

    last_run_start = 0
    run_marker_id = None
    for i, entry in enumerate(lines):
        if entry.get("run_marker"):
            last_run_start = i
            run_marker_id = entry["timestamp"]  # unique per run — identifies THIS run

    entries = [e for e in lines[last_run_start:] if not e.get("run_marker")]

    # Fallback identifier for logs with no run_marker at all (older format) —
    # use the first entry's timestamp instead, so dedup still works.
    if run_marker_id is None and entries:
        run_marker_id = entries[0]["timestamp"]

    return entries, run_marker_id


def already_sent(run_marker_id: str) -> bool:
    if not run_marker_id or not os.path.exists(STATE_FILE):
        return False
    with open(STATE_FILE) as f:
        return f.read().strip() == run_marker_id


def mark_as_sent(run_marker_id: str) -> None:
    if run_marker_id:
        with open(STATE_FILE, "w") as f:
            f.write(run_marker_id)


def write_to_sheet(entries):
    if not GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is not set in .env")
    if not os.path.exists(CREDS_FILE):
        raise RuntimeError(f"{CREDS_FILE} not found in this folder")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

    # Header row, only if the sheet is currently empty
    if not sheet.get_all_values():
        sheet.append_row(["Timestamp", "Bill ID", "PO ID", "Bill Vendor", "PO Vendor", "Reason"])

    # Batched as ONE API call, not one call per row — looping append_row()
    # risks hitting Google Sheets' per-minute write quota once entry counts
    # grow past a handful (e.g. the 100-case suite's ~30 exception rows).
    rows = [
        [e["timestamp"], e["bill_id"], e.get("po_id") or "", e["bill_vendor"], e.get("po_vendor") or "", e["reason"]]
        for e in entries
    ]
    sheet.append_rows(rows)

    return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit"


def post_to_slack(entry_count: int, sheet_url: str):
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set in .env")

    message = {
        "text": (
            f":warning: *Invoice Exception Report* — {entry_count} case(s) need review "
            f"from the latest run.\n<{sheet_url}|Open the review sheet>"
        )
    }
    resp = requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)
    resp.raise_for_status()


def main():
    entries, run_marker_id = get_latest_run_entries()
    if not entries:
        print("No escalations in the most recent run — nothing to send.")
        return

    if already_sent(run_marker_id):
        print("This run's escalations were already sent — skipping to avoid duplicate rows/messages.")
        return

    sheet_url = write_to_sheet(entries)
    post_to_slack(len(entries), sheet_url)
    mark_as_sent(run_marker_id)
    print(f"Wrote {len(entries)} rows to the sheet and posted a Slack summary.")
    print(f"Sheet: {sheet_url}")


if __name__ == "__main__":
    main()
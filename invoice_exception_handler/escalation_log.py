"""
Escalations get written to a daily JSONL log, not blocked on mid-run (D3).
scripts/send_escalation_report.py reads the latest run back out of it.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Bill, PurchaseOrder
from .paths import ESCALATION_LOG_DIR


def log_run_start() -> None:
    """Writes a clear separator into today's escalation log so multiple
    test runs on the same day are distinguishable when reviewing later."""
    _append_entry({
        "run_marker": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "=== NEW RUN STARTED ===",
    })


def log_escalation(bill: Bill, po: Optional[PurchaseOrder], reason: str) -> None:
    _append_entry({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bill_id": bill.bill_id,
        "po_id": po.po_id if po else None,
        "bill_vendor": bill.vendor_name,
        "po_vendor": po.vendor_name if po else None,
        "reason": reason,
    })


def _append_entry(entry: dict) -> None:
    ESCALATION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_todays_log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")


def _todays_log_path() -> Path:
    return ESCALATION_LOG_DIR / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"

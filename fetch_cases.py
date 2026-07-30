"""
Pulls every Bill and PurchaseOrder from the sandbox, maps QuickBooks' raw
JSON into the shapes agent.py expects, and freezes the result to a dated
JSON fixture file.

The MAPPING functions are separated from the FETCHING so they can be
tested against sample JSON without ever calling the live API (see
test_mapping.py) — this is what let me verify the logic correctly here,
without network access to QuickBooks.
"""

import json
import sys
from datetime import date
from decimal import Decimal

from qbo_client import qbo_query


# ---------------------------------------------------------------------------
# MAPPING — pure functions, no network calls. QuickBooks' real field names,
# confirmed against Intuit's published Bill/PurchaseOrder schema.
# ---------------------------------------------------------------------------
def map_po(raw: dict) -> dict:
    """
    One QuickBooks PurchaseOrder JSON object -> our flat PO shape.

    NOTE: PurchaseOrder lines use DetailType "ItemBasedExpenseLineDetail" —
    NOT "SalesItemLineDetail" (that's only for Invoices/sales documents).
    Confirmed against a real sample PurchaseOrder response, not assumed.
    """
    line = _first_item_line(raw["Line"])
    detail = line["ItemBasedExpenseLineDetail"]
    return {
        "po_id": raw["Id"],
        "vendor_name": raw["VendorRef"]["name"],
        "item_name": detail["ItemRef"]["name"],
        "qty": int(detail["Qty"]),
        "rate": str(Decimal(str(detail["UnitPrice"]))),
    }


def map_bill(raw: dict) -> dict:
    """
    One QuickBooks Bill JSON object -> our flat Bill shape.

    NOTE: LinkedTxn is a top-level array on the Bill object (confirmed
    against QuickBooks' documented Bill schema), not nested inside the
    line item — earlier draft checked the wrong place.
    """
    line = _first_item_line(raw["Line"])
    detail = line["ItemBasedExpenseLineDetail"]

    linked_po_id = None
    for txn in raw.get("LinkedTxn", []):
        if txn.get("TxnType") == "PurchaseOrder":
            linked_po_id = txn["TxnId"]
            break

    return {
        "bill_id": raw["Id"],
        "vendor_name": raw["VendorRef"]["name"],
        "item_name": detail["ItemRef"]["name"],
        "qty": int(detail["Qty"]),
        "rate": str(Decimal(str(detail["UnitPrice"]))),
        "linked_po_id": linked_po_id,
    }


def _first_item_line(lines: list) -> dict:
    """
    QuickBooks Line arrays can include non-item lines (e.g. a header/
    description line). Skip anything that isn't an item line rather than
    assuming Line[0] is always the real one.
    """
    for line in lines:
        if "SalesItemLineDetail" in line or "ItemBasedExpenseLineDetail" in line:
            return line
    raise ValueError("No item-based line found in this record's Line array.")


# ---------------------------------------------------------------------------
# FETCH + FREEZE — the only part that touches the network.
# ---------------------------------------------------------------------------
def fetch_and_freeze(output_path: str) -> None:
    po_response = qbo_query("select * from PurchaseOrder")
    bill_response = qbo_query("select * from Bill")

    raw_pos = po_response.get("QueryResponse", {}).get("PurchaseOrder", [])
    raw_bills = bill_response.get("QueryResponse", {}).get("Bill", [])

    fixture = {
        "fetched_date": date.today().isoformat(),
        "purchase_orders": [map_po(p) for p in raw_pos],
        "bills": [map_bill(b) for b in raw_bills],
    }

    with open(output_path, "w") as f:
        json.dump(fixture, f, indent=2)

    print(
        f"Wrote {len(fixture['purchase_orders'])} POs and "
        f"{len(fixture['bills'])} Bills to {output_path}"
    )


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "fixture.json"
    fetch_and_freeze(out)

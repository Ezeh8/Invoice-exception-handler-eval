"""
Pulls every Bill and PurchaseOrder from the sandbox, maps QuickBooks' raw
JSON into the shapes the matching engine expects, and freezes the result
to a dated JSON fixture file.

The mapping lives in invoice_exception_handler/quickbooks/mapping.py,
separate from this fetching, so it can be tested without network access
to QuickBooks.

Run from the project root: python3 -m scripts.fetch_cases [output.json]
"""

import json
import sys
from datetime import date

from invoice_exception_handler.quickbooks.client import qbo_query
from invoice_exception_handler.quickbooks.mapping import map_bill, map_po


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

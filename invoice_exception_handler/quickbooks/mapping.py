"""
Maps QuickBooks' raw JSON into the flat shapes the matching engine expects.
Pure functions, no network calls — so they can be tested against sample
JSON without ever calling the live API (see tests/test_quickbooks_mapping.py).

QuickBooks' real field names, confirmed against Intuit's published
Bill/PurchaseOrder schema.
"""

from decimal import Decimal


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

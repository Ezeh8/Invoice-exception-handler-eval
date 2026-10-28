"""
Verifies map_po() / map_bill() against sample JSON shaped exactly like
QuickBooks' real, documented API responses (field names and nesting
taken from Intuit's published Bill/PurchaseOrder schema and a real
sample PurchaseOrder response) — not invented structures.

This is what let me confirm the mapping logic is correct WITHOUT a live
QuickBooks connection, which this sandbox environment can't reach.

Run with: pytest tests/test_quickbooks_mapping.py -v
"""

from invoice_exception_handler.quickbooks.mapping import map_bill, map_po

# Shaped from a real, documented PurchaseOrder API response.
SAMPLE_PO = {
    "Id": "257",
    "DocNumber": "1005",
    "VendorRef": {"name": "Aurelius Tech", "value": "41"},
    "TotalAmt": 1000,
    "Line": [
        {
            "DetailType": "ItemBasedExpenseLineDetail",
            "Amount": 1000,
            "Id": "1",
            "ItemBasedExpenseLineDetail": {
                "ItemRef": {"name": "Widget A", "value": "38"},
                "Qty": 10,
                "UnitPrice": 100,
            },
        }
    ],
}

# Shaped from QuickBooks' documented Bill schema — LinkedTxn is TOP-LEVEL
# on the Bill object, item line uses ItemBasedExpenseLineDetail.
SAMPLE_BILL = {
    "Id": "301",
    "VendorRef": {"name": "Aurelius Tech", "value": "41"},
    "TotalAmt": 1050,
    "LinkedTxn": [{"TxnId": "257", "TxnType": "PurchaseOrder"}],
    "Line": [
        {
            "DetailType": "ItemBasedExpenseLineDetail",
            "Amount": 1050,
            "Id": "1",
            "ItemBasedExpenseLineDetail": {
                "ItemRef": {"name": "Widget A", "value": "38"},
                "Qty": 10,
                "UnitPrice": 105,
            },
        }
    ],
}

# A Bill with no PO link at all — must map linked_po_id to None, not crash.
SAMPLE_BILL_NO_PO = {
    "Id": "302",
    "VendorRef": {"name": "Aurelius Tech", "value": "41"},
    "TotalAmt": 500,
    "LinkedTxn": [],
    "Line": [
        {
            "DetailType": "ItemBasedExpenseLineDetail",
            "Amount": 500,
            "Id": "1",
            "ItemBasedExpenseLineDetail": {
                "ItemRef": {"name": "Widget A", "value": "38"},
                "Qty": 5,
                "UnitPrice": 100,
            },
        }
    ],
}


def test_map_po_reads_documented_purchase_order_fields():
    po = map_po(SAMPLE_PO)
    assert po["po_id"] == "257"
    assert po["vendor_name"] == "Aurelius Tech"
    assert po["qty"] == 10
    assert po["rate"] == "100"


def test_map_bill_reads_top_level_linked_po():
    bill = map_bill(SAMPLE_BILL)
    assert bill["bill_id"] == "301"
    assert bill["vendor_name"] == "Aurelius Tech"
    assert bill["qty"] == 10
    assert bill["rate"] == "105"
    assert bill["linked_po_id"] == "257"


def test_map_bill_without_po_link_gives_none():
    bill = map_bill(SAMPLE_BILL_NO_PO)
    assert bill["linked_po_id"] is None

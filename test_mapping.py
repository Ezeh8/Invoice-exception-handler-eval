"""
Verifies map_po() / map_bill() against sample JSON shaped exactly like
QuickBooks' real, documented API responses (field names and nesting
taken from Intuit's published Bill/PurchaseOrder schema and a real
sample PurchaseOrder response) — not invented structures.

This is what let me confirm the mapping logic is correct WITHOUT a live
QuickBooks connection, which this sandbox environment can't reach.
"""

from fetch_cases import map_po, map_bill

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

results = []

po = map_po(SAMPLE_PO)
checks = [
    (po["po_id"] == "257", f"po_id: expected 257, got {po['po_id']}"),
    (po["vendor_name"] == "Aurelius Tech", f"vendor_name: got {po['vendor_name']}"),
    (po["qty"] == 10, f"qty: got {po['qty']}"),
    (po["rate"] == "100", f"rate: got {po['rate']}"),
]
for ok, msg in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] map_po: {msg}")
    results.append(ok)

bill = map_bill(SAMPLE_BILL)
checks = [
    (bill["bill_id"] == "301", f"bill_id: got {bill['bill_id']}"),
    (bill["vendor_name"] == "Aurelius Tech", f"vendor_name: got {bill['vendor_name']}"),
    (bill["qty"] == 10, f"qty: got {bill['qty']}"),
    (bill["rate"] == "105", f"rate: got {bill['rate']}"),
    (bill["linked_po_id"] == "257", f"linked_po_id: got {bill['linked_po_id']}"),
]
for ok, msg in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] map_bill: {msg}")
    results.append(ok)

bill_no_po = map_bill(SAMPLE_BILL_NO_PO)
ok = bill_no_po["linked_po_id"] is None
print(f"[{'PASS' if ok else 'FAIL'}] map_bill (no PO): linked_po_id is None -> {bill_no_po['linked_po_id']}")
results.append(ok)

print()
print(f"--- {sum(results)}/{len(results)} passed ---")

"""
Runs a fixture through the real matching logic and prints actual vs.
expected verdicts — an early, human-readable runner, superseded by the
pytest suites in tests/.

This is Track B: proves the matching logic works correctly, independent
of whether QuickBooks sandbox access is currently reachable.

Resets the processed_bills table before running, so results are
repeatable across multiple runs.

Run from the project root: python3 -m scripts.run_fixture [fixture.json]
(defaults to the golden dataset)
"""

import sys

from invoice_exception_handler.database import get_db_connection, reset_processed_bills
from invoice_exception_handler.escalation_log import log_run_start
from invoice_exception_handler.fixture_loading import (
    GOLDEN_DATASET_PATH,
    bill_from,
    load_fixture,
    purchase_orders_from,
)
from invoice_exception_handler.matching import match_bill_to_po


def main(fixture_path) -> None:
    fixture = load_fixture(fixture_path)
    purchase_orders = purchase_orders_from(fixture)

    db_conn = get_db_connection()
    reset_processed_bills(db_conn)
    print("Reset processed_bills table — starting from a clean slate.\n")
    log_run_start()

    print(f"{'BILL ID':<12} {'VERDICT':<10} {'EXPECTED CASE'}")
    print("-" * 80)

    for raw_bill in fixture["bills"]:
        bill = bill_from(raw_bill)
        result = match_bill_to_po(bill, purchase_orders, db_conn)

        print(f"{bill.bill_id:<12} {result.verdict.value:<10} {raw_bill.get('_case', '')}")
        print(f"             reason: {result.reason}\n")

    db_conn.close()


if __name__ == "__main__":
    fixture_file = sys.argv[1] if len(sys.argv) > 1 else GOLDEN_DATASET_PATH
    main(fixture_file)

"""
run_fixture_test.py — runs the 6 (7-record) hand-written fixture through
agent.py's real matching logic and prints actual vs. expected verdicts.

This is Track B: proves agent.py works correctly, independent of whether
QuickBooks sandbox access is currently reachable.

Resets the processed_bills table before running, so results are repeatable
across multiple runs — otherwise BILL-2001 (a clean accept) would look like
a false duplicate on the second run, since it would already be marked
processed from the first run.
"""

import json
import sys

from agent import Bill, PurchaseOrder, get_db_connection, log_run_start, match_bill_to_po


def reset_processed_bills(db_conn) -> None:
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE processed_bills")
    db_conn.commit()
    print("Reset processed_bills table — starting from a clean slate.\n")


def main(fixture_path: str) -> None:
    with open(fixture_path) as f:
        fixture = json.load(f)

    purchase_orders = [PurchaseOrder(**po) for po in fixture["purchase_orders"]]

    db_conn = get_db_connection()
    reset_processed_bills(db_conn)
    log_run_start()

    print(f"{'BILL ID':<12} {'VERDICT':<10} {'EXPECTED CASE'}")
    print("-" * 80)

    for bill_data in fixture["bills"]:
        # _case is our own annotation for humans reading the fixture —
        # not part of the real Bill shape, so strip it before validating.
        expected_case = bill_data.pop("_case", "")
        bill = Bill(**bill_data)

        result = match_bill_to_po(bill, purchase_orders, db_conn)

        print(f"{bill.bill_id:<12} {result.verdict.value:<10} {expected_case}")
        print(f"             reason: {result.reason}\n")

    db_conn.close()


if __name__ == "__main__":
    fixture_file = sys.argv[1] if len(sys.argv) > 1 else "fixture.json"
    main(fixture_file)
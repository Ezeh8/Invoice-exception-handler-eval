"""
Scaled regression suite — runs all 100 fixture cases through the matching
logic and asserts each one against its expected_verdict.

Run with: pytest tests/test_regression_100.py -v

Processes bills in FILE ORDER (not shuffled) — this matters because the
4 duplicate cases are placed after their originals in regression_100.json,
and duplicate detection depends on that order (same principle as D6 in
the original 6-case suite, now scaled).

The fuzzy_vendor_match cases (6 of them) make REAL Haiku API calls —
real cost, real network dependency, not mocked.
"""

import pytest

from invoice_exception_handler.database import get_db_connection, reset_processed_bills
from invoice_exception_handler.escalation_log import log_run_start
from invoice_exception_handler.fixture_loading import (
    REGRESSION_100_PATH,
    bill_from,
    load_fixture,
    purchase_orders_from,
)
from invoice_exception_handler.matching import match_bill_to_po
from invoice_exception_handler.models import Verdict

FIXTURE_BILLS = load_fixture(REGRESSION_100_PATH)["bills"]


@pytest.fixture(scope="module")
def purchase_orders():
    return purchase_orders_from(load_fixture(REGRESSION_100_PATH))


@pytest.fixture(scope="module", autouse=True)
def clean_db_once():
    """
    Resets processed_bills ONCE before the whole 100-case run — not per
    test — because this suite deliberately relies on shared, ordered
    state (clean cases must be accepted before their duplicates run).
    Module-scoped, unlike the 6-case suite's per-test reset.

    Also writes ONE run marker (log_run_start) so send_escalation_report.py
    can correctly find this run's escalations.
    """
    log_run_start()
    db_conn = get_db_connection()
    reset_processed_bills(db_conn)
    yield db_conn
    db_conn.close()


def _bill_test_id(bill_data):
    return f"{bill_data['bill_id']}_{bill_data['case_type']}"


@pytest.mark.parametrize(
    "bill_data",
    FIXTURE_BILLS,
    ids=[_bill_test_id(b) for b in FIXTURE_BILLS],
)
def test_bill_matches_expected_verdict(bill_data, purchase_orders, clean_db_once):
    bill = bill_from(bill_data)
    result = match_bill_to_po(bill, purchase_orders, clean_db_once)
    expected = Verdict(bill_data["expected_verdict"])
    assert result.verdict == expected, (
        f"{bill_data['bill_id']} ({bill_data['case_type']}): "
        f"expected {expected.value}, got {result.verdict.value} — {result.reason}"
    )

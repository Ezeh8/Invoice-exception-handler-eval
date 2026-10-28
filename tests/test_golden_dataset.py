"""
Golden dataset — real pass/fail regression tests for the matching logic,
using the 6-case (7-record) hand-written fixture.

Run with: pytest tests/test_golden_dataset.py -v

Note: the fuzzy-vendor-match test makes a REAL Haiku API call each run —
small cost, real network dependency, not mocked. This is deliberate: it
tests the actual behavior, not a stand-in for it.

The duplicate pair (BILL-2003, BILL-2004) is NOT split into two
independent tests — BILL-2004's correct answer depends on BILL-2003
having already run, per D6. Splitting them would misrepresent how the
system actually behaves, so they're asserted together in one test.
"""

import pytest

from invoice_exception_handler.database import get_db_connection, reset_processed_bills
from invoice_exception_handler.escalation_log import log_run_start
from invoice_exception_handler.fixture_loading import (
    GOLDEN_DATASET_PATH,
    bill_from,
    load_fixture,
    purchase_orders_from,
)
from invoice_exception_handler.matching import match_bill_to_po
from invoice_exception_handler.models import Bill, Verdict


@pytest.fixture(scope="session", autouse=True)
def mark_test_session():
    """
    Writes ONE '=== NEW RUN STARTED ===' marker at the start of the whole
    pytest session — not per test. Without this, send_escalation_report.py
    (which looks for the last marker to find "the current run") would
    miss every escalation this suite writes.
    """
    log_run_start()


@pytest.fixture
def fixture_data():
    return load_fixture(GOLDEN_DATASET_PATH)


@pytest.fixture
def purchase_orders(fixture_data):
    return purchase_orders_from(fixture_data)


@pytest.fixture(autouse=True)
def clean_db():
    """
    Resets processed_bills before every test function, so tests don't
    contaminate each other's duplicate-detection state. Runs
    automatically (autouse) — no need to reference it explicitly.
    """
    db_conn = get_db_connection()
    reset_processed_bills(db_conn)
    yield db_conn
    db_conn.close()


def _find_bill(fixture_data, bill_id: str) -> Bill:
    raw = next(b for b in fixture_data["bills"] if b["bill_id"] == bill_id)
    return bill_from(raw)


def test_clean_accept(fixture_data, purchase_orders, clean_db):
    bill = _find_bill(fixture_data, "BILL-2001")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.ACCEPT, f"Expected accept, got {result.verdict}: {result.reason}"


def test_price_variance_escalates(fixture_data, purchase_orders, clean_db):
    bill = _find_bill(fixture_data, "BILL-2002")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.ESCALATE, f"Expected escalate, got {result.verdict}: {result.reason}"


def test_duplicate_pair_second_bill_escalates(fixture_data, purchase_orders, clean_db):
    """
    Order-dependent by design (D6): the original must be processed
    before the duplicate, since duplicate detection only works if
    there's a prior processed record to compare against.
    """
    original = _find_bill(fixture_data, "BILL-2003")
    duplicate = _find_bill(fixture_data, "BILL-2004")

    original_result = match_bill_to_po(original, purchase_orders, clean_db)
    assert original_result.verdict == Verdict.ACCEPT, (
        f"Original bill should accept cleanly, got {original_result.verdict}: {original_result.reason}"
    )

    duplicate_result = match_bill_to_po(duplicate, purchase_orders, clean_db)
    assert duplicate_result.verdict == Verdict.ESCALATE, (
        f"Duplicate bill should escalate, got {duplicate_result.verdict}: {duplicate_result.reason}"
    )


def test_fuzzy_vendor_match_accepts(fixture_data, purchase_orders, clean_db):
    """Makes a real Haiku API call — see module docstring."""
    bill = _find_bill(fixture_data, "BILL-2005")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.ACCEPT, f"Expected accept, got {result.verdict}: {result.reason}"


def test_quantity_mismatch_escalates(fixture_data, purchase_orders, clean_db):
    bill = _find_bill(fixture_data, "BILL-2006")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.ESCALATE, f"Expected escalate, got {result.verdict}: {result.reason}"


def test_validation_failure_rejects(fixture_data, purchase_orders, clean_db):
    bill = _find_bill(fixture_data, "BILL-2007")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.REJECT, f"Expected reject, got {result.verdict}: {result.reason}"

"""
test_agent.py — real pass/fail regression tests for agent.py's matching
logic, using the 6-case (7-record) hand-written fixture.

Run with: pytest test_agent.py -v

Note: the fuzzy-vendor-match test makes a REAL Haiku API call each run —
small cost, real network dependency, not mocked. This is deliberate: it
tests the actual behavior, not a stand-in for it.

The duplicate pair (BILL-2003, BILL-2004) is NOT split into two
independent tests — BILL-2004's correct answer depends on BILL-2003
having already run, per D6. Splitting them would misrepresent how the
system actually behaves, so they're asserted together in one test.
"""

import json

import pytest

from agent import Bill, PurchaseOrder, Verdict, get_db_connection, match_bill_to_po


FIXTURE_PATH = "demofixture1.json"


@pytest.fixture
def fixture_data():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


@pytest.fixture
def purchase_orders(fixture_data):
    return [PurchaseOrder(**po) for po in fixture_data["purchase_orders"]]


@pytest.fixture(autouse=True)
def clean_db():
    """
    Resets processed_bills before every test function, so tests don't
    contaminate each other's duplicate-detection state. Runs
    automatically (autouse) — no need to reference it explicitly.
    """
    db_conn = get_db_connection()
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE processed_bills")
    db_conn.commit()
    yield db_conn
    db_conn.close()


def _find_bill(fixture_data, bill_id: str) -> Bill:
    raw = next(b for b in fixture_data["bills"] if b["bill_id"] == bill_id)
    raw = {k: v for k, v in raw.items() if k != "_case"}
    return Bill(**raw)


def test_clean_accept(fixture_data, purchase_orders, clean_db):
    bill = _find_bill(fixture_data, "BILL-2001")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.ACCEPT, f"Expected accept, got {result.verdict}: {result.reason}"


def test_price_variance_escalates(fixture_data, purchase_orders, clean_db):
    bill = _find_bill(fixture_data, "BILL-2002")
    result = match_bill_to_po(bill, purchase_orders, clean_db)
    assert result.verdict == Verdict.ESCALATE, f"Expected escalate, got {result.verdict}: {result.reason}"


def test_duplicate_pair_second_bill_rejected(fixture_data, purchase_orders, clean_db):
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
    assert duplicate_result.verdict == Verdict.REJECT, (
        f"Duplicate bill should be rejected, got {duplicate_result.verdict}: {duplicate_result.reason}"
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

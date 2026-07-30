"""
test_agent_100.py — scaled regression suite: runs all 100 fixture cases
through agent.py and asserts each one against its expected_verdict.

Run with: pytest test_agent_100.py -v

Processes bills in FILE ORDER (not shuffled) — this matters because the
4 duplicate cases are placed after their originals in fixture_100.json,
and duplicate detection depends on that order (same principle as D6 in
the original 6-case suite, now scaled).

The fuzzy_vendor_match cases (6 of them) make REAL Haiku API calls —
real cost, real network dependency, not mocked.
"""

import json

import pytest

from agent import Bill, PurchaseOrder, Verdict, get_db_connection, match_bill_to_po


FIXTURE_PATH = "fixture_100.json"


def load_fixture():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def fixture_data():
    return load_fixture()


@pytest.fixture(scope="module")
def purchase_orders(fixture_data):
    return [PurchaseOrder(**po) for po in fixture_data["purchase_orders"]]


@pytest.fixture(scope="module", autouse=True)
def clean_db_once():
    """
    Resets processed_bills ONCE before the whole 100-case run — not per
    test — because this suite deliberately relies on shared, ordered
    state (clean cases must be accepted before their duplicates run).
    Module-scoped, unlike the 6-case suite's per-test reset.
    """
    db_conn = get_db_connection()
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE processed_bills")
    db_conn.commit()
    yield db_conn
    db_conn.close()


VERDICT_MAP = {"accept": Verdict.ACCEPT, "escalate": Verdict.ESCALATE, "reject": Verdict.REJECT}


def _bill_test_id(bill_data):
    return f"{bill_data['bill_id']}_{bill_data['case_type']}"


@pytest.mark.parametrize(
    "bill_data",
    load_fixture()["bills"],
    ids=[_bill_test_id(b) for b in load_fixture()["bills"]],
)
def test_bill_matches_expected_verdict(bill_data, purchase_orders, clean_db_once):
    raw = {k: v for k, v in bill_data.items() if k not in ("_case", "expected_verdict", "case_type")}
    bill = Bill(**raw)
    result = match_bill_to_po(bill, purchase_orders, clean_db_once)
    expected = VERDICT_MAP[bill_data["expected_verdict"]]
    assert result.verdict == expected, (
        f"{bill_data['bill_id']} ({bill_data['case_type']}): "
        f"expected {expected.value}, got {result.verdict.value} — {result.reason}"
    )

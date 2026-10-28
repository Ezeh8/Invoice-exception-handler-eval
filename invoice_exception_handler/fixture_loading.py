"""
Loads the frozen JSON fixtures in fixtures/ into validated models, for the
test suites and scripts/run_fixture.py.
"""

import json
from pathlib import Path

from .models import Bill, PurchaseOrder
from .paths import FIXTURES_DIR

GOLDEN_DATASET_PATH = FIXTURES_DIR / "golden_dataset.json"
REGRESSION_100_PATH = FIXTURES_DIR / "regression_100.json"

# Our own annotations for humans and test assertions — not part of the
# real Bill shape, so they're stripped before validating.
FIXTURE_ANNOTATION_KEYS = ("_case", "expected_verdict", "case_type")


def load_fixture(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def purchase_orders_from(fixture: dict) -> list[PurchaseOrder]:
    return [PurchaseOrder(**po) for po in fixture["purchase_orders"]]


def bill_from(raw_bill: dict) -> Bill:
    fields = {k: v for k, v in raw_bill.items() if k not in FIXTURE_ANNOTATION_KEYS}
    return Bill(**fields)

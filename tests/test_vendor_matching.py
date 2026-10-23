"""
Fast, offline tests for vendor-name normalising, LLM answer parsing, and
how the matching engine treats an "unsure" answer. No database or API key
needed: the LLM is replaced with a stub, and every path tested here returns
before the duplicate check touches Postgres.

Run with: pytest tests/test_vendor_matching.py -v
"""

import pytest

from invoice_exception_handler import matching
from invoice_exception_handler.models import Bill, PurchaseOrder, Verdict
from invoice_exception_handler.vendor_matching import (
    VendorMatchAnswer,
    names_match_after_normalising,
    parse_vendor_answer,
)


@pytest.mark.parametrize("bill_vendor, po_vendor", [
    ("Redwood Component Group", "Redwood Components"),
    ("Sterling Hardware Inc", "Sterling Hardware"),
    ("Blue Peak Logistics Ltd", "Bluepeak Logistics"),
    ("ACME, Co.", "Acme"),
])
def test_names_differing_only_in_suffix_plural_or_spacing_match(bill_vendor, po_vendor):
    assert names_match_after_normalising(bill_vendor, po_vendor)


@pytest.mark.parametrize("bill_vendor, po_vendor", [
    ("Redwood Components", "Redwood Logistics"),
    ("Aurelius Technologies Ltd", "Aurelius Tech"),  # an abbreviation is the LLM's job
    ("Group Ltd", "Inc Co"),  # all-suffix names normalise to nothing
])
def test_genuinely_different_or_abbreviated_names_do_not_match(bill_vendor, po_vendor):
    assert not names_match_after_normalising(bill_vendor, po_vendor)


@pytest.mark.parametrize("raw_answer, expected", [
    ("yes", VendorMatchAnswer.YES),
    ("Yes, they are the same company.", VendorMatchAnswer.YES),
    ("No.", VendorMatchAnswer.NO),
    ("Unsure", VendorMatchAnswer.UNSURE),
    ("I think so", VendorMatchAnswer.UNSURE),
    ("", VendorMatchAnswer.UNSURE),
])
def test_llm_answers_parse_with_anything_unclear_as_unsure(raw_answer, expected):
    assert parse_vendor_answer(raw_answer) == expected


@pytest.fixture
def fuzzy_case(tmp_path, monkeypatch):
    """A Bill whose vendor matches no PO exactly, plus one same-item PO
    under a name that only the LLM could judge."""
    monkeypatch.setattr("invoice_exception_handler.escalation_log.ESCALATION_LOG_DIR", tmp_path)
    po = PurchaseOrder(po_id="PO-1", vendor_name="Pioneer Fabrication", item_name="Steel Beam", qty=5, rate="10")
    bill = Bill(bill_id="BILL-1", vendor_name="Pioneer Fab Co", item_name="Steel Beam", qty=5, rate="10")
    return bill, [po]


def _stub_llm(monkeypatch, answer: VendorMatchAnswer):
    monkeypatch.setattr(matching, "ask_llm_if_same_vendor", lambda *args, **kwargs: answer)


def test_unsure_llm_answer_escalates_to_a_human(fuzzy_case, monkeypatch):
    bill, purchase_orders = fuzzy_case
    _stub_llm(monkeypatch, VendorMatchAnswer.UNSURE)
    result = matching.match_bill_to_po(bill, purchase_orders, db_conn=None)
    assert result.verdict == Verdict.ESCALATE
    assert result.po_id == "PO-1"


def test_no_llm_answer_still_rejects(fuzzy_case, monkeypatch):
    bill, purchase_orders = fuzzy_case
    _stub_llm(monkeypatch, VendorMatchAnswer.NO)
    result = matching.match_bill_to_po(bill, purchase_orders, db_conn=None)
    assert result.verdict == Verdict.REJECT

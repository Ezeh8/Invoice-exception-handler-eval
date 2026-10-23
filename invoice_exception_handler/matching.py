"""
The matching/decision engine for the Invoice Exception Handler.

Takes validated PurchaseOrder/Bill models and returns a verdict: accept,
reject, or escalate.

Locked decisions this file implements:
  D1a — two-way matching only (PurchaseOrder vs Bill; no goods-receipt step)
  D1c — Bills matched to POs on vendor_name + po reference, LinkedTxn is a
        bonus signal only, never the sole check
  D1d — single-line POs/Bills only for v1 (already true of the mapping
        output shape — it only ever carries one item line)
  D3  — deterministic rules handle accept/reject; the ONE LLM-judgment case
        is fuzzy vendor-name matching on the escalate path. On escalation,
        the case is written to the logger folder and processing continues —
        no blocking, no waiting on a human mid-run.
"""

from typing import Union

from .database import is_duplicate, mark_processed
from .escalation_log import log_escalation
from .models import Bill, MatchResult, PurchaseOrder, Verdict
from .vendor_matching import llm_vendor_names_match


def match_bill_to_po(bill: Bill, purchase_orders: list[PurchaseOrder], db_conn) -> MatchResult:
    found = _find_candidate_po(bill, purchase_orders)
    if isinstance(found, MatchResult):
        return found
    candidate_po = found

    # Has a DIFFERENT bill_id already touched this PO? A resubmission of
    # the same bill_id (correction) is fine.
    if is_duplicate(candidate_po.po_id, bill.bill_id, db_conn):
        log_escalation(bill, candidate_po, reason=f"Duplicate: PO {candidate_po.po_id} already has a different Bill processed against it.")
        return MatchResult(
            verdict=Verdict.ESCALATE,
            reason=f"Duplicate Bill: PO {candidate_po.po_id} was already touched by a different Bill.",
            po_id=candidate_po.po_id,
            bill_id=bill.bill_id,
        )

    # Record this bill_id against this PO now — regardless of the verdict
    # that follows below. An escalated Bill (e.g. price variance) still
    # "touches" the PO, so a later, different bill_id against the same PO
    # must be caught even if this one never reaches a clean accept.
    mark_processed(bill.bill_id, candidate_po.po_id, db_conn)

    return _compare_quantity_and_rate(bill, candidate_po)


# ---------------------------------------------------------------------------
# Finding the candidate PO (D1c — vendor + reference, LinkedTxn is bonus only).
# Each step returns either the PO it found or a final MatchResult.
# ---------------------------------------------------------------------------
def _find_candidate_po(bill: Bill, purchase_orders: list[PurchaseOrder]) -> Union[PurchaseOrder, MatchResult]:
    if bill.linked_po_id:
        linked_po = next((p for p in purchase_orders if p.po_id == bill.linked_po_id), None)
        if linked_po is not None:
            return linked_po

    # QuickBooks does not auto-link Bills to POs, so this vendor_name match
    # is the primary path in practice, not a fallback.
    exact_vendor_matches = [p for p in purchase_orders if p.vendor_name == bill.vendor_name]
    if len(exact_vendor_matches) == 1:
        return exact_vendor_matches[0]
    if len(exact_vendor_matches) > 1:
        return MatchResult(
            verdict=Verdict.ESCALATE,
            reason="Multiple POs match this vendor name exactly; cannot determine which PO this Bill belongs to.",
            bill_id=bill.bill_id,
        )

    return _find_po_by_fuzzy_vendor(bill, purchase_orders)


def _find_po_by_fuzzy_vendor(bill: Bill, purchase_orders: list[PurchaseOrder]) -> Union[PurchaseOrder, MatchResult]:
    """No exact vendor match — ask the LLM whether a same-item PO's vendor
    is plausibly the same company (D3)."""
    same_item_pos = [p for p in purchase_orders if p.item_name == bill.item_name]

    for po in same_item_pos:
        try:
            if llm_vendor_names_match(po.vendor_name, bill.vendor_name):
                log_escalation(
                    bill, po,
                    reason=f"Fuzzy vendor match accepted by LLM: '{po.vendor_name}' ~ '{bill.vendor_name}'",
                )
                return po
        except Exception as exc:
            # Ollama down, timeout, missing Haiku key, malformed response —
            # whatever the failure, escalate honestly instead of crashing
            # the whole run over one bad case.
            log_escalation(bill, po, reason=f"Fuzzy vendor match call failed: {exc}")
            return MatchResult(
                verdict=Verdict.ESCALATE,
                reason=f"Vendor name '{bill.vendor_name}' has no exact PO match; LLM check failed: {exc}",
                bill_id=bill.bill_id,
            )

    return _reject_unmatched(bill, had_same_item_candidate=bool(same_item_pos))


def _reject_unmatched(bill: Bill, had_same_item_candidate: bool) -> MatchResult:
    # Either no candidate ever existed, or the LLM considered one and did
    # not confirm it. These are different situations for a human reviewer,
    # so the reason says which.
    if had_same_item_candidate:
        reason = (
            f"Vendor name '{bill.vendor_name}' had a same-item candidate PO, "
            f"but the LLM fuzzy-match check did not confirm it as the same vendor."
        )
    else:
        reason = "No matching PO found by any method (no linked PO, no vendor match, no same-item candidate to fuzzy-check)."
    log_escalation(bill, None, reason=reason)
    return MatchResult(
        verdict=Verdict.REJECT,
        reason=reason,
        bill_id=bill.bill_id,
    )


# ---------------------------------------------------------------------------
# Deterministic comparisons (D1a — two-way matching only).
# ---------------------------------------------------------------------------
def _compare_quantity_and_rate(bill: Bill, po: PurchaseOrder) -> MatchResult:
    if po.qty != bill.qty:
        log_escalation(bill, po, reason=f"Quantity mismatch: PO qty {po.qty} vs Bill qty {bill.qty}")
        return MatchResult(
            verdict=Verdict.ESCALATE,
            reason=f"Quantity mismatch: PO {po.qty} vs Bill {bill.qty}",
            po_id=po.po_id,
            bill_id=bill.bill_id,
        )

    if po.rate_decimal != bill.rate_decimal:
        log_escalation(bill, po, reason=f"Price variance: PO rate {po.rate} vs Bill rate {bill.rate}")
        return MatchResult(
            verdict=Verdict.ESCALATE,
            reason=f"Price variance: PO {po.rate} vs Bill {bill.rate}",
            po_id=po.po_id,
            bill_id=bill.bill_id,
        )

    return MatchResult(
        verdict=Verdict.ACCEPT,
        reason="PO and Bill match on vendor, quantity, and rate.",
        po_id=po.po_id,
        bill_id=bill.bill_id,
    )

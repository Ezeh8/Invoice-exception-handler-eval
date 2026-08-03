"""
agent.py — the matching/decision engine for the Invoice Exception Handler.

Takes the flat PO/Bill shapes produced by fetch_cases.py's map_po/map_bill,
validates them with Pydantic, and returns a verdict: accept, reject, or
escalate.

Locked decisions this file implements:
  D1a — two-way matching only (PurchaseOrder vs Bill; no goods-receipt step)
  D1c — Bills matched to POs on vendor_name + po reference, LinkedTxn is a
        bonus signal only, never the sole check
  D1d — single-line POs/Bills only for v1 (already true of map_po/map_bill's
        output shape — they only ever carry one item line)
  D3  — deterministic rules handle accept/reject; the ONE LLM-judgment case
        is fuzzy vendor-name matching on the escalate path. On escalation,
        the case is written to the logger folder and processing continues —
        no blocking, no waiting on a human mid-run.
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

import psycopg2
import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()  # loads ANTHROPIC_API_KEY etc. from .env — needed independently
               # of qbo_client.py's own load_dotenv() call, since these are
               # separate modules


def get_db_connection():
    """
    Connection to ieh-postgres — a fresh, separate container from
    cara-postgres, per the locked decision to keep zero shared runtime
    dependency with Cara.
    """
    return psycopg2.connect(
        host="localhost",
        port=5434,
        dbname="ieh",
        user="ieh",
        password=os.environ.get("IEH_DB_PASSWORD", "iwontchangeyou"),
    )


# ---------------------------------------------------------------------------
# Pydantic models — validate the shapes coming out of map_po / map_bill.
# Catches malformed sandbox data at the boundary, with a clear error,
# instead of failing confusingly deeper in the matching logic.
# ---------------------------------------------------------------------------
class PurchaseOrder(BaseModel):
    po_id: str
    vendor_name: str
    item_name: str
    qty: int = Field(gt=0)
    rate: str  # kept as string in, converted to Decimal for comparison

    @field_validator("rate")
    @classmethod
    def rate_must_be_valid_decimal(cls, v: str) -> str:
        try:
            Decimal(v)
        except InvalidOperation:
            raise ValueError(f"rate '{v}' is not a valid decimal number")
        return v

    @property
    def rate_decimal(self) -> Decimal:
        return Decimal(self.rate)


class Bill(BaseModel):
    bill_id: str
    vendor_name: str
    item_name: str
    qty: int = Field(gt=0)
    rate: str
    linked_po_id: Optional[str] = None

    @field_validator("rate")
    @classmethod
    def rate_must_be_valid_decimal(cls, v: str) -> str:
        try:
            Decimal(v)
        except InvalidOperation:
            raise ValueError(f"rate '{v}' is not a valid decimal number")
        return v

    @property
    def rate_decimal(self) -> Decimal:
        return Decimal(self.rate)


class Verdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    ESCALATE = "escalate"


class MatchResult(BaseModel):
    verdict: Verdict
    reason: str
    po_id: Optional[str] = None
    bill_id: str


# ---------------------------------------------------------------------------
# Logger — escalations get written here, not blocked on mid-run (D3).
# ---------------------------------------------------------------------------
LOGGER_DIR = os.path.join(os.path.dirname(__file__), "escalation_log")


def log_run_start() -> None:
    """Writes a clear separator into today's escalation log so multiple
    test runs on the same day are distinguishable when reviewing later."""
    os.makedirs(LOGGER_DIR, exist_ok=True)
    log_path = os.path.join(LOGGER_DIR, f"{datetime.now(timezone.utc).date().isoformat()}.jsonl")
    marker = {
        "run_marker": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "=== NEW RUN STARTED ===",
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(marker) + "\n")


def _log_escalation(bill: Bill, po: Optional[PurchaseOrder], reason: str) -> None:
    os.makedirs(LOGGER_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bill_id": bill.bill_id,
        "po_id": po.po_id if po else None,
        "bill_vendor": bill.vendor_name,
        "po_vendor": po.vendor_name if po else None,
        "reason": reason,
    }
    log_path = os.path.join(LOGGER_DIR, f"{datetime.now(timezone.utc).date().isoformat()}.jsonl")
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Fuzzy vendor-name matching — the ONE LLM-judgment case (D3).
# Deliberately isolated in its own function so it's the only place an LLM
# call happens; everything else in this file is pure deterministic logic.
# ---------------------------------------------------------------------------
def llm_vendor_names_match(name_a: str, name_b: str, model: str = "haiku") -> bool:
    """
    Real LLM call for fuzzy vendor-name matching (D3, D7).
    Default is "haiku" — qwen2.5:7b proved accurate but took ~12 minutes
    per call on this hardware (cold start), impractical for a pipeline.
    qwen2.5:3b is fast but got this exact case wrong. Haiku is fast AND
    correct, at a small per-call cost — the honest cost-quality tradeoff
    from D7, resolved in Haiku's favor for this specific judgment call.
    model="ollama" still available (uses local qwen2.5:3b) for testing
    the cost/quality difference side by side.
    """
    prompt = (
        f'Are "{name_a}" and "{name_b}" plausibly the same company '
        f'(e.g. abbreviations, legal suffixes like Ltd/Inc, minor spelling '
        f'differences)? Answer with exactly one word: yes or no.'
    )

    if model == "ollama":
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen2.5:3b", "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        answer = resp.json()["response"].strip().lower()

    elif model == "haiku":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file before "
                "calling model='haiku'."
            )
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = resp.content[0].text.strip().lower()

    else:
        raise ValueError(f"Unknown model: {model!r}. Use 'ollama' or 'haiku'.")

    # Take the first real word rather than a strict startswith — small
    # models often add filler ("Yes, they appear to be...") that a plain
    # startswith would still catch, but "I think yes" would not.
    first_word = answer.strip(".,!?").split()[0] if answer.strip() else ""
    return first_word == "yes"


# ---------------------------------------------------------------------------
# Duplicate detection — needs persistent state across runs (D6).
# Backed by ieh-postgres, a fresh container separate from Cara's.
# ---------------------------------------------------------------------------
def is_duplicate(po_id: str, bill_id: str, db_conn) -> bool:
    """True if a DIFFERENT bill_id has already touched this PO. A
    resubmission of the SAME bill_id (e.g. a correction after a human
    fixes the bill) is not a duplicate."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_bills WHERE po_id = %s AND bill_id != %s",
            (po_id, bill_id),
        )
        return cur.fetchone() is not None


def mark_processed(bill_id: str, po_id: str, db_conn) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO processed_bills (bill_id, po_id) VALUES (%s, %s) "
            "ON CONFLICT (bill_id) DO NOTHING",
            (bill_id, po_id),
        )
    db_conn.commit()


# ---------------------------------------------------------------------------
# Core matching logic.
# ---------------------------------------------------------------------------
def match_bill_to_po(bill: Bill, purchase_orders: list[PurchaseOrder], db_conn) -> MatchResult:
    # --- Step 1: find candidate PO (D1c — vendor + reference, LinkedTxn is bonus only) ---
    candidate_po: Optional[PurchaseOrder] = None

    if bill.linked_po_id:
        candidate_po = next((p for p in purchase_orders if p.po_id == bill.linked_po_id), None)

    if candidate_po is None:
        # Fall back to vendor_name match — QuickBooks does not auto-link
        # Bills to POs, so this is the primary path, not a fallback in practice.
        exact_vendor_matches = [p for p in purchase_orders if p.vendor_name == bill.vendor_name]
        if len(exact_vendor_matches) == 1:
            candidate_po = exact_vendor_matches[0]
        elif len(exact_vendor_matches) > 1:
            return MatchResult(
                verdict=Verdict.ESCALATE,
                reason="Multiple POs match this vendor name exactly; cannot determine which PO this Bill belongs to.",
                bill_id=bill.bill_id,
            )

    # --- Step 2: no exact vendor match found — try fuzzy vendor matching (D3, LLM) ---
    fuzzy_considered = False
    if candidate_po is None:
        fuzzy_candidates = [p for p in purchase_orders if p.item_name == bill.item_name]
        fuzzy_considered = len(fuzzy_candidates) > 0
        for po in fuzzy_candidates:
            try:
                if llm_vendor_names_match(po.vendor_name, bill.vendor_name):
                    candidate_po = po
                    _log_escalation(
                        bill, po,
                        reason=f"Fuzzy vendor match accepted by LLM: '{po.vendor_name}' ~ '{bill.vendor_name}'",
                    )
                    break
            except Exception as exc:
                # Ollama down, timeout, missing Haiku key, malformed response —
                # whatever the failure, escalate honestly instead of crashing
                # the whole run over one bad case.
                _log_escalation(bill, po, reason=f"Fuzzy vendor match call failed: {exc}")
                return MatchResult(
                    verdict=Verdict.ESCALATE,
                    reason=f"Vendor name '{bill.vendor_name}' has no exact PO match; LLM check failed: {exc}",
                    bill_id=bill.bill_id,
                )

    # --- Step 3: still nothing — either no candidate ever existed, or the LLM
    # considered one via fuzzy matching and did not confirm it. These are
    # different situations for a human reviewer, so the reason says which. ---
    if candidate_po is None:
        if fuzzy_considered:
            reason = (
                f"Vendor name '{bill.vendor_name}' had a same-item candidate PO, "
                f"but the LLM fuzzy-match check did not confirm it as the same vendor."
            )
        else:
            reason = "No matching PO found by any method (no linked PO, no vendor match, no same-item candidate to fuzzy-check)."
        _log_escalation(bill, None, reason=reason)
        return MatchResult(
            verdict=Verdict.REJECT,
            reason=reason,
            bill_id=bill.bill_id,
        )

    # --- Step 4: duplicate check — has a DIFFERENT bill_id already touched
    # this PO? A resubmission of the same bill_id (correction) is fine. ---
    if is_duplicate(candidate_po.po_id, bill.bill_id, db_conn):
        _log_escalation(bill, candidate_po, reason=f"Duplicate: PO {candidate_po.po_id} already has a different Bill processed against it.")
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

    # --- Step 5: deterministic comparisons (D1a — two-way matching only) ---
    if candidate_po.qty != bill.qty:
        _log_escalation(bill, candidate_po, reason=f"Quantity mismatch: PO qty {candidate_po.qty} vs Bill qty {bill.qty}")
        return MatchResult(
            verdict=Verdict.ESCALATE,
            reason=f"Quantity mismatch: PO {candidate_po.qty} vs Bill {bill.qty}",
            po_id=candidate_po.po_id,
            bill_id=bill.bill_id,
        )

    if candidate_po.rate_decimal != bill.rate_decimal:
        _log_escalation(bill, candidate_po, reason=f"Price variance: PO rate {candidate_po.rate} vs Bill rate {bill.rate}")
        return MatchResult(
            verdict=Verdict.ESCALATE,
            reason=f"Price variance: PO {candidate_po.rate} vs Bill {bill.rate}",
            po_id=candidate_po.po_id,
            bill_id=bill.bill_id,
        )

    # --- Step 6: everything matches — clean accept ---
    return MatchResult(
        verdict=Verdict.ACCEPT,
        reason="PO and Bill match on vendor, quantity, and rate.",
        po_id=candidate_po.po_id,
        bill_id=bill.bill_id,
    )
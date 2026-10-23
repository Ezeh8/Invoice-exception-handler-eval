"""
Pydantic models — validate the flat PO/Bill shapes produced by
quickbooks/mapping.py. Catches malformed sandbox data at the boundary,
with a clear error, instead of failing confusingly deeper in the
matching logic.
"""

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LineItemDocument(BaseModel):
    """Fields shared by Purchase Orders and Bills — both are single-line
    for v1 (D1d), so each carries exactly one item."""

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


class PurchaseOrder(LineItemDocument):
    po_id: str


class Bill(LineItemDocument):
    bill_id: str
    linked_po_id: Optional[str] = None


class Verdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    ESCALATE = "escalate"


class MatchResult(BaseModel):
    verdict: Verdict
    reason: str
    po_id: Optional[str] = None
    bill_id: str

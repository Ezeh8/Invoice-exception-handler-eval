"""
Duplicate detection needs persistent state across runs (D6), backed by
ieh-postgres — a fresh, separate container from cara-postgres, per the
locked decision to keep zero shared runtime dependency with Cara.
"""

import os

import psycopg2


def get_db_connection():
    password = os.environ.get("IEH_DB_PASSWORD")
    if not password:
        raise RuntimeError(
            "IEH_DB_PASSWORD is not set. Add it to your .env file before "
            "connecting to ieh-postgres."
        )
    return psycopg2.connect(
        host="localhost",
        port=5434,
        dbname="ieh",
        user="ieh",
        password=password,
    )


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


def reset_processed_bills(db_conn) -> None:
    """Empties processed_bills so test and fixture runs are repeatable —
    otherwise a clean accept from a previous run would look like a false
    duplicate on the next one."""
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE processed_bills")
    db_conn.commit()

"""
Project folder locations, anchored to this file rather than the current
working directory, so tests and scripts find the same folders no matter
where they're run from.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "fixtures"
ESCALATION_LOG_DIR = PROJECT_ROOT / "escalation_log"

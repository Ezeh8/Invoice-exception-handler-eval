"""
Invoice Exception Handler — matches QuickBooks Bills to Purchase Orders and
decides accept / reject / escalate. Start reading at matching.py.
"""

from dotenv import load_dotenv

# Loaded once here, on first import of the package, so every module
# (database password, Anthropic key) sees the project's .env without
# each one having to call load_dotenv() itself.
load_dotenv()

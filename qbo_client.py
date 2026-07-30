"""
QuickBooks Online API client — authentication + raw HTTP calls only.
No business logic lives here. That's agent.py's job.

Setup (one time):
  1. In your Intuit app dashboard, get: Client ID, Client Secret, Realm ID
     (Realm ID = your sandbox company ID, e.g. 9341457582663343 — you
     already have this from creating the sandbox).
  2. Run the OAuth Playground (developer.intuit.com -> your app -> OAuth
     Playground tab) to get a Refresh Token. This is the easiest path —
     it does the browser login dance for you and hands you a token.
  3. Put all four values in a .env file next to this script:

     QBO_CLIENT_ID=...
     QBO_CLIENT_SECRET=...
     QBO_REALM_ID=9341457582663343
     QBO_REFRESH_TOKEN=...

  4. pip install requests python-dotenv --break-system-packages
"""

import os
import time

import requests
from dotenv import find_dotenv, load_dotenv, set_key

_ENV_PATH = find_dotenv()
load_dotenv(_ENV_PATH)

SANDBOX_BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

_access_token_cache = {"token": None, "expires_at": 0}


def _refresh_access_token() -> str:
    """
    Access tokens expire in ~1 hour. Refresh tokens are long-lived but
    ALSO rotate on use — Intuit issues a new refresh token on every
    refresh call. If you only have one script run per session this is
    invisible; if you run this script repeatedly across days, save the
    new refresh_token from the response back into your .env or the next
    run will fail with an expired-token error.
    """
    client_id = os.environ["QBO_CLIENT_ID"]
    client_secret = os.environ["QBO_CLIENT_SECRET"]
    refresh_token = os.environ["QBO_REFRESH_TOKEN"]

    resp = requests.post(
        TOKEN_URL,
        headers={"Accept": "application/json"},
        auth=(client_id, client_secret),
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    if not resp.ok:
        print(f"QuickBooks rejected the token request. Status: {resp.status_code}")
        print(f"Reason from QuickBooks: {resp.text}")
    resp.raise_for_status()
    data = resp.json()

    _access_token_cache["token"] = data["access_token"]
    _access_token_cache["expires_at"] = time.time() + data["expires_in"] - 60

    new_refresh_token = data.get("refresh_token")
    if new_refresh_token and new_refresh_token != refresh_token:
        os.environ["QBO_REFRESH_TOKEN"] = new_refresh_token
        if _ENV_PATH:
            set_key(_ENV_PATH, "QBO_REFRESH_TOKEN", new_refresh_token)
            print("NOTE: QuickBooks issued a new refresh_token; saved to .env automatically.")
        else:
            print(
                "NOTE: QuickBooks issued a new refresh_token, but no .env file was "
                "found to save it to. Set it manually or the next run will fail:\n"
                f"  QBO_REFRESH_TOKEN={new_refresh_token}"
            )

    return _access_token_cache["token"]


def _get_access_token() -> str:
    if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
        return _access_token_cache["token"]
    return _refresh_access_token()


def qbo_query(sql_like_query: str) -> dict:
    """
    Runs a QuickBooks query. Example:
        qbo_query("select * from Bill")
        qbo_query("select * from PurchaseOrder")
    Returns the parsed JSON response.
    """
    realm_id = os.environ["QBO_REALM_ID"]
    token = _get_access_token()

    url = f"{SANDBOX_BASE_URL}/v3/company/{realm_id}/query"
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        params={"query": sql_like_query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

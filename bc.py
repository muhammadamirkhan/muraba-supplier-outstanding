"""Business Central read-only client.

OAuth 2.0 client credentials (S2S). BC online has no Basic auth. Secret comes
from st.secrets / env only -- never committed, never rendered into the page.
"""
import os

import requests

TENANT = "0f50122c-45ca-44b1-904f-26ef526945b4"
CLIENT_ID = "6bd60a85-d9ee-4f53-bc94-0b29d7264620"
COMPANY_ID = "140d7d38-cbae-ee11-a568-002248cc1e49"
COMPANY = "Company('Muraba%20Properties%20LLC')"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
SCOPE = "https://api.businesscentral.dynamics.com/.default"
BASE = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT}/Production"

TIMEOUT = 120


class BCError(RuntimeError):
    pass


# Local-dev only: the shared credentials note on the G: drive. Not present on
# Streamlit Cloud, where the secret must be set under Settings -> Secrets.
CRED_FILE = r"G:\My Drive\Upwork\Upwork\Muraba Properties\muraba_bc_api_credentials.txt"


def _from_cred_file():
    import re

    if not os.path.exists(CRED_FILE):
        return ""
    try:
        text = open(CRED_FILE, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    for pat in (r"^\s*Client secret\s*:\s*(.+?)\s*$",
                r"^\s*client_secret\s*=\s*(.+?)\s*$"):
        for m in re.finditer(pat, text, re.MULTILINE):
            v = m.group(1).strip().strip('"').strip("'")
            if v and not v.startswith("<") and "PASTE" not in v.upper():
                return v
    return ""


def _secret():
    """client secret from Streamlit secrets, else env, else the local cred file.

    Never logged, never rendered into the page.
    """
    try:
        import streamlit as st

        val = st.secrets.get("bc_client_secret", "")
        if val:
            return str(val).strip()
    except Exception:  # not running under Streamlit, or no secrets file
        pass
    val = os.environ.get("BC_CLIENT_SECRET", "").strip() or _from_cred_file()
    if not val:
        raise BCError(
            "No BC client secret. Set `bc_client_secret` in .streamlit/secrets.toml "
            "(local) or in Streamlit Cloud -> Settings -> Secrets, or export "
            "BC_CLIENT_SECRET."
        )
    return val


def get_token():
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": _secret(),
            "scope": SCOPE,
        },
        timeout=30,
    )
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        desc = (body.get("error_description") or r.text)[:200]
        hint = ""
        if "AADSTS7000222" in desc:
            hint = " -- the client secret has EXPIRED; issue a new one in Azure."
        elif "AADSTS7000215" in desc:
            hint = " -- wrong secret (make sure it's the Value, not the Secret ID)."
        elif "AADSTS700016" in desc:
            hint = " -- app registration not found in this tenant."
        raise BCError(f"Token request failed (HTTP {r.status_code}){hint}")
    return r.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def fetch_all(path, token=None, params=None):
    """GET an OData path, following @odata.nextLink until exhausted."""
    token = token or get_token()
    url = f"{BASE}/{path.lstrip('/')}"
    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + "&".join(f"{k}={v}" for k, v in params.items())
    rows, pages = [], 0
    while url:
        r = requests.get(url, headers=_headers(token), timeout=TIMEOUT)
        if r.status_code != 200:
            raise BCError(f"{path} -> HTTP {r.status_code}: {r.text[:200]}")
        j = r.json()
        rows.extend(j.get("value", []))
        url = j.get("@odata.nextLink")
        pages += 1
        if pages > 500:  # runaway guard
            raise BCError(f"{path}: stopped after 500 pages ({len(rows)} rows)")
    return rows


# ---- the feeds this dashboard needs ---------------------------------------

def vendor_ledger_entries(token=None):
    """Full AP subledger. 26 fixed fields; $select is ignored on this page."""
    return fetch_all(f"ODataV4/{COMPANY}/VendorLedgerEntries", token)


def posted_purchase_invoice_lines(token=None):
    """Invoice line descriptions, for the printable statement text columns."""
    return fetch_all(f"ODataV4/{COMPANY}/PostedPurchaseInvoiceLines", token)


def gl_entries_for_account(account_no, token=None):
    """GL entries on one account -- used for in-house sales commission (21014)."""
    return fetch_all(
        f"api/v2.0/companies({COMPANY_ID})/generalLedgerEntries",
        token,
        params={"$filter": f"accountNumber eq '{account_no}'"},
    )


def health(token=None):
    """Cheap liveness probe for the sidebar."""
    token = token or get_token()
    r = requests.get(
        f"{BASE}/ODataV4/{COMPANY}/VendorLedgerEntries?$top=1",
        headers=_headers(token),
        timeout=30,
    )
    return r.status_code == 200

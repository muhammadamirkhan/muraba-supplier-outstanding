"""Shared bootstrap for the tools. Run any of them from this folder or tools/.

The BC secret resolution lives in bc.py (env -> Streamlit secrets -> the
credentials note on G:), so nothing here handles secrets itself.
"""
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

import bc          # noqa: E402,F401
import mapping     # noqa: E402,F401
import transform   # noqa: E402,F401


def pull(token=None):
    """The three BC feeds the dashboard runs on."""
    token = token or bc.get_token()
    return (bc.vendor_ledger_entries(token),
            bc.posted_purchase_invoice_lines(token),
            bc.chart_of_accounts(token))

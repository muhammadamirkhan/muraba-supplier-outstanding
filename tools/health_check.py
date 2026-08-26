"""Is BC reachable and are the feeds intact?  python tools/health_check.py"""
from _common import bc

def main():
    print("token ...", end=" ")
    tok = bc.get_token()
    print("OK")
    feeds = [
        ("VendorLedgerEntries", bc.vendor_ledger_entries),
        ("PostedPurchaseInvoiceLines", bc.posted_purchase_invoice_lines),
        ("Chart_of_Accounts", bc.chart_of_accounts),
    ]
    ok = 0
    for name, fn in feeds:
        try:
            rows = fn(tok)
            print(f"  OK   {name:<30} {len(rows):>7,} rows")
            ok += 1
        except bc.BCError as e:
            print(f"  FAIL {name:<30} {e}")
    print(f"\n{ok}/{len(feeds)} feeds healthy")

if __name__ == "__main__":
    main()

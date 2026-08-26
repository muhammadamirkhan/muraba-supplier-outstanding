"""Audit trail for one vendor's category tag.

    python tools/trace_tag.py VLLC0360

Shows every invoice line, the G/L account each posts to, the totals per
account, and how that resolves to the tag on the dashboard -- plus the BC
screens to verify it in.
"""
import collections
import sys

from _common import bc, mapping, transform


def main(vendor):
    tok = bc.get_token()
    lines = bc.posted_purchase_invoice_lines(tok)
    coa = bc.chart_of_accounts(tok)
    vle = bc.vendor_ledger_entries(tok)

    name = next(((e.get("Vendor_Name") or "").strip() for e in vle
                 if e.get("Vendor_No") == vendor and (e.get("Vendor_Name") or "").strip()), "?")
    mine = [l for l in lines if l.get("Buy_from_Vendor_No") == vendor]
    print(f"VENDOR {vendor}  =  {name}")
    print(f"posted purchase invoice lines: {len(mine)}\n")

    print("STEP 1 - invoice lines and the G/L account each posts to")
    print(f'{"Document_No":<14}{"Type":<14}{"G/L":<8}{"Amount":>14}  Description')
    print("-" * 104)
    for l in sorted(mine, key=lambda x: (x.get("Document_No") or ""))[:14]:
        print(f'{(l.get("Document_No") or ""):<14}{(l.get("Type") or "-"):<14}'
              f'{(l.get("No") or ""):<8}{(l.get("Amount") or 0):>14,.2f}  {(l.get("Description") or "")[:42]}')
    if len(mine) > 14:
        print(f"  ... {len(mine) - 14} more")

    print("\nSTEP 2 - totals per account, named from the Chart of Accounts")
    spend = collections.defaultdict(float)
    for l in mine:
        if (l.get("Type") or "").strip() == "G/L Account" and l.get("No"):
            spend[l["No"]] += l.get("Amount") or 0
    tot = sum(abs(v) for v in spend.values()) or 1
    print(f'{"G/L":<8}{"Chart of Accounts name":<46}{"Amount":>15}{"share":>8}   note')
    print("-" * 98)
    for a, amt in sorted(spend.items(), key=lambda x: -abs(x[1])):
        note = "mechanics -> skipped" if a in mapping.MECHANICS_ACCOUNTS else ""
        print(f'{a:<8}{coa.get(a, "?")[:45]:<46}{amt:>15,.2f}{100 * abs(amt) / tot:7.1f}%   {note}')

    if vendor in mapping.CLIENT_CATEGORY_OVERRIDES:
        print(f'\nCLIENT INSTRUCTION -> TAG = "{mapping.CLIENT_CATEGORY_OVERRIDES[vendor]}"')
    else:
        cat, acct = transform._derive_category(spend, coa)
        print(f'\nSTEP 3 - dominant non-mechanics account = {acct}  "{coa.get(acct)}"')
        print(f'STEP 4 - project qualifier trimmed  ->  TAG = "{cat}"')

    print("\n--- verify in the BC web client ---")
    print(f"  1. Alt+Q 'Vendors' -> {vendor} {name}")
    print("  2. Related > Purchases > Ledger Entries      (the dashboard amounts)")
    print(f"  3. Alt+Q 'Posted Purchase Invoices', filter Buy-from Vendor No. = {vendor}")
    print("     open one -> Lines -> column 'No.' is the G/L account above")
    print("  4. Alt+Q 'Chart of Accounts' -> that account -> its Name is the tag")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "VLLC0360")

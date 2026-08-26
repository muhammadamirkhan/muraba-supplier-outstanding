"""Raw BC ledger entries for one vendor -- the ground truth behind its row.

    python tools/vendor_ledger.py VLLC0394
    python tools/vendor_ledger.py "Al Hai"        # name fragment also works
"""
import sys

from _common import bc, transform


def main(query):
    vle = bc.vendor_ledger_entries(bc.get_token())
    ents = [e for e in vle if e.get("Vendor_No") == query] or \
           [e for e in vle if query.lower() in (e.get("Vendor_Name") or "").lower()]
    if not ents:
        print(f"no vendor matching {query!r}")
        return
    no, nm = ents[0].get("Vendor_No"), ents[0].get("Vendor_Name")
    print(f"=== {nm}  ({no})  {len(ents)} entries ===")
    print(f'{"Posting":<12}{"DocType":<13}{"DocNo":<14}{"Amount_LCY":>14}'
          f'{"Debit":>12}{"Credit":>12}{"Remaining":>13}  Open')
    print("-" * 104)
    for e in sorted(ents, key=lambda x: str(x.get("Posting_Date"))):
        print(f'{str(e.get("Posting_Date"))[:10]:<12}{(e.get("Document_Type") or "-"):<13}'
              f'{(e.get("Document_No") or ""):<14}{(e.get("Amount_LCY") or 0):>14,.2f}'
              f'{(e.get("Debit_Amount_LCY") or 0):>12,.2f}{(e.get("Credit_Amount_LCY") or 0):>12,.2f}'
              f'{(e.get("Remaining_Amt_LCY") or 0):>13,.2f}  {e.get("Open")}')
    m = transform._money(ents)
    print(f'\ndashboard shows -> invoiced {m["invoiced_aed"]:,.2f} | '
          f'paid {m["paid_aed"]:,.2f} | outstanding {m["outstanding_aed"]:,.2f}')
    print("(invoiced/paid come from the SIGNED Amount_LCY, not the Debit/Credit "
          "columns -- BC books some reversals with negative debits AND credits.)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "VLLC0394")

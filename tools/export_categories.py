"""Write supplier_categories.csv -- every supplier, its tag, and the evidence.

    python tools/export_categories.py
"""
import collections
import csv
import os

from _common import APP, bc, mapping, transform, pull

OUT = os.path.join(APP, "supplier_categories.csv")


def main():
    vle, lines, coa = pull()
    DATA, _PERF, _LED, TXNS, _diag = transform.build(vle, lines, coa)
    spend = transform._vendor_spend_by_account(lines)

    no_by_name = {}
    for e in vle:
        nm = (e.get("Vendor_Name") or "").strip()
        if nm and nm in DATA:
            no_by_name[nm] = e.get("Vendor_No")

    rows = []
    for name, v in DATA.items():
        no = no_by_name.get(name, "")
        accts = spend.get(no, {})
        _cat, acct_no = transform._derive_category(accts, coa)
        if no in mapping.CLIENT_CATEGORY_OVERRIDES:
            basis, acct_no, share = "Client instruction", "", ""
        elif not accts:
            basis, acct_no, share = "No purchase invoice lines in BC (journal-only)", "", ""
        else:
            tot = sum(abs(a) for a in accts.values()) or 1
            basis = "Dominant G/L cost account"
            share = f"{100 * abs(accts.get(acct_no, 0)) / tot:.0f}%"
        rows.append({
            "Vendor No": no,
            "Supplier Name": name,
            "Category": v["category"],
            "Category basis": basis,
            "G/L account": acct_no or "",
            "G/L account name": coa.get(acct_no, "") if acct_no else "",
            "Share of spend": share,
            "Currency": v["currency"],
            "Invoiced (AED)": round(v["invoiced_aed"], 2),
            "Paid (AED)": round(v["paid_aed"], 2),
            "Outstanding (AED)": round(v["outstanding_aed"], 2),
        })

    rows.sort(key=lambda r: (r["Category"] == mapping.UNCATEGORISED, r["Category"],
                             -abs(r["Outstanding (AED)"]), r["Supplier Name"]))
    with open(OUT, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {OUT}\n{len(rows)} suppliers\n")
    cats = collections.Counter(r["Category"] for r in rows)
    print(f'{"category":<44}{"suppliers":>10}{"outstanding":>16}')
    print("-" * 70)
    for c, n in cats.most_common():
        tot = sum(r["Outstanding (AED)"] for r in rows if r["Category"] == c)
        print(f"{c[:43]:<44}{n:>10}{tot:>16,.0f}")


if __name__ == "__main__":
    main()

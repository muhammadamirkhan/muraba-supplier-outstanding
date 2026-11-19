"""Vendor list for Usman's category segregation, live from Business Central.

    python tools/export_vendor_categories.py

Produces an .xlsx with a blank, dropdown-validated "Category (Usman)" column:

  Vendors with Outstanding  the ask -- every vendor carrying a balance today
  All Vendors               everyone with ledger activity, so vendors that fall
                            due later are not a second round trip
  Category List             the picklist both sheets validate against; extend it
                            there and both dropdowns follow
  Notes                     what each column means and how it was derived

"Category (app)" is what the dashboard derives today from the vendor's dominant
G/L cost account. It travels as a starting point and as evidence, NOT as an
answer -- Usman's column overrides it.
"""
import datetime as dt
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from _common import APP, mapping, transform, pull

OUT = os.path.join(APP, "Vendor Categories - for Usman.xlsx")

# Usman's three, plus the tail his "etc." implied. He extends this on the
# Category List sheet; both dropdowns read the named range, not this list.
CATEGORIES = [
    "Construction", "Design Supervision", "Vendor Marketing", "Consultancy",
    "Fit-out", "Legal & Professional", "Facility Management", "IT & Software",
    "Government & Authority", "Brokerage & Commission", "Other",
]
SPARE_ROWS = 40  # headroom in the named range for categories Usman adds

HEAD = ["Vendor No", "Vendor Name", "Category (Usman)", "Category (app, BC-derived)",
        "Basis", "G/L account", "G/L account name", "Share of spend",
        "Outstanding (AED)", "Invoiced (AED)", "Paid (AED)", "Open items",
        "Oldest open (days)", "Currency"]
WIDTHS = [11, 46, 22, 30, 34, 12, 30, 12, 17, 17, 17, 10, 14, 10]

MONEY = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
BLUE, GREY, FILLME = "4472C4", "F2F5FA", "FFF4CE"
THIN = Side(style="thin", color="D5DCE8")


def _sheet(wb, title, rows, note):
    ws = wb.create_sheet(title)
    ws["A1"] = note
    ws["A1"].font = Font(size=10, italic=True, color="5A6B86")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HEAD))
    ws["A1"].alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30

    for c, h in enumerate(HEAD, 1):
        cell = ws.cell(row=2, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 30

    for r, row in enumerate(rows, 3):
        for c, key in enumerate(HEAD, 1):
            cell = ws.cell(row=r, column=c, value=row.get(key))
            cell.border = Border(bottom=THIN)
            if key.endswith("(AED)"):
                cell.number_format = MONEY
            if key == "Category (Usman)":
                cell.fill = PatternFill("solid", fgColor=FILLME)
            elif c > 3:
                cell.fill = PatternFill("solid", fgColor=GREY)

    last = len(rows) + 2
    if rows:
        dv = DataValidation(type="list", formula1="=Categories", allow_blank=True,
                            showDropDown=False)
        dv.errorTitle = "Not on the category list"
        dv.error = "Pick from the list, or add the category on the Category List sheet first."
        ws.add_data_validation(dv)
        dv.add("C3:C%d" % last)
        ws.auto_filter.ref = "A2:%s%d" % (get_column_letter(len(HEAD)), last)
    ws.freeze_panes = "D3"
    for c, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    return ws


def main():
    vle, lines, coa = pull()
    DATA, _PERF, _LED, _TXNS, diag = transform.build(vle, lines, coa)
    spend = transform._vendor_spend_by_account(lines)

    no_by_name = {}
    for e in vle:
        nm = (e.get("Vendor_Name") or "").strip()
        if nm and nm in DATA:
            no_by_name[nm] = e.get("Vendor_No")

    asof = dt.date.today()
    oldest = {}
    for e in vle:
        if not e.get("Open") or not transform._plausible(e):
            continue
        nm = (e.get("Vendor_Name") or "").strip()
        d = str(e.get("Posting_Date") or "")[:10]
        if not (nm and d):
            continue
        try:
            age = (asof - dt.date.fromisoformat(d)).days
        except ValueError:
            continue
        oldest[nm] = max(oldest.get(nm, 0), age)

    rows = []
    for name, v in DATA.items():
        no = no_by_name.get(name, "")
        accts = spend.get(no, {})
        _cat, acct = transform._derive_category(accts, coa)
        if no in mapping.CLIENT_CATEGORY_OVERRIDES:
            basis, acct, share = "Client instruction", "", ""
        elif not accts:
            basis, acct, share = "No purchase invoice lines in BC (journal-only)", "", ""
        else:
            tot = sum(abs(a) for a in accts.values()) or 1
            basis = "Dominant G/L cost account"
            share = "%.0f%%" % (100 * abs(accts.get(acct, 0)) / tot)
        rows.append({
            "Vendor No": no, "Vendor Name": name, "Category (Usman)": "",
            "Category (app, BC-derived)": v["category"], "Basis": basis,
            "G/L account": acct or "",
            "G/L account name": coa.get(acct, "") if acct else "",
            "Share of spend": share,
            "Outstanding (AED)": round(v["outstanding_aed"], 2),
            "Invoiced (AED)": round(v["invoiced_aed"], 2),
            "Paid (AED)": round(v["paid_aed"], 2),
            "Open items": len(v["opens"]),
            "Oldest open (days)": oldest.get(name, ""),
            "Currency": v["currency"],
        })

    outs = sorted([r for r in rows if r["Outstanding (AED)"] > 1],
                  key=lambda r: -r["Outstanding (AED)"])
    allv = sorted(rows, key=lambda r: (-r["Outstanding (AED)"], r["Vendor Name"]))
    tot = sum(r["Outstanding (AED)"] for r in outs)
    stamp = asof.isoformat()

    wb = Workbook()
    wb.remove(wb.active)

    cl = wb.create_sheet("Category List")
    cl["A1"] = "Category list"
    cl["A1"].font = Font(bold=True, size=12, color="1F3864")
    cl["A2"] = ("Both vendor sheets validate their Category column against this list. Add a "
                "category here first and the dropdowns pick it up automatically. One per row, "
                "no blank rows in between.")
    cl["A2"].font = Font(size=10, italic=True, color="5A6B86")
    cl.merge_cells("A2:D2")
    cl["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    cl.row_dimensions[2].height = 30
    cl.column_dimensions["A"].width = 34
    for i, c in enumerate(CATEGORIES, 4):
        cell = cl.cell(row=i, column=1, value=c)
        cell.border = Border(bottom=THIN)
    wb.defined_names.add(DefinedName(
        "Categories",
        attr_text="'Category List'!$A$4:$A$%d" % (3 + len(CATEGORIES) + SPARE_ROWS)))

    _sheet(wb, "Vendors with Outstanding", outs,
           "Every vendor carrying a balance in Business Central as at %s — %d vendors, "
           "AED %s outstanding. Fill column C (yellow). Column D is what the dashboard derives "
           "from that vendor's own G/L postings: evidence, not an answer."
           % (stamp, len(outs), format(round(tot), ",")))

    _sheet(wb, "All Vendors", allv,
           "Every vendor with ledger activity in BC (%d), balance or not — so vendors that fall "
           "due later are already categorised. Same columns; fill column C." % len(allv))

    nt = wb.create_sheet("Notes")
    nt.column_dimensions["A"].width = 30
    nt.column_dimensions["B"].width = 104
    nt["A1"], nt["B1"] = "Column", "What it is"
    for c in ("A1", "B1"):
        nt[c].font = Font(bold=True, color="FFFFFF")
        nt[c].fill = PatternFill("solid", fgColor=BLUE)
    notes = [
        ("Vendor No", "Business Central Vendor No. The stable key — names change, this does not. "
                      "Please keep the column intact when the file comes back."),
        ("Vendor Name", "BC Vendor Name, verbatim. Not cleaned or shortened."),
        ("Category (Usman)", "Blank, for you to fill. This is the column that will drive the "
                             "dashboard once returned."),
        ("Category (app, BC-derived)", "What the dashboard shows today: the name of the G/L cost "
                                       "account most of that vendor's invoice lines post to. "
                                       "Where it disagrees with your view, yours wins."),
        ("Basis", "How column D was arrived at. 'No purchase invoice lines in BC' means the "
                  "vendor was only ever journal-posted, so BC offers no cost account to read — "
                  "those are the ones most worth your eye."),
        ("G/L account / name", "The account column D was read from, so the derivation can be "
                               "checked against BC."),
        ("Share of spend", "How much of that vendor's invoiced value sits on that one account. "
                           "A low share means the vendor spans several accounts."),
        ("Outstanding (AED)", "-sum(Remaining Amount LCY) — the same basis as BC's Vendor Balance "
                              "and Aged Accounts Payable. Reconciles to BC exactly."),
        ("Invoiced / Paid (AED)", "From the signed Amount (LCY): charges less credit memos, and "
                                  "settlements. Covers the whole ledger, not one project."),
        ("Open items", "Count of entries BC still flags as Open for that vendor."),
        ("Oldest open (days)", "Age of the oldest open entry, from its posting date."),
    ]
    for r, (a, b) in enumerate(notes, 2):
        nt.cell(row=r, column=1, value=a).font = Font(bold=True, size=10)
        cell = nt.cell(row=r, column=2, value=b)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        nt.row_dimensions[r].height = 30
    sr = len(notes) + 3
    nt.cell(row=sr, column=1, value="Source").font = Font(bold=True, size=10)
    cell = nt.cell(row=sr, column=2,
                   value="Live Business Central (VendorLedgerEntries + "
                         "PostedPurchaseInvoiceLines + Chart of Accounts), pulled %s. "
                         "%s ledger entries, %s invoice lines. Nothing in this file is typed "
                         "by hand or carried over from any earlier report."
                         % (stamp, format(diag["entries_used"], ","), format(len(lines), ",")))
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    nt.row_dimensions[sr].height = 44

    wb.save(OUT)
    print("wrote %s" % OUT)
    print("  Vendors with Outstanding : %d  (AED %s)" % (len(outs), format(round(tot), ",")))
    print("  All Vendors              : %d" % len(allv))
    print("  app says Uncategorised   : %d" % sum(
        1 for r in allv if r["Category (app, BC-derived)"] == mapping.UNCATEGORISED))
    return 0


if __name__ == "__main__":
    sys.exit(main())

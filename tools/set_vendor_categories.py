"""Write Finance's vendor categories into BC's Territory Code field.

    python tools/set_vendor_categories.py            # dry run, changes nothing
    python tools/set_vendor_categories.py --apply    # writes to Business Central

Reads the returned category workbook, maps each category to its Territory code
and PATCHes the vendor master over OData. This is the ONLY script in the repo
that writes to BC; everything else is read-only.

Prerequisite, and it cannot be done from here: the Territory codes must exist
in BC first (Setup -> Territories). The Territory table is not a published
OData service, so it cannot be created over the API -- someone has to add the
seven rows in the BC UI once. Until then every PATCH fails with
Internal_InvalidTableRelation and nothing is changed. Run the dry run; it
reports exactly which codes are missing.

Safety: a dry run by default, an explicit --apply to write, If-Match on every
PATCH so a vendor edited since the read is skipped rather than clobbered, and a
printed before/after for each vendor touched.
"""
import argparse
import collections
import json
import os
import sys

import requests
from openpyxl import load_workbook

from _common import APP, bc, mapping  # noqa: F401

DEFAULT_BOOK = os.path.join(APP, "Vendor Categories - for Usman.xlsx")
SHEETS = ("Vendors with Outstanding", "All Vendors")
COL_NO, COL_NAME, COL_CAT = 1, 2, 3

# Label -> Territory code. The inverse of mapping.TERRITORY_CATEGORY, so the
# two can never drift: the dashboard reads the code back through that map.
CODE_FOR = {label: code for code, label in mapping.TERRITORY_CATEGORY.items()}


def read_book(path):
    """-> {vendor_no: (name, category)} from whichever sheets carry entries."""
    wb = load_workbook(path, data_only=True)
    want, seen = {}, collections.Counter()
    for sheet in SHEETS:
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        for r in range(3, ws.max_row + 1):
            no = str(ws.cell(row=r, column=COL_NO).value or "").strip()
            cat = str(ws.cell(row=r, column=COL_CAT).value or "").strip()
            name = str(ws.cell(row=r, column=COL_NAME).value or "").strip()
            if not (no and cat):
                continue
            if no in want and want[no][1] != cat:
                print("  ! %s has two different categories across sheets: %r / %r"
                      % (no, want[no][1], cat))
            want[no] = (name, cat)
            seen[sheet] += 1
    for s, n in seen.items():
        print("  %-26s %d categorised row(s)" % (s, n))
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=DEFAULT_BOOK)
    ap.add_argument("--apply", action="store_true", help="actually write to BC")
    args = ap.parse_args()

    print("reading %s" % args.book)
    want = read_book(args.book)
    if not want:
        print("nothing categorised in the workbook - nothing to do")
        return 1

    unknown = sorted({c for _n, c in want.values() if c not in CODE_FOR})
    if unknown:
        print("\nFAIL: categories with no Territory code in mapping.TERRITORY_CATEGORY:")
        for c in unknown:
            print("   %r" % c)
        print("\nAdd them to mapping.TERRITORY_CATEGORY (code -> label) and re-run.")
        return 1

    token = bc.get_token()
    H = dict(bc._headers(token))
    H["Content-Type"] = "application/json"
    base = bc.BASE + "/ODataV4/%s/workflowVendors" % bc.COMPANY

    print("\nreading vendor master from BC ...")
    rows = bc.fetch_all("ODataV4/%s/workflowVendors" % bc.COMPANY, token)
    by_no = {(r.get("number") or "").strip(): r for r in rows}
    print("  %d vendors" % len(by_no))

    plan, missing, already = [], [], []
    for no, (name, cat) in sorted(want.items()):
        v = by_no.get(no)
        if not v:
            missing.append((no, name))
            continue
        code = CODE_FOR[cat]
        now = (v.get("territoryCode") or "").strip().upper()
        if now == code:
            already.append((no, name, cat))
        else:
            plan.append((no, v, name, cat, now, code))

    print("\n%d to write, %d already correct, %d not found in BC"
          % (len(plan), len(already), len(missing)))
    for no, name in missing:
        print("   not in BC: %-11s %s" % (no, name))

    print("\n%-11s %-44s %-24s %s" % ("Vendor No", "Vendor Name", "Category", "Territory Code"))
    print("-" * 104)
    for no, _v, name, cat, now, code in plan:
        print("%-11s %-44s %-24s %s%s"
              % (no, name[:44], cat, code, ("   (was %s)" % now) if now else ""))

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply to write to BC.")
        print("Territory codes this needs to exist in BC (Setup -> Territories):")
        for code in sorted({c for *_x, c in plan}):
            print("   %-11s %s" % (code, mapping.TERRITORY_CATEGORY[code]))
        return 0

    ok = fail = 0
    for no, v, name, cat, _now, code in plan:
        h = dict(H)
        h["If-Match"] = v.get("@odata.etag")
        url = "%s(%s)" % (base, v.get("id"))
        r = requests.patch(url, headers=h, data=json.dumps({"territoryCode": code}), timeout=90)
        if r.status_code in (200, 204):
            ok += 1
            print("  OK   %-11s %-40s -> %s" % (no, name[:40], code))
        else:
            fail += 1
            msg = ""
            try:
                msg = r.json()["error"]["message"][:150]
            except Exception:
                msg = r.text[:150]
            print("  FAIL %-11s %-40s -> %s  [%s] %s" % (no, name[:40], code, r.status_code, msg))

    print("\nwritten %d, failed %d" % (ok, fail))
    if fail:
        print("Internal_InvalidTableRelation means the Territory code does not exist in BC yet.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

"""Test each of the four 'BC does not hold it' claims against live BC."""
import collections
import os
import sys

from _common import bc, transform

tok = bc.get_token()
CO = "Company('Muraba%20Properties%20LLC')"

print("=" * 78)
print("CLAIM 1  agents are not vendors / commission has no agent dimension")
print("=" * 78)
vle = bc.vendor_ledger_entries(tok)
names = {(e.get("Vendor_Name") or "").strip() for e in vle}
for agent in ("Abhilash", "Eoghan", "Marius"):
    hits = [n for n in names if agent.lower() in n.lower()]
    print(f"  vendor named like {agent!r}: {hits or 'NONE'}")

# Is GL 21014 reachable, and does it carry dimensions?
try:
    gl = bc.fetch_all(f"ODataV4/{CO}/G_LEntries", tok,
                      params={"$filter": "G_L_Account_No eq '21014'"})
    print(f"\n  G_LEntries on 21014: {len(gl)} rows")
    if gl:
        print("  fields:", sorted(gl[0].keys()))
        dims = collections.Counter()
        for r in gl:
            for k in ("Global_Dimension_1_Code", "Global_Dimension_2_Code",
                      "Shortcut_Dimension_1_Code", "Shortcut_Dimension_2_Code"):
                v = (r.get(k) or "").strip()
                if v:
                    dims[(k, v)] += 1
        print("  populated dimension codes:", dict(list(dims.items())[:10]) or "NONE")
        ds = [r.get("Dimension_Set_ID") for r in gl if r.get("Dimension_Set_ID")]
        print(f"  entries with a Dimension_Set_ID: {len(ds)} of {len(gl)}")
        if ds:
            sample = ds[0]
            try:
                dse = bc.fetch_all(f"ODataV4/{CO}/DimensionSetEntries", tok,
                                   params={"$filter": f"Dimension_Set_ID eq {sample}"})
                print(f"  dimensions on set {sample}:",
                      [(d.get("Dimension_Code"), d.get("Dimension_Value_Code")) for d in dse])
            except Exception as e:
                print("  DimensionSetEntries lookup failed:", str(e)[:120])
except Exception as e:
    print("  G_LEntries failed:", str(e)[:160])

print()
print("=" * 78)
print("CLAIM 2  Closed at Date / Closed by Entry No are not published")
print("=" * 78)
print("  VendorLedgerEntries fields:")
print("   ", sorted(vle[0].keys()))
for f in ("Closed_at_Date", "Closed_by_Entry_No", "Closed_by_Amount", "Applies_to_ID"):
    print(f"   {f}: {'PRESENT' if f in vle[0] else 'absent'}")
# any other feed that might carry it?
for svc in ("DetailedVendorLedgEntry", "Detailed_Vendor_Ledg_Entry",
            "Power_BI_Vendor_Ledger_Entries", "VendorLedgerEntriesExcel"):
    try:
        r = bc.fetch_all(f"ODataV4/{CO}/{svc}?$top=1", tok)
        print(f"   {svc}: HTTP 200, fields = {sorted(r[0].keys()) if r else '(empty)'}")
    except Exception as e:
        print(f"   {svc}: {str(e)[:70]}")

print()
print("=" * 78)
print("CLAIM 3  no contract/variation classification on AP documents")
print("=" * 78)
lines = bc.posted_purchase_invoice_lines(tok)
print(f"  {len(lines):,} invoice lines; dimension columns present:",
      [k for k in lines[0] if "Dimension" in k])
for k in ("Shortcut_Dimension_1_Code", "Shortcut_Dimension_2_Code"):
    vals = collections.Counter((l.get(k) or "").strip() for l in lines)
    filled = {v: c for v, c in vals.items() if v}
    print(f"  {k}: {len(filled)} distinct values populated -> {dict(list(filled.items())[:8])}")
jobs = collections.Counter((l.get("Job_No") or "").strip() for l in lines)
print(f"  Job_No populated on {sum(c for v, c in jobs.items() if v)} lines;",
      f"values: {dict(list({v: c for v, c in jobs.items() if v}.items())[:6])}")
vary = [l for l in lines if any(w in (l.get("Description") or "").lower()
        for w in ("variation", "vo-", "v.o"))]
print(f"  lines whose DESCRIPTION mentions a variation: {len(vary)} (text only, not a field)")

print()
print("=" * 78)
print("CLAIM 4  invalid-date entries are matched pairs with nil balance")
print("=" * 78)
bad = [e for e in vle if not transform._plausible(e)]
print(f"  {len(bad)} entries fail the date check")
byv = collections.defaultdict(list)
for e in bad:
    byv[(e.get("Vendor_No"), e.get("Vendor_Name"))].append(e)
for (no, nm), ents in byv.items():
    amt = sum(e.get("Amount_LCY") or 0 for e in ents)
    rem = sum(e.get("Remaining_Amt_LCY") or 0 for e in ents)
    opens = sum(1 for e in ents if e.get("Open"))
    print(f"   {no} {nm[:38]:<38} n={len(ents)} sum(Amount)={amt:>12,.2f} "
          f"sum(Remaining)={rem:>10,.2f} open={opens}")
    for e in ents:
        print(f"        {e.get('Posting_Date')}  {e.get('Document_No')}  "
              f"amt={e.get('Amount_LCY'):>12,.2f}")

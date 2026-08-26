"""Can commission PAID be attributed per agent from BC after all?

Route to test:  G/L 21014 -> Dimension Set -> UNITNAME -> BookingAgreement.Sales_Person_Name
"""
import collections
import os
import sys

from _common import bc

tok = bc.get_token()
CO = "Company('Muraba%20Properties%20LLC')"

gl = bc.fetch_all(f"ODataV4/{CO}/G_LEntries", tok,
                  params={"$filter": "G_L_Account_No eq '21014'"})
print(f"G/L 21014: {len(gl)} entries, "
      f"net {sum((r.get('Debit_Amount') or 0) - (r.get('Credit_Amount') or 0) for r in gl):,.2f}")

# ---- dimension sets on those entries ---------------------------------------
sets = sorted({r.get("Dimension_Set_ID") for r in gl if r.get("Dimension_Set_ID")})
print(f"distinct dimension sets: {len(sets)}")
dse = bc.fetch_all(f"ODataV4/{CO}/DimensionSetEntries", tok)
print(f"DimensionSetEntries rows: {len(dse):,}")
bysid = collections.defaultdict(dict)
for d in dse:
    bysid[d.get("Dimension_Set_ID")][d.get("Dimension_Code")] = d.get("Dimension_Value_Code")

codes = collections.Counter()
for s in sets:
    for k in bysid.get(s, {}):
        codes[k] += 1
print("dimension codes present on 21014 sets:", dict(codes))

unit_amt = collections.defaultdict(float)
no_unit = 0.0
for r in gl:
    amt = (r.get("Debit_Amount") or 0) - (r.get("Credit_Amount") or 0)
    u = bysid.get(r.get("Dimension_Set_ID"), {}).get("UNITNAME")
    if u:
        unit_amt[u] += amt
    else:
        no_unit += amt
print(f"\nattributable to a UNITNAME: {sum(unit_amt.values()):,.2f} across {len(unit_amt)} units")
print(f"no UNITNAME on the entry     : {no_unit:,.2f}")

# ---- units -> agent ---------------------------------------------------------
try:
    ba = bc.fetch_all(f"ODataV4/{CO}/BookingAgreement", tok)
    print(f"\nBookingAgreement rows: {len(ba)}")
    print("fields:", sorted(ba[0].keys())[:26])
    unit_f = next((k for k in ba[0] if "Unit" in k and "Name" in k), None)
    agent_f = next((k for k in ba[0] if "Sales_Person" in k or "Salesperson" in k), None)
    print(f"unit field = {unit_f!r}   agent field = {agent_f!r}")
    if unit_f and agent_f:
        u2a = {}
        for r in ba:
            u = (r.get(unit_f) or "").strip()
            a = (r.get(agent_f) or "").strip()
            if u and a:
                u2a[u] = a
        print(f"units with an agent: {len(u2a)}  sample: {list(u2a.items())[:4]}")
        per_agent = collections.defaultdict(float)
        matched = unmatched = 0.0
        for u, amt in unit_amt.items():
            a = u2a.get(u)
            if a:
                per_agent[a] += amt
                matched += amt
            else:
                unmatched += amt
        print(f"\nCOMMISSION PAID PER AGENT (G/L 21014 via UNITNAME -> BookingAgreement):")
        for a, v in sorted(per_agent.items(), key=lambda x: -abs(x[1])):
            print(f"   {a[:38]:<38} {v:>14,.2f}")
        print(f"   {'unit not on a booking agreement':<38} {unmatched:>14,.2f}")
        print(f"   {'entry carries no unit':<38} {no_unit:>14,.2f}")
        print(f"\n   attributable share: {100*matched/(matched+unmatched+no_unit or 1):.1f}%")
except Exception as e:
    print("BookingAgreement failed:", str(e)[:200])

# ---- is commission EARNED anywhere in BC? ----------------------------------
print("\n" + "=" * 70)
print("Is commission EARNED (accrued but unpaid) anywhere in BC?")
print("=" * 70)
deb = sum(r.get("Debit_Amount") or 0 for r in gl)
cred = sum(r.get("Credit_Amount") or 0 for r in gl)
print(f"  21014 debits {deb:,.2f} | credits {cred:,.2f}")
print("  A payables ACCRUAL would show as credits sitting open on this account.")
print(f"  credit share: {100*cred/(deb+cred or 1):.1f}%  -> "
      f"{'looks like an accrual account' if cred > deb*0.2 else 'looks like a payment/clearing account'}")

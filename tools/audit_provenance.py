"""Prove every figure on the dashboard traces to live Business Central.

    python tools/audit_provenance.py

Exits non-zero if anything on the page could come from somewhere other than BC,
or if a derived figure is not disclosed as such on the page. Run this whenever
the data rules change, and before telling anyone the dashboard is 100% BC.
"""
import io
import json
import os
import re
import sys

from _common import APP, bc, mapping, transform, pull  # noqa: F401

FAILS = []


def check(ok, label, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  -- " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


def head(n, title):
    print("\n" + "=" * 78)
    print("%d. %s" % (n, title))
    print("=" * 78)


def main():
    # ---------------------------------------------------------------- code
    head(1, "SOURCE CODE: can the app read anything other than BC?")
    # Genuine file reads only -- a bare `load(` is the app's own cache function.
    reads = re.compile(r"\b(?:open|read_text|read_csv|read_excel|json\.load|pickle\.load)\s*\(")
    # Two reads are legitimate and neither carries figures:
    #   TEMPLATE  -> template.html, the layout
    #   CRED_FILE -> the local credentials note, a secret
    ALLOWED = ("TEMPLATE", "CRED_FILE")
    for name in ("app.py", "bc.py", "transform.py", "mapping.py"):
        src = io.open(os.path.join(APP, name), encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        offenders = []
        for m in reads.finditer(code):
            ctx = code[max(0, m.start() - 90):m.end() + 60]
            if not any(a in ctx for a in ALLOWED):
                offenders.append(code[max(0, m.start() - 30):m.end() + 30].replace("\n", " ").strip())
        check(not offenders, "%s reads no data file" % name, " | ".join(offenders[:2]))

    data_files = [f for f in os.listdir(APP)
                  if f.endswith((".csv", ".json", ".xlsx", ".xlsm"))
                  and f != "supplier_categories.csv"]  # a generated OUTPUT, never read
    check(not data_files, "no readable data files in the app folder", ", ".join(data_files))

    # ---------------------------------------------------------------- template
    head(2, "TEMPLATE: stale provenance claims or hardcoded money?")
    tpl = io.open(os.path.join(APP, "template.html"), encoding="utf-8").read()
    for phrase in ("supplier-folder", "3.6725", "at indicative rates",
                   "Statement of Account files", "Statement of Account register"):
        check(phrase not in tpl, "no stale claim %r" % phrase)
    # Money on this page is always comma-grouped; account numbers are not.
    # Strip rgb()/rgba() first -- CSS colours are comma-grouped triples too.
    css_free = re.sub(r"rgba?\([^)]*\)", "", tpl)
    money = re.findall(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b", css_free)
    check(not money, "no hardcoded amounts", ", ".join(money[:5]))

    # ---------------------------------------------------------------- live
    head(3, "LIVE PULL: every rendered value reconciles to BC")
    vle, lines, coa = pull()
    print("  pulled %s ledger entries, %s invoice lines, %s accounts"
          % (format(len(vle), ","), format(len(lines), ","), format(len(coa), ",")))
    DATA, PERF, LEDGERS, diag = transform.build(vle, lines, coa)

    # recompute balances straight from the raw feed, bypassing transform
    raw = {}
    for e in vle:
        if transform._plausible(e):
            raw[e.get("Vendor_No")] = raw.get(e.get("Vendor_No"), 0) - (e.get("Remaining_Amt_LCY") or 0)
    name_no = {}
    for e in vle:
        nm = (e.get("Vendor_Name") or "").strip()
        if nm in DATA:
            name_no[nm] = e.get("Vendor_No")
    bad = [n for n, v in DATA.items()
           if n in name_no and abs((v["outstanding_aed"] or 0) - raw.get(name_no[n], 0)) > 0.01]
    check(not bad, "Outstanding == -sum(Remaining Amount LCY), recomputed from raw",
          "%d differ: %s" % (len(bad), bad[:3]))

    ident = [n for n, v in DATA.items()
             if abs((v["invoiced_aed"] or 0) - (v["paid_aed"] or 0) - (v["outstanding_aed"] or 0)) > 1]
    check(not ident, "Invoiced - Paid = Outstanding, every supplier", str(ident[:3]))

    neg = [n for n, v in DATA.items() if v["invoiced_aed"] < 0 or v["paid_aed"] < 0]
    check(not neg, "no negative Invoiced or Paid", str(neg[:3]))

    blob = json.dumps(DATA)
    check(blob.count(":-0.0,") + blob.count(":-0,") == 0, "no signed-zero in the payload")

    bc_names = {(e.get("Vendor_Name") or "").strip() for e in vle}
    notbc = [n for n in DATA
             if n not in bc_names and not re.search(r"\(VLLC\d+\)$", n)
             and not n.startswith("Vendor ")]
    check(not notbc, "every supplier name is a BC Vendor Name", str(notbc[:3]))

    acct_names = {mapping.clean_category(v) for v in coa.values()}
    allowed = acct_names | {mapping.UNCATEGORISED} | set(mapping.CLIENT_CATEGORY_OVERRIDES.values())
    odd = sorted({v["category"] for v in DATA.values()} - allowed)
    check(not odd, "every category is a Chart-of-Accounts name", str(odd[:5]))

    ovr = diag.get("client_overrides", [])
    check(len(ovr) <= len(mapping.CLIENT_CATEGORY_OVERRIDES),
          "human-set categories limited to declared client instructions",
          str([(o[1], o[2]) for o in ovr]))

    raw_open = sum(1 for e in vle if e.get("Open")
                   and abs(e.get("Remaining_Amount") or 0) >= 0.01 and transform._plausible(e))
    shown_open = sum(len(v["opens"]) for v in DATA.values())
    check(raw_open == shown_open, "open items match BC's Open flag exactly",
          "BC %d vs shown %d" % (raw_open, shown_open))

    # ---------------------------------------------------------------- derived
    head(4, "DERIVED figures must be disclosed on the page")
    fields = set(vle[0].keys()) if vle else set()
    check("Closed_at_Date" not in fields,
          "BC feed genuinely lacks Closed at Date (so FIFO is necessary, not lazy)")
    for phrase in ("Estimated", "FIFO", "oldest open invoices"):
        check(phrase in tpl, "Data sources panel discloses %r" % phrase)

    # ---------------------------------------------------------------- excluded
    head(5, "NOT-IN-BC items must be absent from the data and declared on the page")
    agents = [n for n in DATA if any(a in n for a in ("Sales Agent", "Abhilash", "Eoghan", "Marius"))]
    check(not agents, "no sales-agent rows", str(agents))
    check(all(not v["breakdown"]["bifurcate"] for v in DATA.values()),
          "contract/variation split off everywhere")
    for phrase in ("sales-agent commission", "contract versus variation"):
        check(phrase in tpl.lower(), "panel declares %r unavailable" % phrase)

    # ---------------------------------------------------------------- result
    head(6, "RESULT")
    print("  suppliers rendered : %s" % format(len(DATA), ","))
    print("  total outstanding  : %s AED" % format(round(diag["total_outstanding"]), ","))
    print("  uncategorised      : %d (no purchase invoice lines in BC)" % len(diag["uncategorised"]))
    print("  entries excluded   : %d (invalid posting dates)" % diag["bad_date_entries"])
    print()
    if FAILS:
        print("FAILURES (%d): %s" % (len(FAILS), FAILS))
        return 1
    print("ALL CHECKS PASSED - every figure on the dashboard traces to live BC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

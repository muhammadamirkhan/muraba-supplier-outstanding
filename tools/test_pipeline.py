"""Headless end-to-end check -- run before pushing.

    python tools/test_pipeline.py
"""
import collections
import json
import os

from _common import APP, mapping, transform, pull


def main():
    vle, lines, coa = pull()
    print(f"BC: {len(vle):,} ledger entries, {len(lines):,} invoice lines, {len(coa):,} accounts")

    DATA, PERF, LEDGERS, TXNS, diag = transform.build(vle, lines, coa)
    print("\n=== diagnostics ===")
    for k, v in diag.items():
        print(f"  {k}: {len(v) if isinstance(v, list) else v}")

    bad = [n for n, v in DATA.items()
           if abs((v["invoiced_aed"] or 0) - (v["paid_aed"] or 0) - (v["outstanding_aed"] or 0)) > 1]
    print(f"\nidentity invoiced-paid==outstanding: {len(DATA) - len(bad)}/{len(DATA)}"
          + (f"  VIOLATIONS: {bad[:5]}" if bad else ""))

    neg = [n for n, v in DATA.items() if v["invoiced_aed"] < 0 or v["paid_aed"] < 0]
    print(f"negative invoiced/paid: {len(neg)}" + (f" -> {neg[:5]}" if neg else "  (none)"))

    blob = json.dumps(DATA)
    print(f"'-0' tokens in payload: {blob.count(':-0.0,') + blob.count(':-0,')}")

    print("\ntop outstanding:")
    for n, v in sorted(DATA.items(), key=lambda x: -(x[1]["outstanding_aed"] or 0))[:6]:
        print(f'  {n[:46]:<46} [{v["category"][:26]:<26}] {v["outstanding_aed"]:>13,.0f}')

    cats = collections.Counter(v["category"] for v in DATA.values())
    print(f"\n{len(cats)} categories; {cats[mapping.UNCATEGORISED]} uncategorised")

    tpl = open(os.path.join(APP, "template.html"), encoding="utf-8").read()
    out = (tpl.replace("__DATA_JSON__", json.dumps(DATA, ensure_ascii=False))
              .replace("__PERF_JSON__", json.dumps(PERF, ensure_ascii=False))
              .replace("__LEDGERS_JSON__", json.dumps(LEDGERS, ensure_ascii=False))
              .replace("__TXNS_JSON__", json.dumps(TXNS, ensure_ascii=False))
              .replace("__TXNHEAD_JSON__", json.dumps(diag["txn_head"], ensure_ascii=False))
              .replace("__ASOF__", "today"))
    # every placeholder the template declares must be filled -- scan for any
    # __NAME__ left behind rather than a hardcoded list that goes stale
    import re as _re
    left = sorted(set(_re.findall(r"__[A-Z_]+__", out)))
    print(f"render: {len(out)/1e6:.2f} MB, leftover placeholders: {left or 'none'}")
    print(f"transactions: {diag['txn_rows']:,} rows across {len(TXNS)} suppliers")


if __name__ == "__main__":
    main()

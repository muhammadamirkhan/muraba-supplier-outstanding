"""Turn BC vendor ledger entries into the three JSON blobs the dashboard expects.

Money rules, validated against the original statement-derived dashboard:

  outstanding = -sum(Remaining_Amt_LCY)          <- ties to the statements exactly
  invoiced    =  sum(Credit_Amount_LCY) - credit-memo debits
  paid        =  sum(Debit_Amount_LCY)  - credit-memo debits

Do NOT filter on Document_Type: it is blank on ~45% of entries (journal-posted),
so `Document_Type == 'Invoice'` silently drops nearly half the value. The
credit/debit columns carry every entry. Credit memos are debits, and the original
dashboard nets them off invoiced rather than counting them as payments -- the
subtraction appears on both lines so the identity invoiced - paid == outstanding
still holds.

BC keeps AP balances negative (a credit means we owe); every figure here is
sign-flipped to the positive convention the dashboard displays.
"""
import datetime as _dt
from collections import defaultdict

import mapping

# The original dashboard split these suppliers into Contract vs Variation. BC has
# no such classification, so it is inferred from invoice-line text and flagged in
# the UI as inferred. Empty this set to switch the split off entirely.
BIFURCATE_SUPPLIERS = {
    "Arup Gulf Limited", "WSP Middle East", "Zetas Zemin",
    "BeWunder", "TrafQuest", "Joseph Graphics",
}
VARIATION_WORDS = ("variation", "addendum", "vo-", "vo ", "v.o", "additional works")

# Quarters kept on the payment-speed trend chart (original showed 13).
TREND_QUARTERS = 13

# A vendor outside the curated list joins the register once its balance exceeds
# this (either direction -- credit balances matter too).
AUTO_INCLUDE_THRESHOLD = 0.01

# Curated suppliers with no BC activity at all are hidden rather than rendered as
# a row of dashes. A fully-settled supplier (invoiced == paid, nothing
# outstanding) still has values and stays -- "empty" means nothing to show.
DROP_EMPTY_SUPPLIERS = True

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _n(row, key):
    return row.get(key) or 0.0


def _date(s):
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _fmt_date(s):
    d = _date(s)
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}" if d else ""


def _is_credit_memo(e):
    return (e.get("Document_Type") or "").strip() == "Credit Memo"


def _plausible(e):
    """Drop entries with obviously bad posting dates (BC has 2029 and 3035 typos)."""
    d = _date(e.get("Posting_Date"))
    return bool(d) and 2000 <= d.year <= _dt.date.today().year + 1


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def group_entries(vle):
    """Vendor_No -> entries for every vendor in the ledger, sane dates only.

    Deliberately NOT filtered to the mapped suppliers -- doing that hid any
    vendor outside the curated list that happened to carry a balance. Selection
    happens in build(), which keeps the curated list plus anyone with a
    non-zero balance.
    """
    out = defaultdict(list)
    skipped = []
    for e in vle:
        no = e.get("Vendor_No")
        if not no:
            continue
        if not _plausible(e):
            skipped.append(e)
            continue
        out[no].append(e)
    for no in out:
        out[no].sort(key=lambda x: (str(x.get("Posting_Date") or ""), x.get("Entry_No") or 0))
    return out, skipped


def _money(entries):
    cm = sum(_n(e, "Debit_Amount_LCY") for e in entries if _is_credit_memo(e))
    cm_o = sum(_n(e, "Debit_Amount") for e in entries if _is_credit_memo(e))
    return {
        "invoiced_aed": sum(_n(e, "Credit_Amount_LCY") for e in entries) - cm,
        "paid_aed": sum(_n(e, "Debit_Amount_LCY") for e in entries) - cm,
        "outstanding_aed": -sum(_n(e, "Remaining_Amt_LCY") for e in entries),
        "invoiced_orig": sum(_n(e, "Credit_Amount") for e in entries) - cm_o,
        "paid_orig": sum(_n(e, "Debit_Amount") for e in entries) - cm_o,
        "outstanding_orig": -sum(_n(e, "Remaining_Amount") for e in entries),
    }


def _currency(entries):
    counts = defaultdict(int)
    for e in entries:
        c = (e.get("Currency_Code") or "").strip()
        if c:
            counts[c] += 1
    return max(counts, key=counts.get) if counts else "AED"


def _breakdown(name, entries, descriptions, currency):
    """Contract vs Variation, inferred from invoice-line text."""
    if name not in BIFURCATE_SUPPLIERS:
        return {"con": {"inv": 0.0, "out": 0.0, "paid": 0.0},
                "var": {"inv": 0.0, "out": 0.0, "paid": 0.0},
                "bifurcate": False, "currency": currency}
    buckets = {"con": defaultdict(float), "var": defaultdict(float)}
    for e in entries:
        text = (descriptions.get(e.get("Document_No")) or "").lower()
        k = "var" if any(w in text for w in VARIATION_WORDS) else "con"
        buckets[k]["inv"] += _n(e, "Credit_Amount")
        if _is_credit_memo(e):
            # a credit memo reduces what was invoiced; it is not a payment
            buckets[k]["inv"] -= _n(e, "Debit_Amount")
        else:
            buckets[k]["paid"] += _n(e, "Debit_Amount")
        buckets[k]["out"] += -_n(e, "Remaining_Amount")

    con = {k: round(buckets["con"][k], 2) for k in ("inv", "out", "paid")}
    var = {k: round(buckets["var"][k], 2) for k in ("inv", "out", "paid")}
    # No variation side found -> a stacked chart with one empty series is just
    # noise, so fall back to the plain invoiced/paid/balance view.
    if all(abs(v) < 1 for v in var.values()):
        return {"con": con, "var": var, "bifurcate": False, "currency": currency}
    return {"con": con, "var": var, "bifurcate": True, "currency": currency}


def _opens(entries):
    """Itemised open invoices -- the original dashboard could never fill these."""
    rows = []
    for e in entries:
        if not e.get("Open"):
            continue
        rem = -_n(e, "Remaining_Amount")
        if abs(rem) < 0.01:
            continue
        rows.append({
            "no": e.get("Document_No") or "",
            "date": _fmt_date(e.get("Posting_Date")),
            "amt": round(rem, 2),
            "amt_aed": round(-_n(e, "Remaining_Amt_LCY"), 2),
        })
    rows.sort(key=lambda r: r["date"])
    return rows


# ---------------------------------------------------------------------------
# payment performance (FIFO estimate)
# ---------------------------------------------------------------------------

def _fifo_pairs(entries):
    """Pair payments against that vendor's oldest open invoices.

    BC does not publish Closed_at_Date / Closed_by_Entry_No, so which payment
    settled which invoice is unknown. FIFO is the standard assumption. Yields
    (days_to_pay, amount_lcy) per allocation.
    """
    invs = [[_date(e.get("Posting_Date")), _n(e, "Credit_Amount_LCY")]
            for e in entries if _n(e, "Credit_Amount_LCY") > 0 and _date(e.get("Posting_Date"))]
    pays = [[_date(e.get("Posting_Date")), _n(e, "Debit_Amount_LCY")]
            for e in entries
            if _n(e, "Debit_Amount_LCY") > 0 and not _is_credit_memo(e)
            and _date(e.get("Posting_Date"))]
    invs.sort()
    pays.sort()
    out, i = [], 0
    for pdate, pamt in pays:
        while pamt > 0.01 and i < len(invs):
            idate, iamt = invs[i]
            take = min(pamt, iamt)
            out.append(((pdate - idate).days, take))
            invs[i][1] -= take
            pamt -= take
            if invs[i][1] <= 0.01:
                i += 1
    return out


def _stats(pairs):
    total = sum(a for _d, a in pairs)
    if total <= 0:
        return None
    def share(lo, hi):
        return sum(a for d, a in pairs if lo <= d <= hi)
    avg = sum(d * a for d, a in pairs) / total
    return {
        "paid": round(total),
        "avg": round(avg),
        "w30": round(100 * share(-10**6, 30) / total),
        "w60": round(100 * share(-10**6, 60) / total),
        "w90": round(100 * share(-10**6, 90) / total),
        "buckets": {
            "0-30": round(share(-10**6, 30)),
            "31-60": round(share(31, 60)),
            "61-90": round(share(61, 90)),
            "90+": round(share(91, 10**6)),
        },
    }


def build_perf(grouped, names):
    all_pairs, by_supplier, trend_acc = [], {}, defaultdict(list)
    for no, entries in grouped.items():
        name = names.get(no)
        pairs = _fifo_pairs(entries)
        if not pairs:
            continue
        all_pairs.extend(pairs)
        s = _stats(pairs)
        if s:
            by_supplier[name] = {"avg": s["avg"], "w30": s["w30"], "paid": s["paid"]}
        # quarter attribution uses the payment date
        pays = sorted(
            (_date(e.get("Posting_Date")), _n(e, "Debit_Amount_LCY"))
            for e in entries
            if _n(e, "Debit_Amount_LCY") > 0 and not _is_credit_memo(e)
            and _date(e.get("Posting_Date"))
        )
        for (days, amt), (pdate, _amt) in zip(pairs, pays):
            trend_acc[f"{pdate.year}-Q{(pdate.month - 1) // 3 + 1}"].append((days, amt))

    company = _stats(all_pairs) or {
        "paid": 0, "avg": 0, "w30": 0, "w60": 0, "w90": 0,
        "buckets": {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0},
    }
    trend = []
    for q in sorted(trend_acc):
        pr = trend_acc[q]
        tot = sum(a for _d, a in pr)
        if tot <= 0:
            continue
        trend.append({
            "q": q,
            "avg": round(sum(d * a for d, a in pr) / tot),
            "paid": round(tot),
        })
    # BC history reaches back to 2013; the original chart showed 13 quarters and
    # the x-axis is unreadable much beyond that.
    trend = trend[-TREND_QUARTERS:]
    return {"company": company, "by_supplier": by_supplier, "trend": trend}


# ---------------------------------------------------------------------------
# printable statements
# ---------------------------------------------------------------------------

LEDGER_HEAD = ["Invoice No", "Invoice Date", "Invoice Amount", "Payment Date",
               "Payment Amount", "Balance", "Description", "Remarks"]


def build_ledger(entries, descriptions, currency):
    """Statement rows, pairing each invoice with the payment(s) that settled it.

    The original statements put invoice and payment side by side on one row, so
    payments are FIFO-allocated to invoices to reproduce that. A second payment
    against the same invoice gets a continuation row; an unmatched payment
    (prepayment / overpayment) gets its own row.
    """
    invs, pays, memos = [], [], []
    for e in entries:
        doc = e.get("Document_No") or ""
        date = _fmt_date(e.get("Posting_Date"))
        desc = descriptions.get(doc) or ""
        cred, deb = _n(e, "Credit_Amount"), _n(e, "Debit_Amount")
        if cred > 0:
            invs.append({"doc": doc, "date": date, "amt": cred, "left": cred, "desc": desc})
        if deb > 0:
            (memos if _is_credit_memo(e) else pays).append(
                {"doc": doc, "date": date, "amt": deb, "left": deb, "desc": desc}
            )

    # FIFO: each payment settles the oldest invoice still open
    alloc = {id(i): [] for i in invs}
    leftover = []
    i = 0
    for p in pays:
        while p["left"] > 0.01 and i < len(invs):
            take = min(p["left"], invs[i]["left"])
            if take > 0.01:
                alloc[id(invs[i])].append((p, take))
            invs[i]["left"] -= take
            p["left"] -= take
            if invs[i]["left"] <= 0.01:
                i += 1
        if p["left"] > 0.01:
            leftover.append(p)

    rows, running, inv_tot, paid_tot = [], 0.0, 0.0, 0.0
    for inv in invs:
        inv_tot += inv["amt"]
        running += inv["amt"]
        pair = alloc[id(inv)]
        first = pair[0] if pair else None
        if first:
            paid_tot += first[1]
            running -= first[1]
        rows.append([
            inv["doc"], inv["date"], round(inv["amt"], 2),
            first[0]["date"] if first else "",
            round(first[1], 2) if first else "",
            round(running, 2), inv["desc"], "",
        ])
        for p, amt in pair[1:]:
            paid_tot += amt
            running -= amt
            rows.append(["", "", "", p["date"], round(amt, 2),
                         round(running, 2), "", "part payment"])

    for p in leftover:
        paid_tot += p["left"]
        running -= p["left"]
        rows.append(["", "", "", p["date"], round(p["left"], 2),
                     round(running, 2), p["desc"], "unapplied"])

    for m in memos:
        inv_tot -= m["amt"]
        running -= m["amt"]
        rows.append([m["doc"], m["date"], round(-m["amt"], 2), "", "",
                     round(running, 2), m["desc"], "credit memo"])

    summary = [[p["date"], round(p["amt"], 2)] for p in pays]
    return {
        "head": LEDGER_HEAD,
        "rows": rows,
        "invoiced": round(inv_tot, 2),
        "paid": round(paid_tot, 2),
        "currency": currency,
        "payment_summary": summary,
    }


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build(vle, invoice_lines=None, agent_earned=None, agent_paid=None):
    """-> (DATA, PERF, LEDGERS, diagnostics)"""
    grouped, skipped = group_entries(vle)
    names = {no: name for no, (name, _c) in mapping.by_vendor_no().items()}
    mapped_nos = set(mapping.vendor_numbers())

    descriptions = {}
    for ln in (invoice_lines or []):
        doc = ln.get("Document_No")
        if doc and doc not in descriptions:
            d = (ln.get("Description") or "").strip()
            if d:
                descriptions[doc] = d

    DATA, LEDGERS = {}, {}
    dropped_empty = []
    for name, (no, cat) in mapping.SUPPLIERS.items():
        entries = grouped.get(no, [])
        ccy = _currency(entries)
        m = _money(entries)
        if DROP_EMPTY_SUPPLIERS and all(
            abs(m[k]) < 1 for k in ("invoiced_aed", "paid_aed", "outstanding_aed")
        ):
            dropped_empty.append(name)
            continue
        DATA[name] = {
            "name": name,
            "category": cat,
            "currency": ccy,
            "has_soa": bool(entries),
            **{k: round(v, 2) for k, v in m.items()},
            "breakdown": _breakdown(name, entries, descriptions, ccy),
            "opens": _opens(entries),
            "master_aed": None,
        }
        if entries:
            LEDGERS[name] = build_ledger(entries, descriptions, ccy)

    # Any other BC vendor carrying a balance. Without this, a vendor outside the
    # curated list simply never appears, however much it owes.
    auto_added = []
    for no, entries in grouped.items():
        if no in mapped_nos or not entries:
            continue
        m = _money(entries)
        if abs(m["outstanding_aed"]) <= AUTO_INCLUDE_THRESHOLD:
            continue
        name = next((e.get("Vendor_Name") or "").strip() for e in reversed(entries)
                    if (e.get("Vendor_Name") or "").strip())
        if not name or name in DATA:
            name = f"{name or 'Unknown vendor'} ({no})"
        ccy = _currency(entries)
        DATA[name] = {
            "name": name,
            "category": mapping.category_for(no),
            "currency": ccy,
            "has_soa": True,
            **{k: round(v, 2) for k, v in m.items()},
            "breakdown": _breakdown(name, entries, descriptions, ccy),
            "opens": _opens(entries),
            "master_aed": None,
        }
        LEDGERS[name] = build_ledger(entries, descriptions, ccy)
        auto_added.append((no, name, round(m["outstanding_aed"], 2)))

    # in-house sales agents: paid from GL 21014, earned from the manual file
    agent_earned = agent_earned or {}
    agent_paid = agent_paid or {}
    for dash_name, short in mapping.SALES_AGENTS.items():
        paid = float(agent_paid.get(short, 0.0))
        earned = float(agent_earned.get(short, 0.0))
        DATA[dash_name] = {
            "name": dash_name,
            "category": mapping.AGENT_CATEGORY,
            "currency": "AED",
            "has_soa": bool(earned or paid),
            "invoiced_orig": round(earned, 2), "paid_orig": round(paid, 2),
            "outstanding_orig": round(earned - paid, 2),
            "invoiced_aed": round(earned, 2), "paid_aed": round(paid, 2),
            "outstanding_aed": round(earned - paid, 2),
            "breakdown": {"con": {"inv": 0.0, "out": 0.0, "paid": 0.0},
                          "var": {"inv": 0.0, "out": 0.0, "paid": 0.0},
                          "bifurcate": False, "currency": "AED"},
            "opens": [], "master_aed": None,
        }

    PERF = build_perf(grouped, names)

    diagnostics = {
        "entries_used": sum(len(grouped.get(no, [])) for no in mapped_nos)
        + sum(len(grouped.get(no, [])) for no, _n, _o in auto_added),
        "entries_total": len(vle),
        "bad_date_entries": len(skipped),
        "suppliers": len(DATA),
        "vendors_in_ledger": len(grouped),
        "vendors_matched": len([no for no in mapped_nos if no in grouped]),
        "auto_added": sorted(auto_added, key=lambda x: -abs(x[2])),
        "auto_added_total": round(sum(o for _no, _n, o in auto_added), 2),
        "vendors_missing": [n for n, (no, _c) in mapping.SUPPLIERS.items() if no not in grouped],
        "dropped_empty": sorted(dropped_empty),
        "open_items": sum(len(v["opens"]) for v in DATA.values()),
        "descriptions": len(descriptions),
        "total_outstanding": round(sum(v["outstanding_aed"] or 0 for v in DATA.values()), 2),
        "total_invoiced": round(sum(v["invoiced_aed"] or 0 for v in DATA.values()), 2),
        "total_paid": round(sum(v["paid_aed"] or 0 for v in DATA.values()), 2),
    }
    return DATA, PERF, LEDGERS, diagnostics

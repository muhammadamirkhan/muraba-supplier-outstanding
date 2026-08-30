"""Turn BC vendor ledger entries into the three JSON blobs the dashboard expects.

Money rules, all from the signed Amount(_LCY) on each ledger entry:

  invoiced    = -sum(amount) over entries where amount < 0   (charged to us)
                minus credit memos, which cancel part of a charge
  paid        =  sum(amount) over entries where amount > 0   (settled), credit
                memos excluded
  outstanding = -sum(Remaining_Amt_LCY)

Use the SIGNED amount, not the Debit/Credit columns: BC records some reversing
journals with NEGATIVE debit and credit amounts, which makes a literal sum of
those columns come out negative on both lines (Al Hai JV2100005 did exactly
that). Equally, do NOT filter on Document_Type -- it is blank on ~45% of entries
(journal-posted), so `Document_Type == 'Invoice'` silently drops half the value.

The identity invoiced - paid == outstanding holds by construction, since both
sides reduce to the vendor's net balance.

BC keeps AP balances negative (a credit means we owe); every figure here is
sign-flipped to the positive convention the dashboard displays. _zero() clamps
signed-zero and sub-fils dust so nothing ever renders as "-0".
"""
import datetime as _dt
from collections import defaultdict

import mapping

# Contract vs Variation: REMOVED at the client's request.
#
# The original statement-based dashboard carried this split because the SOA
# documents stated it. BC has no equivalent field, so the rebuild inferred it by
# keyword-matching invoice descriptions -- which produced authoritative-looking
# figures from a guess. Better to show nothing than a number nobody can trace.
#
# Re-enable only if a real source appears (a BC dimension, or a flag on the
# invoice line): put supplier names back in this set and the split returns.
BIFURCATE_SUPPLIERS = set()
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


def _zero(v):
    """Kill -0 and sub-fils dust so nothing renders as '-0'."""
    return 0.0 if abs(v) < 0.005 else v


def _split(entries, amount_field):
    """Charges vs settlements, from the SIGNED amount.

    Derived from Amount(_LCY), not the Debit/Credit columns: BC records some
    reversing journals with NEGATIVE debit and credit amounts (e.g. Al Hai
    JV2100005), which made a literal sum of those columns come out negative on
    both lines. The signed amount is unambiguous -- negative = charged to us,
    positive = settled -- however the entry was booked.

    A credit memo is a positive amount that cancels part of a charge, so it
    reduces invoiced rather than counting as a payment.
    """
    invoiced = paid = 0.0
    for e in entries:
        a = _n(e, amount_field)
        if a < 0:
            invoiced -= a
        elif a > 0:
            if _is_credit_memo(e):
                invoiced -= a
            else:
                paid += a
    return invoiced, paid


def _money(entries):
    inv, paid = _split(entries, "Amount_LCY")
    inv_o, paid_o = _split(entries, "Amount")
    return {
        "invoiced_aed": _zero(inv),
        "paid_aed": _zero(paid),
        "outstanding_aed": _zero(-sum(_n(e, "Remaining_Amt_LCY") for e in entries)),
        "invoiced_orig": _zero(inv_o),
        "paid_orig": _zero(paid_o),
        "outstanding_orig": _zero(-sum(_n(e, "Remaining_Amount") for e in entries)),
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


# Payables ageing. The client asked for 0-30 / 30-60 / 60-90 / 90-180 / 180-360;
# 360+ is added because roughly AED 7.8m of open items are older than that and
# would otherwise vanish from a table that is meant to total the payable.
AGE_BUCKETS = [("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90),
               ("91-180", 91, 180), ("181-360", 181, 360), ("360+", 361, 10 ** 6)]


def _bucket(days):
    for label, lo, hi in AGE_BUCKETS:
        if lo <= days <= hi:
            return label
    return AGE_BUCKETS[0][0] if days < 0 else AGE_BUCKETS[-1][0]


def _ageing(entries, asof):
    """Open items bucketed by age, on both bases BC supports.

    'invoice' ages from the posting date -- how long the payable has existed.
    'due' ages from the due date -- how overdue it is. Both are BC fields and
    both total to the supplier's outstanding balance, so the two views agree on
    the total and differ only in distribution.
    """
    out = {"invoice": {b[0]: 0.0 for b in AGE_BUCKETS},
           "due": {b[0]: 0.0 for b in AGE_BUCKETS},
           "count": 0}
    if not asof:
        return out
    for e in entries:
        if not e.get("Open"):
            continue
        amt = -_n(e, "Remaining_Amt_LCY")
        if abs(amt) < 0.01:
            continue
        out["count"] += 1
        for key, field in (("invoice", "Posting_Date"), ("due", "Due_Date")):
            d = _date(e.get(field))
            if d:
                out[key][_bucket((asof - d).days)] += amt
    for key in ("invoice", "due"):
        out[key] = {k: _zero(round(v, 2)) for k, v in out[key].items()}
    return out


def supplier_refs(purchase_invoices):
    """BC Document_No -> the supplier's OWN invoice number.

    Vendor Ledger Entries carry only BC's internal posting number (PPI003272).
    Finance reconciles against the reference printed on the supplier's invoice,
    which BC stores as vendorInvoiceNumber on the posted purchase invoice.
    Payments, journals and credit memos have no such reference -- correctly, as
    they are not supplier invoices -- and keep the BC number.
    """
    out = {}
    for r in purchase_invoices or []:
        doc = (r.get("number") or "").strip()
        ref = (r.get("vendorInvoiceNumber") or "").strip()
        if doc and ref:
            out[doc] = ref
    return out


def _opens(entries, refs=None):
    """Itemised open invoices -- the original dashboard could never fill these."""
    refs = refs or {}
    rows = []
    for e in entries:
        if not e.get("Open"):
            continue
        rem = -_n(e, "Remaining_Amount")
        if abs(rem) < 0.01:
            continue
        doc = e.get("Document_No") or ""
        rows.append({
            # Supplier reference only. Payments, journals and credit memos have
            # none -- correctly, they are not supplier invoices -- and the BC
            # column carries the document number for every row anyway, so do
            # not fall back to it here or both columns read the same.
            "no": refs.get(doc, ""),
            "bc_no": doc,
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

LEDGER_HEAD = ["Supplier Inv. No", "Invoice Date", "Invoice Amount", "Payment Date",
               "Payment Amount", "Balance", "Description", "BC Ref."]


def build_ledger(entries, descriptions, currency, refs=None):
    """Statement rows, pairing each invoice with the payment(s) that settled it.

    The original statements put invoice and payment side by side on one row, so
    payments are FIFO-allocated to invoices to reproduce that. A second payment
    against the same invoice gets a continuation row; an unmatched payment
    (prepayment / overpayment) gets its own row.
    """
    refs = refs or {}
    invs, pays, memos = [], [], []
    for e in entries:
        doc = e.get("Document_No") or ""
        ref = refs.get(doc) or ""          # the supplier's own invoice number
        date = _fmt_date(e.get("Posting_Date"))
        desc = descriptions.get(doc) or ""
        # Classify on the SIGNED amount, exactly as _money() does, so the
        # statement's totals reconcile to the supplier's register row. Using the
        # Credit/Debit columns here made them disagree, because BC books some
        # reversals with negative debits AND credits.
        a = _n(e, "Amount")
        if a < 0:
            invs.append({"doc": doc, "ref": ref, "date": date, "amt": -a,
                         "left": -a, "desc": desc})
        elif a > 0:
            (memos if _is_credit_memo(e) else pays).append(
                {"doc": doc, "ref": ref, "date": date, "amt": a, "left": a, "desc": desc}
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
            inv["ref"], inv["date"], round(inv["amt"], 2),
            first[0]["date"] if first else "",
            round(first[1], 2) if first else "",
            round(running, 2), inv["desc"], inv["doc"],
        ])
        for p, amt in pair[1:]:
            paid_tot += amt
            running -= amt
            rows.append(["", "", "", p["date"], round(amt, 2),
                         round(running, 2), "part payment", p["doc"]])

    for p in leftover:
        paid_tot += p["left"]
        running -= p["left"]
        rows.append(["", "", "", p["date"], round(p["left"], 2),
                     round(running, 2), p["desc"] or "unapplied payment", p["doc"]])

    for m in memos:
        inv_tot -= m["amt"]
        running -= m["amt"]
        rows.append([m["ref"], m["date"], round(-m["amt"], 2), "", "",
                     round(running, 2), m["desc"] or "credit memo", m["doc"]])

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

def _vendor_spend_by_account(invoice_lines):
    """Vendor_No -> {account_no: signed amount} from posted purchase invoice lines."""
    spend = defaultdict(lambda: defaultdict(float))
    for l in invoice_lines or []:
        v = l.get("Buy_from_Vendor_No")
        if v and (l.get("Type") or "").strip() == "G/L Account" and l.get("No"):
            spend[v][l["No"]] += l.get("Amount") or 0
    return spend


def _derive_category(accounts, coa):
    """Category = cleaned name of the vendor's dominant cost account.

    Mechanics accounts (CWIP, advances, prepaid, accruals) are skipped first;
    if the vendor posts ONLY to those, the mechanics account itself is used --
    still a BC fact, never an invented label. No accounts at all -> Uncategorised.
    """
    if not accounts:
        return mapping.UNCATEGORISED, None
    ranked = sorted(accounts.items(), key=lambda x: -abs(x[1]))
    real = [(a, amt) for a, amt in ranked if a not in mapping.MECHANICS_ACCOUNTS]
    acct_no = (real or ranked)[0][0]
    return mapping.clean_category(coa.get(acct_no)), acct_no


def build(vle, invoice_lines=None, coa=None, purchase_invoices=None):
    """-> (DATA, PERF, LEDGERS, diagnostics). Everything from BC.

    Register = every vendor in the ledger with non-zero money. The reference
    HTML contributes layout only.
    """
    coa = coa or {}
    refs = supplier_refs(purchase_invoices)
    grouped, skipped = group_entries(vle)
    asof = max((_date(e.get("Posting_Date")) for e in vle
                if _plausible(e) and _date(e.get("Posting_Date"))), default=None)

    descriptions = {}
    for ln in (invoice_lines or []):
        doc = ln.get("Document_No")
        if doc and doc not in descriptions:
            d = (ln.get("Description") or "").strip()
            if d:
                descriptions[doc] = d

    spend = _vendor_spend_by_account(invoice_lines)

    DATA, LEDGERS = {}, {}
    names, uncategorised, overridden = {}, [], []
    for no, entries in grouped.items():
        m = _money(entries)
        if all(abs(m[k]) < 1 for k in ("invoiced_aed", "paid_aed", "outstanding_aed")):
            continue  # nothing to show

        name = next((( e.get("Vendor_Name") or "").strip() for e in reversed(entries)
                     if (e.get("Vendor_Name") or "").strip()), "") or f"Vendor {no}"
        if name in DATA:  # two BC vendor cards sharing one name stay distinct
            name = f"{name} ({no})"
        names[no] = name

        if no in mapping.CLIENT_CATEGORY_OVERRIDES:
            cat = mapping.CLIENT_CATEGORY_OVERRIDES[no]
            overridden.append((no, name, cat))
        else:
            cat, acct_no = _derive_category(spend.get(no, {}), coa)
            if cat == mapping.UNCATEGORISED:
                uncategorised.append((no, name, round(m["outstanding_aed"], 2)))

        ccy = _currency(entries)
        DATA[name] = {
            "name": name,
            "category": cat,
            "currency": ccy,
            "has_soa": True,
            **{k: round(v, 2) for k, v in m.items()},
            "breakdown": _breakdown(name, entries, descriptions, ccy),
            "opens": _opens(entries, refs),
            "ageing": _ageing(entries, asof),
            "master_aed": None,
        }
        LEDGERS[name] = build_ledger(entries, descriptions, ccy, refs)

    PERF = build_perf({no: grouped[no] for no in names}, names)

    diagnostics = {
        "entries_total": len(vle),
        "entries_used": sum(len(grouped[no]) for no in names),
        "bad_date_entries": len(skipped),
        "vendors_in_ledger": len(grouped),
        "vendors_shown": len(DATA),
        "uncategorised": sorted(uncategorised, key=lambda x: -abs(x[2])),
        "client_overrides": overridden,
        "categories": sorted({v["category"] for v in DATA.values()}),
        "open_items": sum(len(v["opens"]) for v in DATA.values()),
        "descriptions": len(descriptions),
        "supplier_refs": len(refs),
        "asof": asof.isoformat() if asof else "",
        "age_buckets": [b[0] for b in AGE_BUCKETS],
        "total_outstanding": round(sum(v["outstanding_aed"] or 0 for v in DATA.values()), 2),
        "total_invoiced": round(sum(v["invoiced_aed"] or 0 for v in DATA.values()), 2),
        "total_paid": round(sum(v["paid_aed"] or 0 for v in DATA.values()), 2),
    }
    return DATA, PERF, LEDGERS, diagnostics

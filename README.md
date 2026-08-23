# Supplier Outstanding — live from Business Central

Streamlit port of `Supplier_Dashboard.html`. The original page is reused verbatim
as `template.html`; only its three data blobs (`DATA`, `PERF`, `LEDGERS`) are
replaced with live BC data at render time. That keeps the CSS, the Chart.js
visuals, row expansion and the print-to-Statement-of-Account behaviour identical —
none of which Streamlit widgets can reproduce.

## Run locally

```bash
streamlit run app.py --server.port 8783
```

Locally the BC client secret is picked up from `muraba_bc_api_credentials.txt` on
the G: drive, so nothing extra is needed. `dev_bypass = true` in
`.streamlit/secrets.toml` skips the password prompt.

## Deploy to Streamlit Cloud

Repo: `muhammadamirkhan/muraba-supplier-outstanding` — **private**. No financial
data lives in it (everything comes from BC at runtime), but `mapping.py` exposes
the supplier roster and internal vendor codes, so it stays closed.

**The app itself is public, which is deliberate.** Streamlit Community Cloud
allows only one *private app* per user and that slot belongs to `muraba-cashflow`.
Deploying from a private repo makes the app private by default, so set
Settings → Sharing → public straight after the first deploy; access is controlled
by the password gate in `app.py`, not by app visibility. (If Cloud refuses the
deploy because of the one-private-app rule, flip `muraba-cashflow` public for a
minute, deploy this one, set it public, then restore.)

There is no G: drive on Cloud, so Secrets must carry both the BC credential and
the sales-agent figures. App → Settings → Secrets:

```toml
password = "<pick one>"
bc_client_secret = "<the Value from Azure, not the Secret ID>"

[agents.Abhilash]
earned = 0
paid = 0

[agents.Eoghan]
earned = 0
paid = 0

[agents.Marius]
earned = 0
paid = 0
```

Fill the agent figures from Finance's Inhouse Com sheet — they name individuals,
which is why they are kept out of the repo (`agents_manual.json` is gitignored;
`agents_manual.example.json` is the template).

Do **not** set `dev_bypass` on Cloud — it would remove the password gate.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit shell: password gate, controls, injects data into the template |
| `bc.py` | BC OAuth client-credentials + paged OData reads (read-only) |
| `transform.py` | BC entries → `DATA` / `PERF` / `LEDGERS`; all money rules live here |
| `mapping.py` | Dashboard supplier name → BC `Vendor_No` + category; review flags |
| `template.html` | The original dashboard with `__DATA_JSON__` etc. placeholders |
| `agents_manual.json` | Sales-agent commission earned/paid (not in BC — see below) |

Regenerate the template if the design changes: replace the three
`NAME = {...}` literals in the HTML with `__NAME_JSON__` and the as-of date with
`__ASOF__`.

## How the numbers are derived

```
outstanding = -sum(Remaining_Amt_LCY)
invoiced    =  sum(Credit_Amount_LCY) - credit-memo debits
paid        =  sum(Debit_Amount_LCY)  - credit-memo debits
```

BC keeps AP balances negative (a credit means we owe), so everything is
sign-flipped for display.

**Do not filter on `Document_Type`.** It is blank on roughly 45% of entries
(journal-posted), so `Document_Type == 'Invoice'` silently drops nearly half the
value. The credit/debit columns cover every entry.

**Match suppliers on `Vendor_No`, never on name.** BC uses legal names
("Zetas Zemin Teknolojisi A.S Dubai Branch") and contains typos
("XOXO Real Esatate", "Geoestate" vs "Geostate"). Every fuzzy matcher tried
mis-assigned brokers on the generic words "Real Estate" / "Properties".

## Known differences from the original statement-based dashboard

- **Outstanding ties out.** AED 48.39M vs the statements' 48.84M; 44 of 53
  suppliers agree to within 1 AED. The residual is FX plus the four items in
  `mapping.REVIEW`.
- **FX is better.** BC's booked rates replace the old hardcoded indicative
  GBP 4.65 / EUR 4.00, which is why Pentagram and RCR shift slightly.
- **Every BC vendor with a balance appears, not just the curated list.** The
  register is `mapping.SUPPLIERS` (kept even at zero, to preserve the original
  view) *plus* any other vendor whose balance is non-zero, added automatically
  under `mapping.AUTO_CATEGORY` with its BC legal name. Scoping strictly to the
  curated list originally hid 16 vendors holding AED 327k. Vendors with no
  balance are not auto-added — that would mean ~700 empty rows. Classify an
  auto-added vendor via `mapping.EXTRA_CATEGORIES`, or promote it into
  `SUPPLIERS`. The app lists them under "Auto-added from BC".
- **Credit balances are shown, in red parentheses.** The original template
  rendered anything not strictly positive as an em dash, so a supplier we'd
  overpaid vanished from the Outstanding column, the "has balance" filter and
  the count. Charts stay positive-only on purpose: both answer "who do we owe",
  and a doughnut cannot represent a negative.
- **Invoiced / Paid are scoped to these suppliers' full BC history.** BC holds all
  Muraba AP back to 2013 (645.9M gross across 742 vendors); restricting to the
  dashboard's supplier list gives 261.7M / 213.3M against the statements'
  264.5M / 215.7M. Paid % lands on 81.5%, same as before.
- **Open invoices are now itemised.** The original's `opens` arrays were all
  empty, so every supplier showed "summary balance only". BC exposes an `Open`
  flag — 115 open items now appear.
- **Payment speed is an estimate.** BC does not publish which payment settled
  which invoice, so payments are FIFO-matched to each vendor's oldest open
  invoices. Ask the BC admin to expose `Closed_at_Date` and `Closed_by_Entry_No`
  on the `VendorLedgerEntries` web service (or publish Detailed Vendor Ledger
  Entries, table 380) and replace `transform._fifo_pairs` with the real link.
  Figures moved from 69d/64% on-time to 93d/56% because the scope is now all
  history rather than 9 suppliers.
- **Contract vs Variation was removed.** The original statement-based dashboard
  carried the split because the SOA documents stated it; BC has no equivalent
  field, so the rebuild inferred it by keyword-matching invoice descriptions.
  That produced authoritative-looking figures from a guess, so it is gone.
  `BIFURCATE_SUPPLIERS` is now empty -- put supplier names back only if a real
  source appears (a BC dimension, or a flag on the invoice line).
- **Sales agents are manual.** Abhilash, Eoghan and Marius are staff, not vendors:
  BC never sees an invoice from them. GL 21014 holds commission *paid* but has no
  agent dimension (only 7 of 99 postings can be attributed by name), and
  commission *earned* is a Finance entitlement that isn't in BC at all. Both
  figures therefore live in `agents_manual.json` and need updating each period;
  the app shows GL attribution beside them as a cross-check.
- **Trend chart is capped** at the last 13 quarters (`transform.TREND_QUARTERS`) to
  match the original; BC history would otherwise stretch to 48 quarters.
- Entries with implausible posting dates are skipped — BC contains a few dated
  2029 and 3035.

## Needs a human decision

See `mapping.REVIEW`, surfaced in the app's "Needs review" panel:

- **Electra Marquees** — statement showed AED 425,375 outstanding, BC shows nil.
- **Dubai Water Canal** — BC is exactly 2× the statement (287,185 vs 143,592).
- **Nakheel — Palm Jumeirah** — statement showed 78,886; both candidate vendors
  are nil in BC (`VLLC0216 Nakheel` vs `VLLC0228 The Palm Jumeirah Co LLC`).
- **Sukoon Insurance** — small credit balance, -131 vs BC -1,471.

`Electra Exhibitions` and `Lucretia Real Estate Broker` have vendor cards but no
posted entries, so they render as zero — same as the original.

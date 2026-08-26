# Supplier Outstanding — 100% from Business Central

The old statement-derived `Supplier_Dashboard.html` is a visual **template
only** (`template.html`, with `__DATA_JSON__` etc. placeholders). Not a single
value on the live page comes from it. Everything is pulled from BC on refresh:

| Element | BC source |
|---|---|
| Which vendors appear | every `Vendor_No` in `VendorLedgerEntries` with non-zero money |
| Names | BC `Vendor_Name`, verbatim |
| Categories | name of the vendor's dominant G/L cost account (`PostedPurchaseInvoiceLines` → `Chart_of_Accounts`) |
| Invoiced / Paid / Outstanding | ledger credit/debit/`Remaining_Amt_LCY` columns (credit memos netted off invoiced) |
| Open invoices, printable SOA ledgers | the same ledger entries |
| As-of date | latest sane posting date |

## Money rules

```
outstanding = -sum(Remaining_Amt_LCY)
invoiced    =  sum(Credit_Amount_LCY) - credit-memo debits
paid        =  sum(Debit_Amount_LCY)  - credit-memo debits
```

Never filter on `Document_Type` — blank on ~45% of entries (journal-posted).
BC keeps AP balances negative; everything is sign-flipped for display.
Entries with implausible posting dates (2029/3035 typos) are skipped.

## Category derivation

Purchase invoice lines record the G/L account each cost hits; the account's
name (Chart of Accounts) is the category, with trailing project qualifiers
trimmed (" - Muraba Veil"). Mechanics accounts — CWIP 24810, advances 24420,
prepaid 22300, accruals 51300, owner's account 30800 — are skipped when a real
cost line exists; a vendor with only mechanics postings shows that account as
its category rather than an invented label. `mapping.py` holds these reading
rules plus dated client instructions (currently one: Electra Marquees →
Marketing Cost; BC has no invoice lines for it).

## Not available from BC (told to the client, not backfilled)

1. **In-house sales-agent commission** (Abhilash / Eoghan / Marius, previously
   ~AED 647k) — staff, not vendors; earned exists only in Finance's manual
   sheet; GL 21014 has no agent dimension. **Excluded** until it lives in BC.
2. **Exact invoice→payment matching** — the published feed omits
   `Closed_at_Date`/`Closed_by_Entry_No`, so Payment Performance is a FIFO
   estimate. A small BC-side change (publish those fields) makes it exact.
3. **Categories for journal-only vendors** (~305, mostly settled history) —
   no invoice lines, so no cost account to derive from: shown *Uncategorised*.
4. **Contract vs Variation split** — no BC field; removed rather than inferred.

## Run / deploy

Local: `streamlit run app.py --server.port 8783` (secret auto-read from the
G-drive credentials note; `dev_bypass` skips nothing — there is no app password,
access is via the Muraba Veil Apps landing page).

Cloud (repo `muhammadamirkhan/muraba-supplier-outstanding`, private; app set to
public — the one-private-app slot belongs to muraba-cashflow): Secrets needs
only `bc_client_secret`. The old `[agents]` block is no longer read.

Files: `app.py` (shell + panels), `bc.py` (OAuth + OData reads, read-only),
`transform.py` (all money/category rules), `mapping.py` (BC reading rules +
client instructions), `template.html` (layout).

## Tools

`tools/` holds read-only scripts for verifying the dashboard against BC —
health check, per-supplier tag audit trail, raw ledger dump, the category CSV
export, and a pre-push pipeline test. See `tools/README.md`.

## Everything Suppliers-related lives in this folder

App (`app.py`, `bc.py`, `transform.py`, `mapping.py`, `template.html`),
verification tools (`tools/`), the category export (`supplier_categories.csv`),
Cloud secrets (`cloud_secrets.toml`, gitignored), and the original reference
dashboard (`Supplier_Dashboard.html`, gitignored — kept for layout reference
only; no value on the live page comes from it).

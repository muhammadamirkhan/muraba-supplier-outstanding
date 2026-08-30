# Supplier Outstanding — 100% from Business Central

The old statement-derived `Supplier_Dashboard.html` is a visual **template
only** (`template.html`, with `__DATA_JSON__` etc. placeholders). Not a single
value on the live page comes from it. Everything is pulled from BC on refresh:

| Element | BC source |
|---|---|
| Which vendors appear | every `Vendor_No` in `VendorLedgerEntries` with non-zero money |
| Names | BC `Vendor_Name`, verbatim |
| Categories | name of the vendor's dominant G/L cost account (`PostedPurchaseInvoiceLines` → `Chart_of_Accounts`) |
| Invoiced / Paid / Outstanding | signed `Amount_LCY` split by sign, plus `Remaining_Amt_LCY` (credit memos netted off invoiced) |
| Open invoices, printable SOA ledgers | the same ledger entries |
| As-of date | latest sane posting date |

## Money rules

```
invoiced    = -sum(Amount_LCY) where Amount_LCY < 0   (charged to us)
              less credit memos, which cancel part of a charge
paid        =  sum(Amount_LCY) where Amount_LCY > 0   (settled), memos excluded
outstanding = -sum(Remaining_Amt_LCY)
```

Use the **signed amount**, never the Credit/Debit columns: BC books some
reversing journals with negative debits *and* negative credits, which makes a
literal sum of those columns come out negative on both lines. `build_ledger`
must use the same basis or statement totals stop reconciling to the register.

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

## Not available from BC (verified, not assumed)

Each point was checked against the live company with `tools/verify_claims.py`.

1. **In-house sales-agent commission.** Agents are employees, not vendors, so they
   have no vendor account and no AP entry. Commission *paid* IS in BC (G/L 21014)
   and can be attributed per agent via the `UNITNAME` dimension joined to
   `BookingAgreement.Sales_Person_Name` — about 61% of that account carries a unit,
   and the account also holds brokerage commission, split by the `PAYMENTPLAN`
   dimension. What is missing is commission **earned but unpaid**: 21014 is a
   payment/clearing account (98% debits, no accrual), so entitlement lives only in
   Finance's manual schedule. Outstanding = earned − paid, so it cannot come from
   BC. Excluded rather than estimated.
2. **Exact payment timing.** The published Vendor Ledger Entries service exposes 26
   fields; `Closed at Date`, `Closed by Entry No.`, `Closed by Amount` and
   `Applies-to ID` are not among them, and no other published service carries them
   (Detailed Vendor Ledger Entries is not published; the Power BI vendor feed has
   four fields). Payment speed is therefore a FIFO estimate.
3. **Contract versus variation.** AP invoice lines carry unit (`Shortcut Dimension
   1`) and project (`Shortcut Dimension 2`) dimensions but nothing separating
   contract from variation; 33 lines mention it in free text only. Not reported.
4. **Four invalid-date entries** — `PPI000424`/`PPCM000028` (Vivium, 2029) and
   `PPI000941`/`PPCM000105` (Google, 3035). Each is an invoice + matching credit
   memo netting to nil with no remaining balance, so no balance is affected.

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

## Tabs

**Supplier Register** — the KPI strip, charts, payment performance and the
register itself.

**Statement of Account & Ageing** — payables ageing for the whole book
(0-30 / 31-60 / 61-90 / 91-180 / 181-360 / 360+, switchable between invoice-date
and due-date basis), plus the Statement of Account.

The statement reproduces the first sheet of the client's `Zetas Zemin_ SOA.xlsx`
exactly: the eight columns of its row 4 — Invoice No, Invoice Date, Invoice
Amount, Payment Date, Payment Amount, Balance, Description, Remarks — dates as
`d-mmm-yy`, amounts in the workbook's accounting format (no decimals, zero as a
dash, negatives in parentheses), a part-payment continuation row with the
invoice columns left blank, then `Total - AED` and `% of Amount paid`.
Remarks carries BC's document number: the workbook leaves it blank on data rows,
and it keeps a posting traceable without adding a column.

**Statements are produced for Zetas only**, per `mapping.SOA_SUPPLIERS`. That
format was agreed for Zetas; add a vendor number to the set once its format is
confirmed. Suppliers without a statement have no print button on the register —
their entries are on the Transactions tab and their balances on the register.
The VAT lines below the workbook's table (Outstanding VAT Amount) are not
reproduced: BC holds no VAT figure for them.

A `360+` bucket is added beyond the five requested: roughly AED 7.8m of open
items are older than 360 days and would otherwise be missing from a table that
is meant to total the payable. Buckets always sum to Total Outstanding.

**Transactions** — every Vendor Ledger Entry for a supplier, as booked: entry
no, posting/document/due dates, type, the supplier's invoice number, BC document
no, description, currency, debit, credit, amount (LCY), remaining and the open
flag, with source/reason/purchaser/payment-discount date/transaction no/
dimension set/original amount behind an "All BC fields" toggle. Nothing is
paired or netted here — that is what the SOA tab does. Filters: supplier search,
a free-text filter across the rows, and open-items-only. Debit, credit and
remaining totals follow the filtered set, and remaining ties to the register.

Rows travel as plain arrays against a header list rather than objects; at ~11k
entries the repeated keys would roughly double the payload (currently 3.7 MB).

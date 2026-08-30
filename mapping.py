"""Rules for deriving the register from Business Central. No data lives here.

The old statement-derived HTML is a visual TEMPLATE only. Everything shown --
which vendors appear, their names, their categories, every amount -- comes from
BC at refresh time:

  vendors     = every Vendor_No in the ledger with non-zero money
  names       = BC Vendor_Name, verbatim
  categories  = the NAME of the vendor's dominant G/L cost account, taken from
                the Chart of Accounts (purchase invoice lines record which
                account each cost posts to)

What this module holds is judgment about HOW to read BC, not values:
  * which accounts are balance-sheet mechanics rather than cost categories
  * cosmetic trimming of account names for display
  * explicit client instructions, labelled as such
"""

# Accounts that say nothing about what a vendor does -- posting mechanics.
# Skipped when picking the dominant account; if a vendor has ONLY these, the
# mechanics account itself becomes the category (still 100% BC) rather than
# inventing anything.
MECHANICS_ACCOUNTS = {
    "24810",  # Project cost CWIP - Muraba Veil
    "24420",  # Advance to Contractors
    "22300",  # Prepaid Expense
    "51300",  # Accrued Expense
    "30800",  # Owner's Current Account
}

# Purely cosmetic: trailing project qualifiers stripped from account names so
# 21012 "Marketing Cost - Muraba Veil" and 78100 "Marketing Cost" read as one
# category. The substance of the name is untouched.
_TRIM_SUFFIXES = (" - Muraba Veil", " - Veil Plot", " - Muraba Dia", " - Muraba")

UNCATEGORISED = "Uncategorised"


def clean_category(account_name):
    s = (account_name or "").strip()
    for suf in _TRIM_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s or UNCATEGORISED


# Client instructions -- the only human-set categories, each dated and sourced.
# These are NOT from the reference HTML.
CLIENT_CATEGORY_OVERRIDES = {
    # 2026-08-04, client: "Electra Marquees should be Marketing". BC holds no
    # invoice lines for this vendor (journal-only), so BC offers no category.
    "VLLC0396": "Marketing Cost",
}


# --------------------------------------------------------------------------
# Statement of Account availability
#
# The SOA is rendered in the exact format of the client's own workbook
# (Zetas Zemin_ SOA.xlsx, first sheet). That format was signed off for Zetas
# only, so the statement is offered for Zetas alone until the client confirms
# it suits the rest. Every other supplier still has its full transaction list
# on the Transactions tab and its balances on the register.
#
# Add a vendor number here once its statement format is agreed.
# --------------------------------------------------------------------------
SOA_SUPPLIERS = {
    "VLLC0485",   # Zetas Zemin Teknolojisi A.S Dubai Branch
}

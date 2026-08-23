"""Dashboard supplier name -> Business Central vendor.

Curated by hand against the BC vendor list. Keyed on Vendor_No (VLLC####), NOT
on name: BC uses legal names ("Zetas Zemin Teknolojisi A.S Dubai Branch") and
carries typos ("XOXO Real Esatate", "Geoestate" vs "Geostate"), so every fuzzy
matcher tried mis-assigned brokers on the generic words "Real Estate"/"Properties".

CATEGORY is Muraba's own grouping. BC has no category field on the vendor, but
the books do reveal it: purchase invoice lines carry the G/L account, and
Muraba's chart of accounts has a project cost line per category --

    21011 Legal & Admin        21012 Marketing Cost      21013 Design & Supervision
    21014 Sales Commission     21016 Construction        21017 Service Charges
    21018 Project Management   21020 DWTC Sales Gallery Fitout

Tags below were audited against each supplier's dominant project account. Ignore
24810 (Project cost CWIP), 22300 (Prepaid) and 51300 (Accrued) when judging --
those are balance-sheet mechanics, not cost categories. New vendors default to
"Other".

REVIEW flags a row whose BC balance disagrees with the original statement; see
the notes at the bottom.
"""

# dashboard name -> (BC Vendor_No, category)
SUPPLIERS = {
    # ---- Design & Supervision ----------------------------------------------
    # These four bill overwhelmingly to G/L 21013 "Design & Supervision - Muraba
    # Veil" (Omnium 100%, Arup 77%, RCR 68%, WSP 60%), which is a separate cost
    # line from Project Management in Muraba's own chart of accounts.
    "WSP Middle East":            ("VLLC0393", "Design & Supervision"),
    "Arup Gulf Limited":          ("VLLC0366", "Design & Supervision"),
    "RCR Arquitectes":            ("VLLC0253", "Design & Supervision"),
    "Omnium International":       ("VLLC0479", "Design & Supervision"),
    # ---- Project Management -------------------------------------------------
    # TrafQuest bills 64% to G/L 21018 "Project Management Cost - Muraba Veil".
    "TrafQuest":                  ("VLLC0358", "Project Management"),
    # ---- Construction ------------------------------------------------------
    "Zetas Zemin":                ("VLLC0485", "Construction"),
    "RNS Technical Services":     ("VLLC0446", "Construction"),
    "BAUER International":        ("VLLC0421", "Construction"),
    "Electra Exhibitions":        ("VLLC0460", "Construction"),
    "Enjay Engineering":          ("VLLC0119", "Construction"),
    "Titans MEP Contracting":     ("VLLC0405", "Construction"),
    "Geostate Survey Services":   ("VLLC0497", "Legal"),
    # ---- Marketing ---------------------------------------------------------
    "Electra Marquees":           ("VLLC0396", "Marketing"),
    "Pentagram":                  ("VLLC0360", "Marketing"),
    "Bureau of Visual Affairs":   ("VLLC0462", "Marketing"),
    "Zaina International":        ("VLLC0313", "Marketing"),
    "Flick Tech":                 ("VLLC0474", "Marketing"),
    "Luxhabitat FZ LLC":          ("VLLC0481", "Marketing"),
    "LUUX Digital Media":         ("VLLC0470", "Marketing"),
    "Marchmade":                  ("VLLC0197", "Marketing"),
    "BeWunder":                   ("VLLC0459", "Construction"),
    "Joseph Graphics":            ("VLLC0397", "Marketing"),
    "Richard Bryant Photography": ("VLLC0543", "Marketing"),
    "Flint Culture MENA Marketing": ("VLLC0388", "Marketing"),
    # ---- Legal -------------------------------------------------------------
    "Al Tamimi & Co":             ("VLLC0037", "Legal"),
    "King & Spalding":            ("VLLC0430", "Legal"),
    # ---- Community / Service Charges --------------------------------------
    "Dubai Water Canal":          ("VLLC0595", "Community / Service Charges"),
    "Nakheel — Palm Jumeirah": ("VLLC0216", "Community / Service Charges"),
    # ---- Insurance / Fit-out ----------------------------------------------
    "Sukoon Insurance PJSC":      ("VLLC0427", "Insurance"),
    "Burmester Home Audio":       ("VLLC0534", "Fit-out / Supply"),
    # ---- Real Estate Brokerage --------------------------------------------
    "ONG Real Estate":            ("VLLC0593", "Real Estate Brokerage"),
    "Knight Frank Real Estate Brokerage":     ("VLLC0539", "Real Estate Brokerage"),
    "XOXO Real Estate Brokerage":             ("VLLC0498", "Real Estate Brokerage"),
    "Premier Estates Real Estate Brokerage":  ("VLLC0244", "Real Estate Brokerage"),
    "Metrika Real Estate Brokerage":          ("VLLC0558", "Real Estate Brokerage"),
    "Ninety Degree South Real Estate Broker": ("VLLC0559", "Real Estate Brokerage"),
    "Lucretia Real Estate Broker":            ("VLLC0757", "Real Estate Brokerage"),
    "Epsace Real Estate Broker":              ("VLLC0717", "Real Estate Brokerage"),
    "Blackstone Capital Properties":          ("VLLC0738", "Real Estate Brokerage"),
    "Nine Estate Properties":                 ("VLLC0546", "Real Estate Brokerage"),
    "McCone Properties":                      ("VLLC0467", "Real Estate Brokerage"),
    "Metropolitan Premium Properties":        ("VLLC0206", "Real Estate Brokerage"),
    "DAX (AX Capital) Real Estate Brokerage": ("VLLC0646", "Real Estate Brokerage"),
    "Seven Luxury Real Estate":               ("VLLC0629", "Real Estate Brokerage"),
    "Luxury X Real Estate":                   ("VLLC0457", "Real Estate Brokerage"),
    "Insight City Real Estate":               ("VLLC0597", "Real Estate Brokerage"),
    "eXp Real Estate":                        ("VLLC0574", "Real Estate Brokerage"),
    "Roman Realty":                           ("VLLC0547", "Real Estate Brokerage"),
    "GGS Real Estate":                        ("VLLC0537", "Real Estate Brokerage"),
    "Fair Oppotunity Real Estate":            ("VLLC0493", "Real Estate Brokerage"),
}

# Muraba's own salespeople -- staff, not vendors, so they have no BC vendor
# account and are never invoiced. Paid comes from GL 21014; the earned figure is
# a manual Finance entitlement (agents_manual.json).
SALES_AGENTS = {
    "Eoghan - Sales Agent":   "Eoghan",
    "Marius - Sales Agent":   "Marius",
    "Abhilash - Sales Agent": "Abhilash",
}

AGENT_CATEGORY = "Sales Agent"
GL_INHOUSE_COMMISSION = "21014"

# --------------------------------------------------------------------------
# Auto-inclusion
#
# SUPPLIERS above is the list carried over from the original statement-based
# dashboard. BC has ~745 vendors, so scoping to that list silently hid every
# other vendor that happens to carry a balance -- the client spotted 16 of them
# (AED 327k) missing. Any BC vendor with a non-zero balance is now added
# automatically under AUTO_CATEGORY, using its BC legal name.
#
# Vendors with no balance are NOT auto-added; that would put ~700 empty rows in
# the register. So the register = the curated list (even at zero, to preserve
# the original view) + anyone else who actually owes or is owed something.
#
# To classify an auto-added vendor properly, add it to EXTRA_CATEGORIES; to
# promote it permanently, move it into SUPPLIERS above.
# --------------------------------------------------------------------------
AUTO_CATEGORY = "Other"

EXTRA_CATEGORIES = {
    # "VLLC0433": "Professional Services",
}


def category_for(vendor_no, default=None):
    return EXTRA_CATEGORIES.get(vendor_no, default or AUTO_CATEGORY)

# Dropped from the original 54: "Flint Culture MENA" was a duplicate of
# "Flint Culture MENA Marketing" (both resolve to VLLC0388) and had no
# statement on file.
DROPPED = {"Flint Culture MENA": "duplicate of Flint Culture MENA Marketing (VLLC0388)"}

# Rows where BC disagrees with the original statement -- surfaced in the app so
# they get a human decision rather than being silently papered over.
REVIEW = {
    "Electra Marquees": "statement showed AED 425,375 outstanding; BC shows nil",
    "Dubai Water Canal": "BC balance is exactly 2x the statement (287,185 vs 143,592)",
    "Nakheel — Palm Jumeirah": (
        "statement showed AED 78,886; both candidate vendors are nil in BC "
        "(VLLC0216 'Nakheel' vs VLLC0228 'The Palm Jumeirah Co LLC') -- confirm which"
    ),
    "Sukoon Insurance PJSC": "small credit balance; statement -131 vs BC -1,471",
}

# BC vendor cards that duplicate a mapped vendor. Left unmapped deliberately;
# listed so nobody wonders where they went.
KNOWN_BC_DUPLICATES = {
    "VLLC0436": "Metropolitan Premium Properties LLC (dupe of VLLC0206, no entries)",
    "VLLC0087": "DAX Real Estate One Person Company LLC (near-dupe of VLLC0646)",
    "VLLC0389": "Geoestate Survey Services (spelling variant of VLLC0497)",
    "VLLC0228": "The Palm Jumeirah Co LLC (alternative for Nakheel)",
}


def vendor_numbers():
    return [no for no, _cat in SUPPLIERS.values()]


def by_vendor_no():
    return {no: (name, cat) for name, (no, cat) in SUPPLIERS.items()}

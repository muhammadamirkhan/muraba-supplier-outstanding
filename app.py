"""Supplier Outstanding -- live from Business Central.

Renders the original Supplier_Dashboard.html unchanged (same CSS, charts, row
expansion and print-to-SOA), with its three data blobs replaced by live BC data.
Keeping the template intact is deliberate: Streamlit widgets can't reproduce the
print stylesheet, and st.data_editor can't style rows at all.
"""
import datetime as dt
import json
import pathlib

import streamlit as st

import bc
import mapping
import transform

# The dashboard must render inside an iframe: it ships its own CSS and a print
# stylesheet, both of which would collide with Streamlit's page if inlined.
# st.components.v1.html is deprecated but is still the only API that takes an
# HTML *string* -- st.iframe() wants a src URL. Resolve it defensively so a
# future Streamlit release that drops it degrades instead of crashing.
try:
    import streamlit.components.v1 as _components

    _render_iframe = _components.html
except (ImportError, AttributeError):  # pragma: no cover - version dependent
    _render_iframe = None


def render_dashboard(html: str, height: int = 4300):
    if _render_iframe is not None:
        _render_iframe(html, height=height, scrolling=True)
        return
    st.warning(
        "This Streamlit version no longer provides components.v1.html, so the "
        "dashboard is rendered inline; printing a Statement of Account may pick "
        "up the surrounding page. Pin an older streamlit in requirements.txt."
    )
    try:
        st.html(html, unsafe_allow_javascript=True)
    except TypeError:  # older signature without the javascript flag
        st.html(html)

HERE = pathlib.Path(__file__).parent
TEMPLATE = HERE / "template.html"

st.set_page_config(page_title="Supplier Outstanding", page_icon="🏗", layout="wide")


# Entry password removed: access is controlled by the Muraba Veil Apps
# landing page. Per-action passwords guarding writes are kept.


# ------------------------------------------------------------------ data layer
@st.cache_data(ttl=900, show_spinner=False)
def load(_bust: int = 0):
    token = bc.get_token()
    vle = bc.vendor_ledger_entries(token)
    try:
        lines = bc.posted_purchase_invoice_lines(token)
    except bc.BCError:
        lines = []  # descriptions/categories degrade gracefully
    try:
        coa = bc.chart_of_accounts(token)
    except bc.BCError:
        coa = {}
    return vle, lines, coa


# -------------------------------------------------------------------- controls
# Deliberately in the main area, not st.sidebar: on Streamlit 1.56 the sidebar
# renders no DOM for this app, and a full-width report reads better with a top
# control strip anyway.
try:
    vle, lines, coa = load()
except bc.BCError as e:
    st.error(f"Business Central: {e}")
    st.info(
        "The dashboard needs a valid BC client secret. Set `bc_client_secret` in "
        "Streamlit Cloud → Settings → Secrets (or .streamlit/secrets.toml locally)."
    )
    st.stop()

DATA, PERF, LEDGERS, diag = transform.build(vle, lines, coa)

latest = max(
    (str(e.get("Posting_Date") or "")[:10] for e in vle
     if e.get("Posting_Date") and str(e["Posting_Date"])[:4] <= str(dt.date.today().year)),
    default="",
)
c1, c2, c3, c4 = st.columns([1.1, 1.2, 2.2, 1.6])
with c1:
    if st.button("↻ Refresh from BC", use_container_width=True):
        load.clear()
        st.rerun()
with c2:
    asof = st.date_input(
        "Statement as of",
        value=dt.date.fromisoformat(latest) if latest else dt.date.today(),
        help="Shown in the header and on printed statements",
        label_visibility="collapsed",
    )
with c3:
    st.caption(
        f"✅ **BC live** · {diag['entries_used']:,} entries · "
        f"{diag['vendors_shown']} vendors with activity · "
        f"{diag['open_items']} open items · latest posting {latest}"
    )
with c4:
    st.caption(f"**Total outstanding** AED {diag['total_outstanding']:,.0f}")
asof_txt = asof.strftime("%d %B %Y")

n1, n2, n3 = st.columns(3)
with n1.expander("Data notes — everything from BC"):
    st.markdown(
        f"""
The reference HTML is layout only; no value on this page comes from it.

- **Vendors** = every vendor in BC's ledger with non-zero money
  ({diag['vendors_shown']} of {diag['vendors_in_ledger']} in the ledger).
- **Names** = BC `Vendor_Name`, verbatim.
- **Categories** = the name of each vendor's dominant G/L cost account
  (purchase invoice lines record the account; the Chart of Accounts names it).
  Mechanics accounts (CWIP, advances, prepaid, accruals) are skipped when a
  real cost line exists.
- **Money**: outstanding = `Remaining_Amt_LCY`; invoiced/paid from the
  credit/debit columns, credit memos netted off invoiced. FX at BC's booked rates.
- **Payment speed is estimated** (FIFO): BC doesn't publish which payment
  settled which invoice. Exact figures need the BC admin to expose
  `Closed_at_Date` / `Closed_by_Entry_No`.
- {diag['bad_date_entries']} entries skipped for implausible posting dates
  (2029/3035 typos in BC).
"""
    )

unc = diag.get("uncategorised", [])
with n2.expander(f"ℹ Not available from BC ({2 + (1 if unc else 0)})"):
    st.markdown(
        """
**For the client — BC cannot provide these, so they are not shown:**

1. **In-house sales agent commission** (Abhilash, Eoghan, Marius — previously
   AED ~647k outstanding). They are staff, not vendors: BC has no invoice from
   them, commission *earned* exists only in Finance's manual Inhouse Com sheet,
   and GL 21014 (paid) carries no agent dimension. These rows are excluded until
   the figures live in BC.
2. **Exact invoice→payment matching.** The published `VendorLedgerEntries` feed
   omits `Closed_at_Date`/`Closed_by_Entry_No`, so the Payment Performance panel
   is a FIFO estimate. A small BC-side change makes it exact.
"""
    )
    if unc:
        st.markdown(
            f"**3. Category for {len(unc)} vendors** — no posted purchase invoice "
            "lines (journal-only postings), so BC offers no cost account to derive "
            "a category from. Shown as *Uncategorised*:"
        )
        for no, nm, out in unc[:15]:
            st.markdown(f"- `{no}` {nm} — outstanding {out:,.0f}")
        if len(unc) > 15:
            st.caption(f"…and {len(unc) - 15} more (all zero/settled).")

ovr = diag.get("client_overrides", [])
with n3.expander(f"Client instructions ({len(ovr)})"):
    if not ovr:
        st.caption("None — every category is BC-derived.")
    for no, nm, cat in ovr:
        st.markdown(f"- `{no}` **{nm}** → *{cat}* (client instruction; "
                    "BC has no invoice lines for this vendor)")

# ----------------------------------------------------------------------- render
html = TEMPLATE.read_text(encoding="utf-8")
html = (
    html.replace("__DATA_JSON__", json.dumps(DATA, ensure_ascii=False))
        .replace("__PERF_JSON__", json.dumps(PERF, ensure_ascii=False))
        .replace("__LEDGERS_JSON__", json.dumps(LEDGERS, ensure_ascii=False))
        .replace("__ASOF__", asof_txt)
)
render_dashboard(html)

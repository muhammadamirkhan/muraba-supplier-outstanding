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
AGENTS_FILE = HERE / "agents_manual.json"

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
        lines = []  # descriptions are cosmetic; don't fail the page over them
    try:
        gl = bc.gl_entries_for_account(mapping.GL_INHOUSE_COMMISSION, token)
    except bc.BCError:
        gl = []
    return vle, lines, gl


def agent_paid_from_gl(gl_rows):
    """Cross-check only: attribute GL 21014 postings to an agent by name in the text.

    GL 21014 has no agent dimension, so most postings can't be attributed. This is
    shown in the sidebar next to the manual figure, never used in place of it.
    """
    paid = {short: 0.0 for short in mapping.SALES_AGENTS.values()}
    matched = 0
    for r in gl_rows:
        text = " ".join(str(r.get(k) or "") for k in ("description", "documentNumber")).lower()
        for short in paid:
            if short.lower() in text:
                paid[short] += (r.get("debitAmount") or 0) - (r.get("creditAmount") or 0)
                matched += 1
                break
    return paid, matched


def load_agents():
    """-> (earned, paid, source)

    Commission figures name individuals, so they are kept OUT of the repo.
    Preferred home is st.secrets["agents"]; agents_manual.json is a local
    convenience and is gitignored.
    """
    try:
        blob = st.secrets.get("agents", None)
        if blob:
            agents = {k: dict(v) for k, v in dict(blob).items()}
            return (
                {k: float(v.get("earned") or 0) for k, v in agents.items()},
                {k: float(v.get("paid") or 0) for k, v in agents.items()},
                "st.secrets",
            )
    except Exception:
        pass

    if not AGENTS_FILE.exists():
        st.warning(
            "No sales-agent commission figures found — those rows will read zero. "
            'Add an [agents] section to Secrets (see agents_manual.example.json).'
        )
        return {}, {}, "none"
    try:
        blob = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        st.error(f"agents_manual.json is not valid JSON ({e.msg}) — agent rows read zero.")
        return {}, {}, "none"
    agents = blob.get("agents", {})
    earned = {k: float(v.get("earned") or 0) for k, v in agents.items()}
    paid = {k: float(v.get("paid") or 0) for k, v in agents.items()}
    return earned, paid, "agents_manual.json"


# -------------------------------------------------------------------- controls
# Deliberately in the main area, not st.sidebar: on Streamlit 1.56 the sidebar
# renders no DOM for this app, and a full-width report reads better with a top
# control strip anyway.
try:
    vle, lines, gl = load()
except bc.BCError as e:
    st.error(f"Business Central: {e}")
    st.info(
        "The dashboard needs a valid BC client secret. Set `bc_client_secret` in "
        "Streamlit Cloud → Settings → Secrets (or .streamlit/secrets.toml locally)."
    )
    st.stop()

earned, agent_paid, agent_src = load_agents()
gl_paid, gl_matched = agent_paid_from_gl(gl)
DATA, PERF, LEDGERS, diag = transform.build(vle, lines, earned, agent_paid)

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
        f"{diag['vendors_matched']}/{len(mapping.SUPPLIERS)} vendors matched · "
        f"{diag['open_items']} open items · latest posting {latest}"
    )
with c4:
    st.caption(f"**Total outstanding** AED {diag['total_outstanding']:,.0f}")
asof_txt = asof.strftime("%d %B %Y")

n1, n2, n3, n4 = st.columns(4)
with n1.expander("Data notes"):
    st.markdown(
        f"""
- **Outstanding** ties to the supplier statements (BC `Remaining_Amt_LCY`).
- **Invoiced / Paid** are these {len(mapping.SUPPLIERS)} suppliers' full BC history,
  so they read higher than the old statement-derived figures.
- **Payment speed is estimated** (FIFO): BC doesn't publish which payment settled
  which invoice. Ask the BC admin to expose `Closed_at_Date` and
  `Closed_by_Entry_No` for exact figures.
- **Sales agents** aren't BC vendors — both earned and paid come from
  `agents_manual.json` (Finance's Inhouse Com sheet).
- FX uses BC's booked rates, not the old indicative GBP 4.65 / EUR 4.00.
- {diag['bad_date_entries']} entries skipped for implausible posting dates.
"""
    )

auto = diag.get("auto_added", [])
with n2.expander(f"➕ Auto-added from BC ({len(auto)})"):
    if not auto:
        st.caption("Every BC vendor carrying a balance is on the curated list.")
    else:
        st.caption(
            f"Vendors outside the original supplier list that carry a balance — "
            f"AED {diag['auto_added_total']:,.0f} in total. They're included "
            f'automatically under "{mapping.AUTO_CATEGORY}"; add them to '
            f"`EXTRA_CATEGORIES` in mapping.py to classify them properly."
        )
        for no, nm, out in auto:
            st.markdown(f"- `{no}` **{nm}** — {out:,.0f}")

flagged = [n for n in mapping.REVIEW if n in DATA]
with n3.expander(f"⚠ Needs review ({len(flagged)})"):
    for n in flagged:
        st.markdown(f"**{n}** — {mapping.REVIEW[n]}")
    if diag["vendors_missing"]:
        st.markdown(
            "**No BC entries at all:** " + ", ".join(diag["vendors_missing"])
            + " — vendor cards exist but nothing has been posted."
        )
    if mapping.DROPPED:
        for k, why in mapping.DROPPED.items():
            st.markdown(f"**{k}** — dropped, {why}")

with n4.expander("Sales agents (manual)"):
    st.caption(
        f"Not BC vendors. Figures read from **{agent_src}**; GL "
        f"{mapping.GL_INHOUSE_COMMISSION} attribution is shown only as a cross-check "
        f"({gl_matched} of {len(gl)} postings could be attributed by name)."
    )
    for short in mapping.SALES_AGENTS.values():
        st.markdown(
            f"**{short}** — earned {earned.get(short, 0):,.0f} · "
            f"paid {agent_paid.get(short, 0):,.0f} "
            f"<span style='color:#888'>(GL says {gl_paid.get(short, 0):,.0f})</span>",
            unsafe_allow_html=True,
        )
    missing = [s for s in mapping.SALES_AGENTS.values() if not earned.get(s)]
    if missing:
        st.warning("Earned not set for: " + ", ".join(missing))


# ----------------------------------------------------------------------- render
html = TEMPLATE.read_text(encoding="utf-8")
html = (
    html.replace("__DATA_JSON__", json.dumps(DATA, ensure_ascii=False))
        .replace("__PERF_JSON__", json.dumps(PERF, ensure_ascii=False))
        .replace("__LEDGERS_JSON__", json.dumps(LEDGERS, ensure_ascii=False))
        .replace("__ASOF__", asof_txt)
)
render_dashboard(html)

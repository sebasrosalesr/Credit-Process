# app.py
from datetime import datetime, date
from dateutil.parser import parse
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# =============================
# Streamlit App Configuration
# =============================
st.set_page_config(page_title="🧾 Credit Aging & CR Tracker", layout="wide")
st.title("🧾 Credit Aging & CR Tracker")
st.caption("Loads tickets from Firebase, computes aging, and separates Pending-CR vs Has-CR with status checks.")

# =============================
# Expected Columns (flexible)
# =============================
EXPECTED_COLUMNS = [
    "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
    "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
    "Reason for Credit", "Record ID", "Requested By", "Sales Rep", "Status",
    "Ticket Number", "Unit Price", "Type", "RTN_CR_No", "Close date", "Resolution date"
]

# =============================
# Firebase Admin Init
# Provide your service account in .streamlit/secrets.toml (see sample below)
# =============================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(
        cred,
        {"databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"}
    )
ref = db.reference("credit_requests")

# =============================
# Helpers
# =============================
def safe_parse_force_string(x):
    """Force parse dates using dateutil; return NaT if it fails."""
    try:
        return parse(str(x), fuzzy=True)
    except Exception:
        return pd.NaT

def format_money_series(s: pd.Series) -> pd.Series:
    return s.map(lambda v: f"${v:,.2f}" if pd.notna(v) else "")

def nonempty(series: pd.Series) -> pd.Series:
    """True if non-empty after stripping; safe on NaN."""
    return series.fillna("").astype(str).str.strip().ne("")

@st.cache_data(ttl=180)
def fetch_credits_df() -> pd.DataFrame:
    """Fetch all records from Firebase, coerce schema, parse dates, compute aging/buckets."""
    data = ref.get() or {}
    rows = []
    if isinstance(data, dict):
        for key, item in data.items():
            rec = {col: item.get(col, None) for col in EXPECTED_COLUMNS}
            rec["Record ID"] = key  # keep Firebase key
            rows.append(rec)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Parse "Date"
    df["Date_parsed"] = df["Date"].apply(safe_parse_force_string)
    df = df.dropna(subset=["Date_parsed"]).copy()

    # Age in days
    today = pd.Timestamp(date.today())
    df["Age (days)"] = (today - df["Date_parsed"]).dt.days

    # Optional: parse close/resolution dates if present
    if "Close date" in df.columns:
        df["Close_date_parsed"] = df["Close date"].apply(safe_parse_force_string)
    if "Resolution date" in df.columns:
        df["Resolution_date_parsed"] = df["Resolution date"].apply(safe_parse_force_string)

    # Aging buckets
    bins = [-1, 7, 14, 30, 60, 90, 180, 365, 10_000]
    labels = ["0-7", "8-14", "15-30", "31-60", "61-90", "91-180", "181-365", "365+"]
    df["Aging Bucket"] = pd.cut(df["Age (days)"], bins=bins, labels=labels)

    # Numeric for money
    if "Credit Request Total" in df.columns:
        df["Credit Request Total"] = pd.to_numeric(df["Credit Request Total"], errors="coerce")

    # Remove dup column names (defensive)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    return df

# =============================
# Sidebar Controls
# =============================
with st.sidebar:
    st.header("Filters")
    min_age = st.number_input("Minimum Age (days)", min_value=0, value=0, step=1)
    start_date = st.date_input("Start Date (optional)", value=None)
    end_date   = st.date_input("End Date (optional)", value=None)
    only_with_rtn    = st.checkbox("Only records WITH RTN_CR_No", value=False)
    only_without_rtn = st.checkbox("Only records WITHOUT RTN_CR_No", value=False)

    closed_labels_default = ["closed", "resolved", "completed", "done"]
    closed_labels = st.text_input(
        "Closed status keywords (comma-separated, lowercase)",
        value=",".join(closed_labels_default)
    )
    if st.button("🔄 Refresh data cache"):
        st.cache_data.clear()

with st.spinner("Loading data…"):
    df = fetch_credits_df()

if df.empty:
    st.info("No records found in Firebase path `credit_requests`.")
    st.stop()

# =============================
# Apply global filters
# =============================
mask = pd.Series(True, index=df.index)
if min_age > 0:
    mask &= df["Age (days)"] >= min_age
if start_date:
    mask &= df["Date_parsed"] >= pd.Timestamp(start_date)
if end_date:
    mask &= df["Date_parsed"] <= pd.Timestamp(end_date)
if "RTN_CR_No" in df.columns:
    if only_with_rtn:
        mask &= nonempty(df["RTN_CR_No"])
    if only_without_rtn:
        mask &= ~nonempty(df["RTN_CR_No"])

df_view = df[mask].copy()

# =============================
# Summary Metrics
# =============================
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total rows (dated)", f"{len(df):,}")
with col2:
    st.metric("Filtered rows", f"{len(df_view):,}")
with col3:
    st.metric("Max age (days)", f"{int(df_view['Age (days)'].max()) if len(df_view) else 0}")
with col4:
    total_amt = df_view["Credit Request Total"].sum(skipna=True) if "Credit Request Total" in df_view.columns else 0
    st.metric("Sum Credit Request Total", f"${total_amt:,.2f}")

st.markdown("---")

# =============================
# Split into Pending-CR vs Has-CR
# =============================
# Build a safe RTN series even if the column is missing
rtn_series = df_view["RTN_CR_No"] if "RTN_CR_No" in df_view.columns else pd.Series("", index=df_view.index)
df_view["Has CR No"] = nonempty(rtn_series)

# --- 1) Pending CR number (needs follow-up)
pending = df_view[~df_view["Has CR No"]].copy()
pending["Action"] = "Pending CR number — please follow up"
pending_cols = [c for c in [
    "Age (days)", "Aging Bucket", "Date_parsed",
    "Ticket Number", "Invoice Number", "Item Number",
    "Requested By", "Sales Rep", "Status", "Record ID", "Action"
] if c in pending.columns]
pending = pending.sort_values(["Age (days)", "Date_parsed"] , ascending=[False, True])

# --- 2) Has CR number (check status / closed)
with_cr = df_view[df_view["Has CR No"]].copy()
closed_set = {s.strip().lower() for s in closed_labels.split(",") if s.strip()}
with_cr["Is Closed"] = with_cr["Status"].fillna("").str.lower().isin(closed_set) if "Status" in with_cr.columns else False
with_cr["Action"] = with_cr["Is Closed"].map({True: "Closed ✅", False: "Has CR — check status"})

with_cr_cols = [c for c in [
    "Age (days)", "Aging Bucket", "Date_parsed",
    "Ticket Number", "Invoice Number", "Item Number",
    "RTN_CR_No", "Status", "Requested By", "Sales Rep", "Record ID", "Action"
] if c in with_cr.columns]

# Optional: show time-to-close or time-to-resolve if dates exist
if "Close_date_parsed" in with_cr.columns and with_cr["Close_date_parsed"].notna().any():
    with_cr["Days to Close"] = (with_cr["Close_date_parsed"] - with_cr["Date_parsed"]).dt.days
    if "Days to Close" not in with_cr_cols:
        with_cr_cols.insert(3, "Days to Close")
elif "Resolution_date_parsed" in with_cr.columns and with_cr["Resolution_date_parsed"].notna().any():
    with_cr["Days to Resolve"] = (with_cr["Resolution_date_parsed"] - with_cr["Date_parsed"]).dt.days
    if "Days to Resolve" not in with_cr_cols:
        with_cr_cols.insert(3, "Days to Resolve")

# Order: show open first, then closed; within each, oldest first
with_cr = with_cr.sort_values(["Is Closed", "Age (days)"], ascending=[True, False])

# =============================
# Display Sections + Downloads
# =============================
st.subheader(f"🚩 Pending CR Number — Follow Up ({len(pending):,})")
if len(pending):
    out_pending = pending[pending_cols].rename(columns={"Date_parsed": "Date"})
    st.dataframe(out_pending, use_container_width=True)
    buf1 = io.StringIO()
    out_pending.to_csv(buf1, index=False)
    st.download_button(
        "⬇️ Download Pending List (CSV)",
        data=buf1.getvalue(),
        file_name=f"pending_cr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
else:
    st.success("All dated tickets have a CR number. 🎉")

st.subheader(f"📘 Has CR Number — Status Check ({len(with_cr):,})")
if len(with_cr):
    if "Credit Request Total" in with_cr.columns:
        with_cr["Credit Request Total"] = format_money_series(with_cr["Credit Request Total"])
        if "Credit Request Total" not in with_cr_cols:
            with_cr_cols.insert(min(6, len(with_cr_cols)), "Credit Request Total")

    out_hascr = with_cr[with_cr_cols].rename(columns={"Date_parsed": "Date"})
    st.dataframe(out_hascr, use_container_width=True)
    buf2 = io.StringIO()
    out_hascr.to_csv(buf2, index=False)
    st.download_button(
        "⬇️ Download Has-CR List (CSV)",
        data=buf2.getvalue(),
        file_name=f"has_cr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
else:
    st.info("No records with CR number in the current filter.")

# =============================
# Optional: Full raw view
# =============================
with st.expander("🔎 Full filtered table (raw)"):
    master_cols = [c for c in [
        "Age (days)", "Aging Bucket", "Date_parsed",
        "Ticket Number", "Invoice Number", "Item Number",
        "Credit Request Total", "RTN_CR_No",
        "Requested By", "Sales Rep", "Status", "Record ID"
    ] if c in df_view.columns]
    raw_out = df_view[master_cols].rename(columns={"Date_parsed": "Date"}).copy()
    if "Credit Request Total" in raw_out.columns:
        raw_out["Credit Request Total"] = format_money_series(
            pd.to_numeric(df_view["Credit Request Total"], errors="coerce")
        )
    st.dataframe(raw_out, use_container_width=True)

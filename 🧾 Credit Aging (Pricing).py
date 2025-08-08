from datetime import datetime, date
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# =========================
# Streamlit + Firebase Init
# =========================
st.set_page_config(page_title="🧾 Credit Aging (Pricing)", layout="wide")
st.title("🧾 Credit Aging (Pricing)")
st.caption("Shows credits with a valid Date, computes aging (days), oldest first. Filters + CSV export.")

EXPECTED_COLUMNS = [
    "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
    "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
    "Reason for Credit", "Record ID", "Requested By", "Sales Rep", "Status",
    "Ticket Number", "Unit Price", "Type", "RTN_CR_No"
]

# --- Firebase init ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
    })
ref = db.reference("credit_requests")

# =========================
# Helpers
# =========================
@st.cache_data(ttl=120)
def fetch_credits_df() -> pd.DataFrame:
    """Fetch all records, coerce to EXPECTED_COLUMNS, parse date, compute age & buckets."""
    data = ref.get() or {}
    rows = []
    for key, item in data.items():
        rec = {col: item.get(col, None) for col in EXPECTED_COLUMNS}
        rec["Record ID"] = key  # ensure we always keep the Firebase key
        rows.append(rec)

    df = pd.DataFrame(rows)

    # Robust date parsing
    # Accepts formats like YYYY-MM-DD, MM/DD/YYYY, with/without time
    df["Date_parsed"] = pd.to_datetime(df.get("Date"), errors="coerce", infer_datetime_format=True)

    # Keep only rows with a valid date
    df = df[~df["Date_parsed"].isna()].copy()

    # Age (days)
    today = pd.Timestamp(date.today())  # normalized to midnight
    df["Age (days)"] = (today - df["Date_parsed"]).dt.days

    # Aging buckets
    bins = [-1, 7, 14, 30, 60, 90, 180, 365, 10_000]
    labels = ["0-7", "8-14", "15-30", "31-60", "61-90", "91-180", "181-365", "365+"]
    df["Aging Bucket"] = pd.cut(df["Age (days)"], bins=bins, labels=labels)

    # Sort: oldest first
    df = df.sort_values(["Age (days)", "Date_parsed"], ascending=[False, True])

    # Normalize money column (numeric for later pretty print)
    if "Credit Request Total" in df.columns:
        df["Credit Request Total"] = pd.to_numeric(df["Credit Request Total"], errors="coerce")

    # Ensure no duplicate column names (defensive)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    return df

def format_money_series(s: pd.Series) -> pd.Series:
    return s.map(lambda v: f"${v:,.2f}" if pd.notna(v) else "")

# =========================
# Load + Filters
# =========================
with st.spinner("Loading credits…"):
    df = fetch_credits_df()

c1, c2, c3, c4 = st.columns(4)
with c1:
    min_age = st.number_input("Minimum age (days)", min_value=0, value=0, step=1)
with c2:
    start_date = st.date_input("Start Date (optional)", value=None)
with c3:
    end_date = st.date_input("End Date (optional)", value=None)
with c4:
    must_have_cr = st.checkbox("Only rows with RTN_CR_No", value=False)

mask = pd.Series(True, index=df.index)
if min_age > 0:
    mask &= df["Age (days)"] >= min_age
if start_date:
    mask &= df["Date_parsed"] >= pd.Timestamp(start_date)
if end_date:
    mask &= df["Date_parsed"] <= pd.Timestamp(end_date)
if must_have_cr and "RTN_CR_No" in df.columns:
    mask &= df["RTN_CR_No"].astype(str).str.strip().ne("").fillna(False)

df_view = df[mask].copy()

# Display columns (keep Date_parsed name to avoid duplicates)
desired_cols = [
    "Age (days)", "Aging Bucket", "Date_parsed",
    "Ticket Number", "Invoice Number", "Item Number",
    "Credit Request Total", "RTN_CR_No",
    "Requested By", "Sales Rep", "Status", "Record ID",
]
show_cols = [c for c in desired_cols if c in df_view.columns]

st.subheader(f"Results ({len(df_view):,}) — Oldest on top")

if show_cols:
    # Pretty money
    if "Credit Request Total" in show_cols:
        df_view["Credit Request Total"] = format_money_series(df_view["Credit Request Total"])

    # Friendlier column label for Date_parsed
    rename_map = {"Date_parsed": "Date"}
    safe_cols = [rename_map.get(c, c) for c in show_cols]
    df_to_show = df_view[show_cols].rename(columns=rename_map)

    st.dataframe(df_to_show, use_container_width=True)

    # Download
    csv_buf = io.StringIO()
    df_to_show.to_csv(csv_buf, index=False)
    st.download_button(
        "⬇️ Download CSV",
        data=csv_buf.getvalue(),
        file_name=f"credit_aging_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
else:
    st.info("No displayable columns found.")

# =========================
# Quick Summary
# =========================
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Total rows (dated)", f"{len(df):,}")
with c2:
    st.metric("Filtered rows", f"{len(df_view):,}")
with c3:
    st.metric("Max age (days)", f"{int(df_view['Age (days)'].max()) if len(df_view) else 0}")

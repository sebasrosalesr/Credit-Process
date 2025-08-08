from datetime import datetime, date
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# ---------- CONFIG ----------
st.set_page_config(page_title="🧾 Credit Aging (Pricing)", layout="wide")

# Expected columns (to keep output consistent even if some keys are missing)
EXPECTED_COLUMNS = [
    "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
    "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
    "Reason for Credit", "Record ID", "Requested By", "Sales Rep", "Status",
    "Ticket Number", "Unit Price", "Type", "RTN_CR_No"
]

# ---------- FIREBASE INIT ----------
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
    })

ref = db.reference("credit_requests")

# ---------- HELPERS ----------
@st.cache_data(ttl=120)
def fetch_credits():
    """Fetch all credit_requests; return DataFrame with EXPECTED_COLUMNS."""
    data = ref.get() or {}
    records = []
    for key, item in data.items():
        rec = {col: item.get(col, None) for col in EXPECTED_COLUMNS}
        rec["Record ID"] = key  # ensure key is captured
        records.append(rec)
    df = pd.DataFrame(records)

    # Parse Date (robust) -> datetime
    # Common cases: 'YYYY-MM-DD', 'MM/DD/YYYY', 'YYYY-MM-DD HH:MM:SS', etc.
    df["Date_parsed"] = pd.to_datetime(df["Date"], errors="coerce", infer_datetime_format=True)

    # Compute Age (days) from today (UTC by default; OK for aging)
    today = pd.Timestamp(date.today())
    df["Age (days)"] = (today - df["Date_parsed"]).dt.days

    # Keep only rows that actually have a date
    df = df[~df["Date_parsed"].isna()].copy()

    # Optional: Aging bucket
    bins = [-1, 7, 14, 30, 60, 90, 180, 365, 10_000]
    labels = ["0-7", "8-14", "15-30", "31-60", "61-90", "91-180", "181-365", "365+"]
    df["Aging Bucket"] = pd.cut(df["Age (days)"], bins=bins, labels=labels)

    # Sort oldest first
    df = df.sort_values(["Age (days)", "Date_parsed"], ascending=[False, True])
    return df

def format_money(x):
    try:
        v = float(x)
        return f"${v:,.2f}"
    except Exception:
        return x

# ---------- UI ----------
st.title("🧾 Credit Aging (Pricing)")
st.caption("Shows credits with a valid Date, computes aging in days, and sorts by oldest first.")

with st.spinner("Loading credits…"):
    df = fetch_credits()

# Filters row
col1, col2, col3, col4 = st.columns([1,1,1,1])
with col1:
    min_age = st.number_input("Minimum age (days)", min_value=0, value=0, step=1)
with col2:
    start_date = st.date_input("Start Date (optional)", value=None)
with col3:
    end_date = st.date_input("End Date (optional)", value=None)
with col4:
    must_have_cr = st.checkbox("Only rows with RTN_CR_No", value=False)

# Apply filters
mask = pd.Series(True, index=df.index)

if min_age > 0:
    mask &= df["Age (days)"] >= min_age
if start_date:
    mask &= df["Date_parsed"] >= pd.Timestamp(start_date)
if end_date:
    mask &= df["Date_parsed"] <= pd.Timestamp(end_date)
if must_have_cr:
    mask &= df["RTN_CR_No"].astype(str).str.strip().ne("").fillna(False)

df_view = df[mask].copy()

# Select columns to show
show_cols = [
    "Age (days)", "Aging Bucket", "Date_parsed",
    "Ticket Number", "Invoice Number", "Item Number",
    "Credit Request Total", "RTN_CR_No",
    "Requested By", "Sales Rep", "Status", "Record ID"
]
show_cols = [c for c in show_cols if c in df_view.columns]

# Pretty formatting
df_view = df_view.rename(columns={"Date_parsed": "Date"})
if "Credit Request Total" in df_view.columns:
    df_view["Credit Request Total"] = df_view["Credit Request Total"].apply(format_money)

# Display
st.subheader(f"Results ({len(df_view):,}) — Oldest on top")
st.dataframe(
    df_view[show_cols],
    use_container_width=True,
)

# Download
csv_buf = io.StringIO()
df_view[show_cols].to_csv(csv_buf, index=False)
st.download_button(
    "⬇️ Download CSV",
    data=csv_buf.getvalue(),
    file_name=f"credit_aging_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)

# Quick summary stats
st.markdown("### 📊 Summary")
left, right, far = st.columns(3)
with left:
    st.metric("Total rows (dated)", f"{len(df):,}")
with right:
    st.metric("Filtered rows", f"{len(df_view):,}")
with far:
    st.metric("Max age (days)", f"{int(df_view['Age (days)'].max()) if len(df_view) else 0}")

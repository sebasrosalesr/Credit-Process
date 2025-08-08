from datetime import datetime, date
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

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

@st.cache_data(ttl=120)
def fetch_credits():
    data = ref.get() or {}
    rows = []
    for key, item in data.items():
        rec = {col: item.get(col, None) for col in EXPECTED_COLUMNS}
        rec["Record ID"] = key
        rows.append(rec)
    df = pd.DataFrame(rows)

    # Robust date parsing
    df["Date_parsed"] = pd.to_datetime(df.get("Date"), errors="coerce", infer_datetime_format=True)

    # Compute age
    today = pd.Timestamp(date.today())
    df["Age (days)"] = (today - df["Date_parsed"]).dt.days

    # Drop rows without a valid date
    df = df[~df["Date_parsed"].isna()].copy()

    # Aging bucket (optional)
    bins = [-1, 7, 14, 30, 60, 90, 180, 365, 10_000]
    labels = ["0-7", "8-14", "15-30", "31-60", "61-90", "91-180", "181-365", "365+"]
    df["Aging Bucket"] = pd.cut(df["Age (days)"], bins=bins, labels=labels)

    # Sort: oldest first
    df = df.sort_values(["Age (days)", "Date_parsed"], ascending=[False, True])

    # Pretty money if present
    if "Credit Request Total" in df.columns:
        df["Credit Request Total"] = pd.to_numeric(df["Credit Request Total"], errors="coerce")
    return df

with st.spinner("Loading credits…"):
    df = fetch_credits()

# ---- Filters
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
df_view = df_view.rename(columns={"Date_parsed": "Date"})

# Columns to show (use only those that exist to avoid KeyError)
desired_cols = [
    "Age (days)", "Aging Bucket", "Date",
    "Ticket Number", "Invoice Number", "Item Number",
    "Credit Request Total", "RTN_CR_No",
    "Requested By", "Sales Rep", "Status", "Record ID"
]
show_cols = [c for c in desired_cols if c in df_view.columns]

st.subheader(f"Results ({len(df_view):,}) — Oldest on top")
if show_cols:
    # Format money column if present
    if "Credit Request Total" in show_cols:
        df_view["Credit Request Total"] = df_view["Credit Request Total"].apply(
            lambda v: f"${v:,.2f}" if pd.notna(v) else ""
        )
    st.dataframe(df_view[show_cols], use_container_width=True)
else:
    st.info("No displayable columns found in the current selection.")

# Download
csv_buf = io.StringIO()
(df_view[show_cols] if show_cols else df_view).to_csv(csv_buf, index=False)
st.download_button(
    "⬇️ Download CSV",
    data=csv_buf.getvalue(),
    file_name=f"credit_aging_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)

# Summary
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Total rows (dated)", f"{len(df):,}")
with c2:
    st.metric("Filtered rows", f"{len(df_view):,}")
with c3:
    st.metric("Max age (days)", f"{int(df_view['Age (days)'].max()) if len(df_view) else 0}")

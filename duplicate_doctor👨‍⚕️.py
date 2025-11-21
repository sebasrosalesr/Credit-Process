from datetime import datetime
import math
from typing import Iterable, Dict, Any, Tuple
from collections import defaultdict

import pandas as pd
import streamlit as st

import firebase_admin
from firebase_admin import credentials, db

# =========================
# Page + Auth
# =========================
st.set_page_config(page_title="🩺 Duplicate Doctor — Credit Requests", layout="wide")

APP_PASSWORD  = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL   = 30 * 60  # 30 min
MAX_ATTEMPTS  = 5
LOCKOUT_SEC   = 60

def check_password():
    now = datetime.now().timestamp()
    ss = st.session_state
    ss.setdefault("auth_ok", False)
    ss.setdefault("last_seen", 0.0)
    ss.setdefault("bad_attempts", 0)
    ss.setdefault("locked_until", 0.0)

    if ss["auth_ok"]:
        if now - ss["last_seen"] > SESSION_TTL:
            ss["auth_ok"] = False
        else:
            ss["last_seen"] = now
            return True

    if now < ss["locked_until"]:
        st.error("Too many attempts. Try again in a minute.")
        st.stop()

    st.title("🔒 Private Access — Duplicate Doctor")
    pwd = st.text_input("Enter password:", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            ss.update(auth_ok=True, last_seen=now, bad_attempts=0)
            st.rerun()
        else:
            ss["bad_attempts"] += 1
            if ss["bad_attempts"] >= MAX_ATTEMPTS:
                ss["locked_until"] = now + LOCKOUT_SEC
                ss["bad_attempts"] = 0
            st.error("❌ Incorrect password")
            st.stop()
    st.stop()

if not check_password():
    st.stop()

st.title("🩺 Duplicate Doctor — Credit Request Scanner")

st.caption(
    "This tool scans **Firebase → `credit_requests`** for logical duplicates using a "
    "composite key of Ticket, Invoice, Item, QTY, and Credit Request Total. "
    "You can optionally mark specific rows to delete from Firebase."
)

# =========================
# Firebase Init
# =========================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(
        cred,
        {"databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"},
    )

ref = db.reference("credit_requests")

# =========================
# Helpers / Normalizers
# =========================
def as_str(x) -> str:
    return "" if x is None else str(x).strip()

def norm_invoice(x) -> str:
    return as_str(x).upper()

def norm_item(x) -> str:
    s = as_str(x)
    if s.endswith(".0"):
        try:
            f = float(s)
            if f.is_integer():
                return str(int(f))
        except ValueError:
            pass
    return s

def norm_ticket(x) -> str:
    return as_str(x).upper()

def safe_float(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None

def safe_int(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        f = float(x)
        if f.is_integer():
            return int(f)
        return f  # leave as float if truly fractional
    except Exception:
        return None

def make_dedupe_key(rec: Dict[str, Any]) -> Tuple:
    """
    Composite key used to define a 'logical duplicate'.
    Adjust if you want more/less strict matching.
    """
    return (
        norm_ticket(rec.get("Ticket Number", "")),
        norm_invoice(rec.get("Invoice Number", "")),
        norm_item(rec.get("Item Number", "")) if rec.get("Item Number") is not None else None,
        safe_int(rec.get("QTY", None)),
        safe_float(rec.get("Credit Request Total", None)),
    )

# =========================
# Scan Firebase
# =========================
st.header("Step 1: Scan Firebase for Duplicates")

if st.button("🔍 Run Duplicate Scan", type="primary", key="scan_button"):
    with st.spinner("Scanning Firebase credit_requests…"):
        raw_data = ref.get() or {}

        records = []
        for fb_key, rec in raw_data.items():
            if not isinstance(rec, dict):
                continue

            # Build a flattened, normalized view
            ticket = norm_ticket(rec.get("Ticket Number", ""))
            invoice = norm_invoice(rec.get("Invoice Number", ""))
            item = (
                norm_item(rec.get("Item Number", ""))
                if rec.get("Item Number") is not None
                else None
            )
            qty = safe_int(rec.get("QTY", None))
            cr_total = safe_float(rec.get("Credit Request Total", None))

            record = {
                "_firebase_key": fb_key,
                "Ticket Number": ticket,
                "Invoice Number": invoice,
                "Item Number": item,
                "QTY": qty,
                "Credit Request Total": cr_total,
                "Credit Type": as_str(rec.get("Credit Type", "")),
                "Type": as_str(rec.get("Type", "")),
                "Issue Type": as_str(rec.get("Issue Type", "")),
                "Requested By": as_str(rec.get("Requested By", "")),
                "Sales Rep": as_str(rec.get("Sales Rep", "")),
                "Date": as_str(rec.get("Date", "")),
                "Record ID": as_str(rec.get("Record ID", "")),
                "Status": as_str(rec.get("Status", "")),
                "Customer Number": as_str(rec.get("Customer Number", "")),
                "Invoice Raw": as_str(rec.get("Invoice Number", "")),
                "Item Raw": as_str(rec.get("Item Number", "")),
            }

            record["Dedupe Key"] = make_dedupe_key(record)
            records.append(record)

        if not records:
            st.warning("No records found in Firebase `credit_requests`.")
            st.session_state.pop("dup_df", None)
        else:
            # Group by dedupe key
            by_key = defaultdict(list)
            for rec in records:
                by_key[rec["Dedupe Key"]].append(rec)

            duplicate_groups = {k: v for k, v in by_key.items() if len(v) > 1}

            total_records = len(records)
            total_groups = len(duplicate_groups)
            total_dupes = sum(len(v) for v in duplicate_groups.values())

            st.success("✅ Scan complete!")

            st.metric("Total records scanned", f"{total_records:,}")
            st.metric("Duplicate groups found", f"{total_groups:,}")
            st.metric("Total duplicate rows (in those groups)", f"{total_dupes:,}")

            if total_groups == 0:
                st.info("No logical duplicates found with the current dedupe key.")
                st.session_state.pop("dup_df", None)
            else:
                # Flatten duplicate groups into a DataFrame
                flat_rows = []
                for key, group_recs in duplicate_groups.items():
                    group_size = len(group_recs)
                    for rec in group_recs:
                        row = rec.copy()
                        row["Duplicate Group Size"] = group_size
                        row["Dedupe Key (str)"] = str(key)
                        flat_rows.append(row)

                dup_df = pd.DataFrame(flat_rows)

                # Add Delete flag (default False)
                dup_df["Delete"] = False

                # Store in session_state so we can interact with it
                st.session_state["dup_df"] = dup_df

else:
    # Just show existing metrics/info if any from prior run
    st.info("Click **'🔍 Run Duplicate Scan'** to analyze current Firebase records.")

# =========================
# Interactive Duplicate Table + Delete
# =========================
if "dup_df" in st.session_state:
    st.subheader("Step 2: Review Duplicate Groups & Mark Rows to Delete")

    st.warning(
        "⚠️ Deletions are **permanent** in Firebase. "
        "Only mark rows you are **100% sure** you want to remove."
    )

    dup_df = st.session_state["dup_df"]

    display_cols = [
        "Delete",
        "Duplicate Group Size",
        "Ticket Number",
        "Invoice Number",
        "Item Number",
        "QTY",
        "Credit Request Total",
        "Credit Type",
        "Issue Type",
        "Sales Rep",
        "Requested By",
        "Date",
        "_firebase_key",
        "Record ID",
        "Dedupe Key (str)",
    ]

    # Data editor with checkbox for Delete
    edited_df = st.data_editor(
        dup_df[display_cols],
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="dup_editor",
    )

    # Persist edited flags back to session_state
    # (so the Delete button can read latest selections)
    merged = dup_df.copy()
    # Only update the Delete column from edited_df
    merged = merged.drop(columns=["Delete"])
    merged = edited_df.merge(
        merged.drop(columns=["Delete"]),
        on=[
            "Duplicate Group Size",
            "Ticket Number",
            "Invoice Number",
            "Item Number",
            "QTY",
            "Credit Request Total",
            "Credit Type",
            "Issue Type",
            "Sales Rep",
            "Requested By",
            "Date",
            "_firebase_key",
            "Record ID",
            "Dedupe Key (str)",
        ],
        how="left",
        suffixes=("", "_orig"),
    )
    # Clean up possible extra columns
    cols_to_keep = dup_df.columns
    merged = merged[[c for c in merged.columns if c in cols_to_keep]]

    st.session_state["dup_df"] = merged
    dup_df = merged  # refreshed reference

    # Download CSV of current view (with Delete flags)
    csv_bytes = dup_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Download Duplicate Report (CSV, including Delete flags)",
        data=csv_bytes,
        file_name=f"duplicate_doctor_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.subheader("Step 3: Apply Deletes to Firebase")

    delete_df = dup_df[dup_df["Delete"] == True]
    num_to_delete = delete_df["_firebase_key"].nunique()

    st.write(f"Selected for deletion: **{num_to_delete}** unique Firebase record(s).")

    if num_to_delete > 0:
        if st.button("⚠️ Delete selected records from Firebase", type="primary"):
            with st.spinner("Deleting selected records from Firebase…"):
                success = 0
                failed = 0
                errors = []

                unique_keys = delete_df["_firebase_key"].unique().tolist()
                for fb_key in unique_keys:
                    try:
                        db.reference(f"credit_requests/{fb_key}").delete()
                        success += 1
                    except Exception as e:
                        failed += 1
                        errors.append(f"{fb_key}: {e}")

                # Remove deleted rows from in-memory DataFrame
                dup_df = dup_df[~dup_df["_firebase_key"].isin(unique_keys)].reset_index(drop=True)
                st.session_state["dup_df"] = dup_df

            st.success(f"✅ Deleted {success} record(s) from Firebase.")
            if failed > 0:
                st.error(f"🔥 Failed to delete {failed} record(s). See details below.")
                with st.expander("Error details"):
                    for line in errors:
                        st.write(line)

    else:
        st.info("No rows are currently marked for deletion.")

# Sidebar logout
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()

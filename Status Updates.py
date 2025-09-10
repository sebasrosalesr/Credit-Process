from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import pytz

# --- Firebase Initialization ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- Helpers ---
def normalize_str(x):
    if x is None:
        return ""
    s = str(x).strip()
    return s

def has_cr_number(record):
    """
    Returns True if the record looks like it has a CR number in any of the common fields.
    Treats empty, '-', 'n/a', 'none', 'no', '0' as missing.
    """
    candidates = [
        record.get("RTN_CR_No"),
        record.get("CR Number"),
        record.get("RTN No"),
        record.get("CR_No"),
        record.get("RTN_CR"),
    ]
    for val in candidates:
        if val is None:
            continue
        s = str(val).strip()
        if s and s.lower() not in {"-", "n/a", "na", "none", "no", "0"}:
            return True
    return False

# --- Streamlit UI ---
st.set_page_config(page_title="Bulk Status Update", layout="wide")
st.title("📋 Bulk Update Credit Request Status")

st.header("Step 1: Search Records")
search_input = st.text_input("🔍 Ticket Number, Invoice Number, Item Number, or Invoice|Item pair")

if search_input:
    data = ref.get() or {}
    search_input = search_input.strip().lower()
    matches = {}
    source = ""

    for key, record in data.items():
        # Normalize fields
        ticket = normalize_str(record.get("Ticket Number", "")).lower()
        invoice = normalize_str(record.get("Invoice Number", "")).lower()
        item = normalize_str(record.get("Item Number", "")).lower()
        status = normalize_str(record.get("Status", "")).lower()

        if search_input == ticket:
            matches[key] = record; source = "Ticket Number"
        elif search_input == invoice:
            matches[key] = record; source = "Invoice Number"
        elif search_input == item:
            matches[key] = record; source = "Item Number"
        elif "|" in search_input:
            parts = [p.strip().lower() for p in search_input.split("|")]
            if len(parts) == 2 and invoice == parts[0] and item == parts[1]:
                matches[key] = record; source = "Invoice + Item Pair"
        elif search_input in status:
            matches[key] = record; source = "Status field (partial match)"

    if matches:
        # --- NEW: CR filter control ---
        st.subheader("Filter by CR Number")
        cr_filter = st.radio(
            "Choose which records to show/update based on RTN_CR_No:",
            ["All", "Has CR Number", "No CR Number"],
            index=0,
            horizontal=True
        )

        # Apply CR filter
        if cr_filter == "All":
            filtered = matches
        elif cr_filter == "Has CR Number":
            filtered = {k: v for k, v in matches.items() if has_cr_number(v)}
        else:  # "No CR Number"
            filtered = {k: v for k, v in matches.items() if not has_cr_number(v)}

        if filtered:
            st.success(f"✅ Found {len(filtered)} record(s) using {source} (CR filter: {cr_filter}).")

            # Optional: display results before updating
            df_preview = pd.DataFrame.from_dict(filtered, orient="index")
            st.dataframe(df_preview)

            st.header("Step 2: Apply Bulk Status Update")
            status_option = st.selectbox("🔄 New Status", [
                "Update", "Credit No & Reason", "In Process", "Submitted to Billing"
            ])
            status_description = st.text_area("📝 Status Description")

            if st.button("📤 Apply Status Update to These Records"):
                if not status_description.strip():
                    st.warning("⚠️ Please enter a status description.")
                else:
                    # --- Set to Indianapolis timezone ---
                    indiana_tz = pytz.timezone("America/Indiana/Indianapolis")
                    timestamp = datetime.now(indiana_tz).strftime("%Y-%m-%d %H:%M:%S")

                    status_entry = f"[{timestamp}] {status_option}: {status_description}"
                    count = 0

                    for key, val in filtered.items():
                        current_status = normalize_str(val.get("Status", ""))
                        new_status = (current_status + "\n" + status_entry).strip() if current_status else status_entry
                        ref.child(key).update({"Status": new_status})
                        count += 1

                    st.success(f"✅ Updated {count} record(s) with new status.")
        else:
            st.warning(f"⚠️ No records after applying CR filter: {cr_filter}.")
    else:
        st.warning("⚠️ No records matched your search input.")

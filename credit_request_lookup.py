from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
import re

# =========================
# Firebase Initialization
# =========================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")

cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# =========================
# Streamlit UI
# =========================
st.set_page_config(page_title="🔎 Credit Processing Snapshot (Pricing)", layout="wide")
st.title("🔎 Credit Processing Snapshot (Pricing)")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, or Invoice + Item Pair.")

# =========================
# Input Fields
# =========================
search_type = st.selectbox("Search By", [
    "Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"
])

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None
uploaded_file = st.file_uploader(
    "📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'",
    type=["csv"]
) if search_type == "Invoice + Item Pair" else None

# =========================
# Helpers
# =========================
def extract_status_info(text: str):
    """
    Returns (latest_update_text, latest_timestamp_str)
    Finds the LAST '[YYYY-MM-DD HH:MM:SS] ...' line in Status.
    Falls back to labeled patterns if no timestamped line found.
    """
    if pd.isna(text) or not isinstance(text, str) or not text.strip():
        return "No updates", None

    # 1) Try to find the last timestamped line
    ts_iter = list(re.finditer(
        r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)',
        text
    ))
    if ts_iter:
        last = ts_iter[-1]
        ts = last.group(1)
        msg = last.group(2).strip() or "No detailed status"
        return msg, ts

    # 2) Fallback to older labeled formats
    m = re.search(r'(Update|In Process|Submitted to Billing|Credit No & Reason):\s*(.*)', text, flags=re.IGNORECASE)
    if m:
        return (m.group(2).strip() or "No detailed status"), None

    return "No detailed status", None


def format_currency(val):
    """Format value as currency ($1,234.56) or return empty string."""
    try:
        return f"${float(val):,.2f}" if pd.notna(val) and str(val).strip() != "" else ""
    except:
        return ""


# =========================
# Search Action
# =========================
if st.button("🔎 Search"):
    try:
        data = ref.get()
        matches = []

        if data:
            for key, record in data.items():
                match = False
                inv = str(record.get("Invoice Number", "")).strip()
                item = str(record.get("Item Number", "")).strip()
                ticket = str(record.get("Ticket Number", "")).strip()
                status = str(record.get("Status", "")).strip()

                # Ticket Number
                if search_type == "Ticket Number" and input_ticket:
                    if ticket.lower() == input_ticket.strip().lower():
                        match = True

                # Invoice Number
                elif search_type == "Invoice Number" and input_invoice:
                    if inv == input_invoice.strip():
                        match = True

                # Item Number
                elif search_type == "Item Number" and input_item:
                    if item == input_item.strip():
                        match = True

                # Invoice + Item Pair
                elif search_type == "Invoice + Item Pair":
                    if uploaded_file:
                        pair_df = pd.read_csv(uploaded_file)
                        if not {'Invoice Number', 'Item Number'}.issubset(pair_df.columns):
                            st.error("CSV must contain 'Invoice Number' and 'Item Number' columns.")
                            break
                        for _, row in pair_df.iterrows():
                            if inv == str(row['Invoice Number']).strip() and item == str(row['Item Number']).strip():
                                match = True
                                record["Search_Invoice"] = row['Invoice Number']
                                record["Search_Item"] = row['Item Number']
                                break
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                # If match found, store record
                if match:
                    record["Record ID"] = key
                    update_text, update_ts = extract_status_info(status)
                    record["Latest Update"] = update_text
                    record["Update Timestamp"] = update_ts
                    matches.append(record)

        # =========================
        # Display results
        # =========================
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")
            df_results = pd.DataFrame(matches)

            # Format Credit Request Total
            if "Credit Request Total" in df_results.columns:
                df_results["Credit Request Total ($)"] = df_results["Credit Request Total"].apply(format_currency)
                if "Credit Request Total" in df_results.columns:
                    df_results.drop(columns=["Credit Request Total"], inplace=True)

            # Show only the most relevant columns
            display_cols = [
                'Invoice Number', 'Item Number', 'Update Timestamp', 'Latest Update',
                'Ticket Number', 'Credit Request Total ($)'
            ]
            existing_cols = [col for col in display_cols if col in df_results.columns]

            st.dataframe(df_results[existing_cols])

            # Download results
            csv_buf = io.StringIO()
            df_results[existing_cols].to_csv(csv_buf, index=False)
            st.download_button(
                label="⬇️ Download Results as CSV",
                data=csv_buf.getvalue(),
                file_name="credit_request_search_results.csv",
                mime="text/csv"
            )
        else:
            st.warning("❌ No matching records found.")

    except Exception as e:
        st.error(f"🔥 Error retrieving records: {e}")

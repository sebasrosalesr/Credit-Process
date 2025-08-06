from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
import re

# --- Firebase Init ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- Streamlit UI ---
st.set_page_config(page_title="🔎 Credit Processing Snapshot(Pricing)", layout="wide")
st.title("🔎 Credit Request Search Tool")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, or Invoice+Item Pair")

# --- Input Fields ---
search_type = st.selectbox("Search By", ["Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"])

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None
uploaded_file = st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'", type=["csv"]) if search_type == "Invoice + Item Pair" else None

# --- Extract status update and timestamp ---
def extract_status_info(text):
    if pd.isna(text) or not isinstance(text, str):
        return "No updates", None

    timestamp_match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', text)
    timestamp = timestamp_match.group(1) if timestamp_match else None

    status_match = re.search(r'(Update|In Process|Submitted to Billing|Credit No & Reason):\s*(.*)', text)
    update_text = status_match.group(2).strip() if status_match else "No detailed status"

    return update_text, timestamp

# --- Search Action ---
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
                if search_type == "Ticket Number":
                    ticket_search = input_ticket.strip().lower()
                    if ticket.lower() == ticket_search:
                        match = True

                # Invoice Number
                elif search_type == "Invoice Number":
                    if inv == input_invoice.strip():
                        match = True

                # Item Number
                elif search_type == "Item Number":
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
                            target_inv = str(row['Invoice Number']).strip()
                            target_item = str(row['Item Number']).strip()
                            if inv == target_inv and item == target_item:
                                match = True
                                record["Search_Invoice"] = target_inv
                                record["Search_Item"] = target_item
                                break
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                if match:
                    record["Record ID"] = key
                    update_text, update_ts = extract_status_info(status)
                    record["Latest Update"] = update_text
                    record["Update Timestamp"] = update_ts
                    matches.append(record)

        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")
            df_results = pd.DataFrame(matches)

            # Show only the most relevant columns
            display_cols = ['Invoice Number', 'Item Number', 'Update Timestamp', 'Latest Update',
                            'Ticket Number', 'Credit Request Total']
            existing_cols = [col for col in display_cols if col in df_results.columns]

            st.dataframe(df_results[existing_cols])

            # Download
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

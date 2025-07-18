from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# --- Firebase Initialization ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- Streamlit UI ---
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")
st.title("🔍 Credit Request Search Tool")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, or Invoice+Item Pair")

# --- Input Fields ---
search_type = st.selectbox("Search By", ["Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"])

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None
uploaded_file = st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'", type=["csv"]) if search_type == "Invoice + Item Pair" else None

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
                    if ticket.lower() == ticket_search or ticket_search in status.lower():
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
                    # Case 1: CSV Upload
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
                    # Case 2: Manual input
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                if match:
                    record["Record ID"] = key
                    matches.append(record)

        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            # Show each record in an expander
            for i, record in enumerate(matches):
                with st.expander(f"📌 Record {i + 1} — Ticket: {record.get('Ticket Number', 'N/A')}"):
                    st.json(record)

            # Convert to DataFrame and enable download
            df_export = pd.DataFrame(matches)
            csv_buffer = io.StringIO()
            df_export.to_csv(csv_buffer, index=False)

            st.download_button(
                label="⬇️ Download Results as CSV",
                data=csv_buffer.getvalue(),
                file_name="credit_request_results.csv",
                mime="text/csv"
            )
        else:
            st.warning("❌ No matching records found.")

    except Exception as e:
        st.error(f"🔥 Error retrieving records: {e}")

from datetime import datetime
import streamlit as st
import firebase_admin
from firebase_admin import credentials, db

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
st.title("🔍 Credit Request Search Tool")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, or a Pair")

# --- Input Fields ---
search_type = st.selectbox("Search By", ["Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"])
input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None

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

                if search_type == "Ticket Number":
                    ticket_search = input_ticket.strip().lower()
                    if ticket.lower() == ticket_search:
                        match = True
                    elif ticket_search in status.lower():
                        match = True
                elif search_type == "Invoice Number" and inv == input_invoice.strip():
                    match = True
                elif search_type == "Item Number" and item == input_item.strip():
                    match = True
                elif search_type == "Invoice + Item Pair":
                    if inv == input_invoice.strip() and item == input_item.strip():
                        match = True

                if match:
                    record["Record ID"] = key
                    matches.append(record)

        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")
            for i, record in enumerate(matches):
                with st.expander(f"📌 Record {i + 1} — Ticket: {record.get('Ticket Number', 'N/A')}"):
                    st.json(record)
        else:
            st.warning("❌ No matching records found.")

    except Exception as e:
        st.error(f"🔥 Error retrieving records: {e}")

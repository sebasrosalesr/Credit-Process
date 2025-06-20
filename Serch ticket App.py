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
st.title("🔎 Ticket Search - Credit Requests")
st.markdown("Search any ticket by its number to view full submission.")

# --- Ticket Search Form ---
st.header("Search by Ticket Number")
ticket_query = st.text_input("Enter Ticket Number", help="Searches all records for this ticket number")
search_button = st.button("Search")

if search_button and ticket_query:
    try:
        data = ref.get()
        match_found = False

        if data:
            for key, record in data.items():
                if str(record.get("Ticket Number", "")) == ticket_query:
                    st.success(f"✅ Match Found: Record ID = {key}")
                    st.json(record)
                    match_found = True
                    break

        if not match_found:
            st.warning("❌ No record found with that ticket number.")

    except Exception as e:
        st.error(f"🔥 Error retrieving records: {e}")

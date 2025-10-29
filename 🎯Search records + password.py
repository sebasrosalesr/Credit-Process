from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# -------------------------------------------------
# Basic password gate (no Firebase needed to login)
# -------------------------------------------------
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")  # uses Streamlit Secret in prod

def check_password():
    """Return True if the correct password is entered; otherwise render login and stop."""
    if st.session_state.get("auth_ok"):
        return True

    st.title("🔒 Private Access")
    pwd = st.text_input("Enter password:", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("❌ Incorrect password")
            st.stop()
    st.stop()

if not check_password():
    st.stop()

# Optional: logout button in sidebar
with st.sidebar:
    if st.button("Logout"):
        st.session_state.auth_ok = False
        st.rerun()

# ---------------------------
# Firebase Initialization
# ---------------------------
firebase_config = dict(st.secrets["firebase"])
# Fix newline escapes from secrets UI
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
    })

ref = db.reference("credit_requests")

# ---------------------------
# App UI (your original tool)
# ---------------------------
st.title("🔍 Credit Request Search Tool")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, or Invoice+Item Pair")

search_type = st.selectbox(
    "Search By",
    ["Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"]
)

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None
uploaded_file = (
    st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'", type=["csv"])
    if search_type == "Invoice + Item Pair" else None
)

if st.button("🔎 Search"):
    try:
        data = ref.get()
        matches = []

        if data:
            for key, record in data.items():
                inv = str(record.get("Invoice Number", "")).strip()
                item = str(record.get("Item Number", "")).strip()
                ticket = str(record.get("Ticket Number", "")).strip()
                status = str(record.get("Status", "")).strip()

                match = False

                if search_type == "Ticket Number":
                    ticket_search = (input_ticket or "").strip().lower()
                    if ticket.lower() == ticket_search or ticket_search in status.lower():
                        match = True

                elif search_type == "Invoice Number":
                    if inv == (input_invoice or "").strip():
                        match = True

                elif search_type == "Item Number":
                    if item == (input_item or "").strip():
                        match = True

                elif search_type == "Invoice + Item Pair":
                    if uploaded_file:
                        pair_df = pd.read_csv(uploaded_file)
                        if not {"Invoice Number", "Item Number"}.issubset(pair_df.columns):
                            st.error("CSV must contain 'Invoice Number' and 'Item Number' columns.")
                            break
                        # check if any row matches this record
                        for _, row in pair_df.iterrows():
                            target_inv = str(row["Invoice Number"]).strip()
                            target_item = str(row["Item Number"]).strip()
                            if inv == target_inv and item == target_item:
                                match = True
                                record["Search_Invoice"] = target_inv
                                record["Search_Item"] = target_item
                                break
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                if match:
                    out = dict(record)
                    out["Record ID"] = key
                    matches.append(out)

        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")
            for i, rec in enumerate(matches):
                with st.expander(f"📌 Record {i + 1} — Ticket: {rec.get('Ticket Number', 'N/A')}"):
                    st.json(rec)

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

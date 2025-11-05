from datetime import datetime
import time
import sqlite3
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, db

# ===============================
# Auth (same as your current one)
# ===============================
APP_PASSWORD   = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL_SEC = 30 * 60       # 30 min
MAX_ATTEMPTS    = 5
LOCKOUT_SEC     = 60            # 1 min cooldown

def check_password():
    now = time.time()
    # init state
    st.session_state.setdefault("auth_ok", False)
    st.session_state.setdefault("last_seen", 0.0)
    st.session_state.setdefault("bad_attempts", 0)
    st.session_state.setdefault("locked_until", 0.0)

    # active session timeout
    if st.session_state["auth_ok"]:
        if now - st.session_state["last_seen"] > SESSION_TTL_SEC:
            st.session_state["auth_ok"] = False
        else:
            st.session_state["last_seen"] = now
            return True

    # lockout window after too many failures
    if now < st.session_state["locked_until"]:
        st.error("Too many attempts. Try again in a minute.")
        st.stop()

    st.title("🔒 Private Access")
    pwd = st.text_input("Enter password:", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.update(auth_ok=True, last_seen=now, bad_attempts=0)
            st.rerun()
        else:
            st.session_state["bad_attempts"] += 1
            if st.session_state["bad_attempts"] >= MAX_ATTEMPTS:
                st.session_state["locked_until"] = now + LOCKOUT_SEC
                st.session_state["bad_attempts"] = 0
            st.error("❌ Incorrect password")
            st.stop()
    st.stop()

# Gate the app
if not check_password():
    st.stop()

# ===============================
# Firebase init
# ===============================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# ===============================
# Local SQLite (as before)
# ===============================
db_path = "credits.db"
conn = sqlite3.connect(db_path)

# ===============================
# Load data
# ===============================
st.header("🛠️ Edit Existing Records")
data = ref.get()
records = []

if data:
    for key, record in data.items():
        record = record or {}
        record['firebase_key'] = key
        records.append(record)

df_records = pd.DataFrame(records) if records else pd.DataFrame()

# ===============================
# Dropdown options
# ===============================
sales_rep_options = sorted([
    'HOUSE','SA/AR','nan','AR/KE','BPARKER','RFRIEDMAN','AROSENFELD','DR/TU','JK/AR','AR/MG',
    'CHRISWYLER','JGOULDING','AL/NL','MALCARAZ','TJUNIK','ALANDAU','NYS','EB/MC/MF/SM',
    'EB/MC/MF/SM/SP','ELIB','MF/SG','TRENNERT','SA/MG','WNISCHT','AR/BG','RMAIRS','BWERCZBERGER',
    'AL/AR/BG','EB','JEARL','TWHITZEL','JSWEENEY','JMCSHANNOCK','DDFILIPPO','CTHOMAS','NELLMAN',
    'BMONCZYK','SADAMS','DW/EB/MC/MF/SM','DWEBMCMFSMSP','DW/EB/MF/MC/SP/','JC/JT','RF/AR','RDORAN',
    'SMARCIANO','JCROSGROVE','MC/MF','MC/SM','BOBGOLD','ELI/BOB','MFINE','CFAULKNER','NLANDAU','MF',
    'ALLMED','CW/SM','AOBEZIL','EB/MC/MF','JTIPTON','AR/JS','DW/MF','BRANDALL','KM/RM','MDESIMONE',
    'MEYER','MC','CHI/NL','BBINDEL','MWEENIG','NMERRITT','DW','SDECKERT','MC/MF/SM',
    'ELIB/MC/MF/SIMI','DW/MF/SM','EB/SG','EB/MC/MF/SG/SM','NBITTERMAN','SM/MC/EB/MF/AL','MLANDAU',
    'EB/MF/MC/SP/SM','JMILLER','ELIB/MC','JGOLESTANI','MF/SM','JSOLOMON','AL/NL/TJ','MVZ','SIMI',
    'CWILLIAMS','DW/EB/MC/MF/SIM','TPETERS','BP/NL','DW/SIMI/MF','JDUCKWORTH','EB/MC','DWEINBERGER',
    'AL/MF','SIMI/MF','DD/AS','MAMCGOWEN','AROEBUCK','JM/BB','JGRANT','ALEBMCMFSMSP','AROTH',
    'SIMI/MC/MF','JSHALLMAN','DROPA','ASPEAR','JS/DW','JE/JT','AL/AR','SIMI/MC','ELIB/SIMI',
    'JM/MA','RA/KE','MC/MF/SG','JC/JE','EB/SM','MDELGADO','BW/CW','ELI/SHAWEL','BROOSEVELT',
    'DYONA','MVANZELST','ROB','ELI/BOB/MF','MC/MF/SG/SM','AL/MC','SIMI/MC/ELIB','TJ/NB','MC/SG',
    'MF/SP/RF','AL/JG','MEDSPARK','JM/AS','CRAMIREZ','CF/AR','SM','TJ/NL','AO/MA','MCHASE',
    'KSCHWIETERMAN','ELI BERKOVICH','CW/TJ','MW/TJ','KEMORY','RA','BG','PECK','EB/NB/C/F/M/P',
    'CROBINSON','MF/NL','SG','SD/SM','DW/EB/MC/MF/SM/SP','BB/MDS','BFR','TJ/SA','NB/JE',
    'BOB/MF/SIMI/MC','DW/MC/MF/SM','CLANDAU/CWYLER','ELIB/MC/MF/RG/S'
])

credit_type_options = ["Credit Memo", "Internal"]

def _sanitize_opt(s):
    if s is None:
        return ""
    s = str(s).strip()
    # normalize a few "nan"ish values
    if s.lower() in ("nan", "none", "null"):
        return ""
    return s

# ===============================
# Search UI
# ===============================
if df_records.empty:
    st.info("No records available.")
    st.stop()

search_type = st.selectbox("Search by", ["Ticket Number", "Invoice + Item", "Invoice Only", "Item Only"])

results = pd.DataFrame()
if search_type == "Ticket Number":
    ticket = st.text_input("Enter Ticket Number").strip().lower()
    if ticket:
        results = df_records[df_records['Ticket Number'].astype(str).str.strip().str.lower() == ticket]
elif search_type == "Invoice + Item":
    col1, col2 = st.columns(2)
    with col1:
        invoice = st.text_input("Invoice Number").strip().lower()
    with col2:
        item = st.text_input("Item Number").strip().lower()
    if invoice and item:
        results = df_records[
            (df_records['Invoice Number'].astype(str).str.strip().str.lower() == invoice) &
            (df_records['Item Number'].astype(str).str.strip().str.lower() == item)
        ]
elif search_type == "Invoice Only":
    invoice = st.text_input("Invoice Number").strip().lower()
    if invoice:
        results = df_records[df_records['Invoice Number'].astype(str).str.strip().str.lower() == invoice]
elif search_type == "Item Only":
    item = st.text_input("Item Number").strip().lower()
    if item:
        results = df_records[df_records['Item Number'].astype(str).str.strip().str.lower() == item]

# ===============================
# Edit results
# ===============================
if not results.empty:
    st.write(f"🔍 Found {len(results)} matching record(s):")

    # Fields you allow to edit
    editable_fields = [
        "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
        "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
        "Reason for Credit", "Requested By", "Sales Rep", "Status",
        "Ticket Number", "Unit Price", "Type"
    ]

    for idx, row in results.iterrows():
        with st.expander(f"📄 Record {idx} — Invoice: {row.get('Invoice Number')} | Item: {row.get('Item Number')}"):
            st.write("🧾 Current Record:")
            st.json(row.to_dict())

            updated_data = {}
            for field in editable_fields:
                current_val = _sanitize_opt(row.get(field, ""))

                # --- Dropdown for Sales Rep ---
                if field == "Sales Rep":
                    # ensure current value is present (even if not in predefined list)
                    options = sales_rep_options.copy()
                    if current_val and current_val not in options:
                        options = [current_val] + options
                    # add a blank at the top for clearing value
                    if "" not in options:
                        options = [""] + options

                    updated_data[field] = st.selectbox(
                        f"{field} (Record {idx})",
                        options=options,
                        index=options.index(current_val) if current_val in options else 0,
                        help="Type to search the list."
                    )

                # --- Dropdown for Credit Type ---
                elif field == "Credit Type":
                    options = credit_type_options.copy()
                    # preserve unusual existing values
                    if current_val and current_val not in options:
                        options = [current_val] + options
                    if "" not in options:
                        options = [""] + options

                    updated_data[field] = st.selectbox(
                        f"{field} (Record {idx})",
                        options=options,
                        index=options.index(current_val) if current_val in options else 0
                    )

                # --- Everything else as free text ---
                else:
                    updated_data[field] = st.text_input(
                        f"{field} (Record {idx})",
                        value=current_val,
                        key=f"{field}_{idx}"
                    )

            if st.button(f"💾 Save Changes for Record {idx}"):
                firebase_key = row['firebase_key']
                try:
                    # normalize blanks back to None instead of "nan"
                    clean_update = {k: (v if str(v).strip() != "" else None) for k, v in updated_data.items()}
                    ref.child(firebase_key).update(clean_update)
                    st.success(f"✅ Record {idx} updated successfully.")
                except Exception as e:
                    st.error(f"❌ Failed to update record {idx}: {e}")
else:
    if search_type:
        st.info("No matching records found.")

# Sidebar logout
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()

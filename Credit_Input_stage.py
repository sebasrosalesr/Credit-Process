from datetime import datetime
import math, sqlite3, time
from typing import Iterable

import pandas as pd
import streamlit as st
from streamlit import column_config

import firebase_admin
from firebase_admin import credentials, db

# =========================
# Page + Auth
# =========================
st.set_page_config(page_title="RTN/CR No. Sync Tool", layout="wide")
APP_PASSWORD  = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL   = 30 * 60
MAX_ATTEMPTS  = 5
LOCKOUT_SEC   = 60

def check_password():
    now = time.time()
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

    st.title("🔒 Private Access")
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

st.title("📄 Credit Request Dashboard")

# =========================
# Firebase
# =========================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'})
ref = db.reference('credit_requests')

# Optional local db (kept for parity)
conn = sqlite3.connect("credits.db")

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

def clean_str_options(seq: Iterable) -> list[str]:
    out, seen = [], set()
    for x in seq:
        if x is None:
            s = ""
        elif isinstance(x, float) and math.isnan(x):
            s = ""
        else:
            s = str(x).strip()
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

CREDIT_TYPE_TO_CODE = {"Credit Memo": "RTNCM", "Internal": "RTNINT"}
CREDIT_TYPES = clean_str_options(["Credit Memo", "Internal"])
SALES_REPS = clean_str_options([
    "",  # allow blank
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

# =========================
# Upload
# =========================
st.header("Step 1: Upload Credit Request Template")
uploaded_file = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])
if not uploaded_file:
    st.stop()

df = pd.read_excel(uploaded_file)

expected_cols = [
    'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price',
    'Corrected Unit Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit'
]
missing = [c for c in expected_cols if c not in df.columns]
if missing:
    st.error(f"❌ Missing required columns: {', '.join(missing)}")
    st.stop()

df_filtered = df[expected_cols].copy()
df_filtered["Sales Rep"] = df.get("Sales Rep", pd.Series([None]*len(df)))

# Numeric cleaning
for field in ['Unit Price', 'Corrected Unit Price', 'Credit Request Total']:
    df_filtered[field] = df_filtered[field].astype(str).str.replace(r'[$,]', '', regex=True)
    df_filtered[field] = pd.to_numeric(df_filtered[field], errors='coerce')

# QTY extraction
df_filtered['QTY_raw'] = df_filtered['QTY'].astype(str).str.strip()
df_filtered['QTY_extracted'] = df_filtered['QTY_raw'].str.extract(r'^(\d+(?:\.\d+)?)')[0]
df_filtered['QTY'] = pd.to_numeric(df_filtered['QTY_extracted'], errors='coerce')
df_filtered.drop(columns=['QTY_raw', 'QTY_extracted'], inplace=True)

# Keep valid rows
df_filtered = df_filtered[
    (df_filtered['Issue Type'] == 'Tax') |
    (df_filtered['Invoice Number'].notna() & df_filtered['Item Number'].notna())
]
df_filtered.fillna({'QTY':0, 'Unit Price':0, 'Corrected Unit Price':0, 'Credit Request Total':0}, inplace=True)

# Normalize IDs now
df_filtered['Invoice Number'] = df_filtered['Invoice Number'].map(norm_invoice)
df_filtered['Item Number']    = df_filtered['Item Number'].map(norm_item)

# Existing pairs (dedupe)
existing_pairs = set()
try:
    existing_data = ref.get() or {}
    for rec in existing_data.values():
        inv = norm_invoice(rec.get('Invoice Number'))
        item = norm_item(rec.get('Item Number')) if rec.get('Item Number') is not None else None
        existing_pairs.add((inv, item))
except Exception as e:
    st.error(f"❌ Error reading from Firebase: {e}")

# =========================
# Ticket Metadata (no forms; always visible)
# =========================
st.header("Step 2: Ticket Info")
c1, c2, c3 = st.columns([1,1,2])
with c1:
    ticket_number = st.text_input("🎫 Ticket Number", value=st.session_state.get("ticket_number", ""))
with c2:
    ticket_date = st.date_input("📅 Ticket Date", value=st.session_state.get("ticket_date", datetime.today()))
with c3:
    status = st.text_area("📜 Status / Reason", value=st.session_state.get("ticket_status", ""))

# persist live
st.session_state["ticket_number"] = ticket_number
st.session_state["ticket_date"]   = ticket_date
st.session_state["ticket_status"] = status

# =========================
# Row Review (always renders)
# =========================
st.header("Step 3: Review & Edit Rows")

for need in ['Credit Type', 'Sales Rep']:
    if need not in df_filtered.columns:
        df_filtered[need] = ""
df_filtered['Credit Type'] = df_filtered['Credit Type'].astype(str).fillna("")
df_filtered['Sales Rep']   = df_filtered['Sales Rep'].astype(str).fillna("")

review_cols = [
    'Invoice Number', 'Item Number', 'Issue Type', 'QTY',
    'Unit Price', 'Corrected Unit Price', 'Credit Request Total',
    'Requested By', 'Reason for Credit',
    'Credit Type', 'Sales Rep'
]
review_df = df_filtered[review_cols].copy()

st.caption("Edit **Credit Type** and **Sales Rep** per row.")
edited_df = st.data_editor(
    review_df,
    use_container_width=True,
    num_rows="fixed",
    column_config={
        "Credit Type": column_config.SelectboxColumn("Credit Type", options=CREDIT_TYPES),
        "Sales Rep":   column_config.SelectboxColumn("Sales Rep",   options=SALES_REPS),
    },
    key="editor_table",
)

# persist the editor result
st.session_state["edited_df"] = edited_df.copy()

# =========================
# Submit
# =========================
if st.button("🚀 Submit Edited Rows to Firebase"):
    edited_df = st.session_state.get("edited_df")
    ticket_number = st.session_state.get("ticket_number", "")
    ticket_date   = st.session_state.get("ticket_date", datetime.today())
    status        = st.session_state.get("ticket_status", "")

    ticket_norm = norm_ticket(ticket_number)
    if not ticket_norm:
        st.error("Ticket Number is required.")
        st.stop()

    submitted = 0
    skipped_dupe = 0
    failed = 0
    details = []

    with st.spinner("Submitting rows…"):
        for i, row in edited_df.iterrows():
            inv  = norm_invoice(row['Invoice Number'])
            item = None if row['Issue Type'] == 'Tax' else norm_item(row['Item Number'])

            # duplicate check (non-Tax only)
            if row['Issue Type'] != 'Tax' and (inv, item) in existing_pairs:
                skipped_dupe += 1
                details.append(f"Row {i}: skipped duplicate (Invoice {inv}, Item {item})")
                continue

            record = row.to_dict()
            record['Invoice Number'] = inv
            record['Item Number'] = None if item is None else item

            # meta
            record["Ticket Number"] = ticket_norm
            record["Date"] = datetime.combine(ticket_date, datetime.min.time()).strftime("%Y-%m-%d")
            record["Status"] = as_str(status)

            # dropdowns
            friendly_ct = as_str(record.get("Credit Type"))
            record["Credit Type"] = friendly_ct
            record["Type"] = CREDIT_TYPE_TO_CODE.get(friendly_ct, "")
            record["Sales Rep"] = as_str(record.get("Sales Rep"))

            # clean NaNs -> None
            record = {k: (None if pd.isna(v) else v) for k, v in record.items()}

            # stringify IDs
            if record.get("Item Number") is not None:
                record["Item Number"] = as_str(record["Item Number"])
            record["Invoice Number"] = as_str(record["Invoice Number"])
            record["Ticket Number"]  = as_str(record["Ticket Number"])

            # Record ID
            record["Record ID"] = f"{ticket_norm}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{submitted}"

            try:
                ref.push(record)
                submitted += 1
                details.append(f"Row {i}: ✅ submitted (Invoice {inv}, Item {item})")
            except Exception as e:
                failed += 1
                details.append(f"Row {i}: 🔥 failed (Invoice {inv}, Item {item}) → {e}")

    st.info(f"Summary → Submitted: {submitted} • Duplicates: {skipped_dupe} • Errors: {failed}")
    with st.expander("Submission details"):
        for line in details:
            st.write(line)
    if submitted > 0:
        st.success(f"✅ {submitted} record(s) submitted to Firebase!")

# Sidebar logout
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()

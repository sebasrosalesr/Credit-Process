from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import sqlite3, time

# =========================
# Auth
# =========================
APP_PASSWORD  = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL   = 30 * 60
MAX_ATTEMPTS  = 5
LOCKOUT_SEC   = 60

def check_password():
    now = time.time()
    st.session_state.setdefault("auth_ok", False)
    st.session_state.setdefault("last_seen", 0.0)
    st.session_state.setdefault("bad_attempts", 0)
    st.session_state.setdefault("locked_until", 0.0)

    if st.session_state["auth_ok"]:
        if now - st.session_state["last_seen"] > SESSION_TTL:
            st.session_state["auth_ok"] = False
        else:
            st.session_state["last_seen"] = now
            return True

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

if not check_password():
    st.stop()

# =========================
# Firebase
# =========================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'})
ref = db.reference('credit_requests')

# =========================
# Local DB (optional)
# =========================
conn = sqlite3.connect("credits.db")

# =========================
# Normalizers (critical)
# =========================
def as_str(x) -> str:
    return "" if x is None else str(x).strip()

def norm_invoice(x) -> str:
    # keep invoices as uppercase strings
    return as_str(x).upper()

def norm_item(x) -> str:
    # remove .0 artifacts and return string
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

# Map friendly credit type to your short code if you still want to store both
CREDIT_TYPE_TO_CODE = {"Credit Memo": "RTNCM", "Internal": "RTNINT"}

# =========================
# UI
# =========================
st.set_page_config(page_title="RTN/CR No. Sync Tool", layout="wide")
st.title("📄 Credit Request Dashboard")

# Step 1: Upload File
st.header("Step 1: Upload Credit Request Template")
uploaded_file = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)

    expected_cols = [
        'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price',
        'Corrected Unit Price', 'Credit Request Total', 'Requested By',
        'Reason for Credit'
    ]
    for col in expected_cols:
        if col not in df.columns:
            st.error(f"❌ Missing required column: {col}")
            st.stop()

    df_filtered = df[expected_cols].copy()

    # Ensure Sales Rep column exists
    df_filtered["Sales Rep"] = df.get("Sales Rep", pd.Series([None]*len(df)))

    # --- Clean numeric fields ---
    for field in ['Unit Price', 'Corrected Unit Price', 'Credit Request Total']:
        df_filtered[field] = (
            df_filtered[field].astype(str).str.replace(r'[$,]', '', regex=True)
        )
        df_filtered[field] = pd.to_numeric(df_filtered[field], errors='coerce')

    # --- QTY: extract numeric from things like "2CS", "3EA" ---
    df_filtered['QTY_raw'] = df_filtered['QTY'].astype(str).str.strip()
    df_filtered['QTY_extracted'] = df_filtered['QTY_raw'].str.extract(r'^(\d+(?:\.\d+)?)')[0]
    df_filtered['QTY'] = pd.to_numeric(df_filtered['QTY_extracted'], errors='coerce')
    df_filtered.drop(columns=['QTY_raw', 'QTY_extracted'], inplace=True)

    # --- Keep valid rows ---
    df_filtered = df_filtered[
        (df_filtered['Issue Type'] == 'Tax') |
        (df_filtered['Invoice Number'].notna() & df_filtered['Item Number'].notna())
    ]

    df_filtered.fillna({
        'QTY': 0, 'Unit Price': 0, 'Corrected Unit Price': 0, 'Credit Request Total': 0
    }, inplace=True)

    # --- Normalize core IDs now (for downstream dedupe) ---
    df_filtered['Invoice Number'] = df_filtered['Invoice Number'].map(norm_invoice)
    df_filtered['Item Number']    = df_filtered['Item Number'].map(norm_item)

    # --- Fetch existing Firebase entries for dedupe (normalized) ---
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
    # Step 2: Ticket info (common fields)
    # =========================
    st.header("Step 2: Ticket Info")
    with st.form("ticket_meta"):
        colA, colB = st.columns(2)
        with colA:
            ticket_number = st.text_input("🎫 Ticket Number")
        with colB:
            ticket_date   = st.date_input("📅 Ticket Date", value=datetime.today())

        status = st.text_area("📜 Status / Reason")

        submitted_meta = st.form_submit_button("Continue to Row Review")

    if not submitted_meta:
        st.stop()

    # =========================
    # Step 3: Per-row Review & Edits (Sales Rep + Credit Type dropdowns)
    # =========================
    st.header("Step 3: Review & Edit Rows")

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

    # Ensure required columns exist for editing
    if 'Credit Type' not in df_filtered.columns:
        df_filtered['Credit Type'] = ""
    if 'Sales Rep' not in df_filtered.columns:
        df_filtered['Sales Rep'] = ""

    # Build an editor-friendly frame with only the columns you want to tweak + context
    review_cols = [
        'Invoice Number', 'Item Number', 'Issue Type', 'QTY',
        'Unit Price', 'Corrected Unit Price', 'Credit Request Total',
        'Requested By', 'Reason for Credit',
        'Credit Type', 'Sales Rep'  # editable via dropdowns
    ]
    review_df = df_filtered[review_cols].copy()

    st.caption("Tip: You can sort/filter in the table; edit **Credit Type** and **Sales Rep** per row.")
    edited_df = st.data_editor(
        review_df,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Credit Type": st.column_config.SelectboxColumn("Credit Type", options=credit_type_options, required=False),
            "Sales Rep": st.column_config.SelectboxColumn("Sales Rep", options=[""] + sales_rep_options, required=False),
        }
    )

    # =========================
    # Step 4: Submit to Firebase
    # =========================
    if st.button("🚀 Submit Edited Rows to Firebase"):
        ticket_norm = norm_ticket(ticket_number)
        if not ticket_norm:
            st.error("Ticket Number is required.")
            st.stop()

        count = 0
        for _, row in edited_df.iterrows():
            inv  = norm_invoice(row['Invoice Number'])
            # Tax rows don't require Item Number for dedupe
            item = None if row['Issue Type'] == 'Tax' else norm_item(row['Item Number'])

            # dedupe on normalized pair
            if row['Issue Type'] != 'Tax' and (inv, item) in existing_pairs:
                st.warning(f"⚠️ Skipped duplicate: Invoice {inv}, Item {item}")
                continue

            record = row.to_dict()

            # Normalize IDs (avoid .0 in Firebase)
            record['Invoice Number'] = inv
            record['Item Number'] = None if item is None else item

            # Attach ticket meta + mappings
            record["Ticket Number"] = ticket_norm
            record["Date"] = datetime.combine(ticket_date, datetime.min.time()).strftime("%Y-%m-%d")
            record["Status"] = as_str(status)

            # Ensure dropdown values exist
            record["Sales Rep"] = as_str(record.get("Sales Rep"))
            friendly_ct = as_str(record.get("Credit Type"))
            record["Credit Type"] = friendly_ct if friendly_ct in credit_type_options else friendly_ct

            # optional short code 'Type' kept for legacy
            record["Type"] = CREDIT_TYPE_TO_CODE.get(friendly_ct, as_str(CREDIT_TYPE_TO_CODE.get(friendly_ct, "")))

            # Clean NaNs -> None
            record = {k: (None if pd.isna(v) else v) for k, v in record.items()}

            # Push with string IDs
            if record.get("Item Number") is not None:
                record["Item Number"] = as_str(record["Item Number"])
            record["Invoice Number"] = as_str(record["Invoice Number"])
            record["Ticket Number"]  = as_str(record["Ticket Number"])

            # Add Record ID
            record["Record ID"] = f"{ticket_norm}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{count}"

            try:
                ref.push(record)
                count += 1
            except Exception as e:
                st.error(f"🔥 Submission failed for Invoice {inv}, Item {item}: {e}")

        if count:
            st.success(f"✅ {count} record(s) submitted to Firebase!")

# Logout
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()

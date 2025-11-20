# credit_request_search_app.py
from datetime import datetime
import io
from typing import List, Set

import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, db

# =========================
# CONFIG (edit as needed)
# =========================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")

DB_URL  = "https://creditapp-tm-default-rtdb.firebaseio.com/"
DB_NODE = "credit_requests"

# Field names in your Firebase records
RTN_FIELD              = "RTN_CR_No"
INVOICE_FIELD          = "Invoice Number"
ITEM_FIELD             = "Item Number"
TICKET_FIELD           = "Ticket Number"
CUSTOMER_FIELD         = "Customer Number"
CUSTOMER_NAME_FIELD    = "Customer Name"   # set to the correct column if different
STATUS_FIELD           = "Status"

MONEY_FIELDS = ["Credit Request Total", "Extended Price", "Unit Price", "Corrected Unit Price"]
ID_FIELDS    = [INVOICE_FIELD, ITEM_FIELD, TICKET_FIELD, RTN_FIELD, CUSTOMER_FIELD, "Record ID"]

# =========================
# AUTH
# =========================
def check_password() -> bool:
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

with st.sidebar:
    if st.button("Logout"):
        st.session_state.auth_ok = False
        st.rerun()

# =========================
# FIREBASE INIT
# =========================
firebase_config = dict(st.secrets["firebase"])
# Fix newline escaping in private key if needed
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {"databaseURL": DB_URL})
ref = db.reference(DB_NODE)

# =========================
# HELPERS
# =========================
def safe_str(v) -> str:
    return "" if v is None else str(v)

def norm(s: str) -> str:
    """Uppercase + strip for case-insensitive comparison."""
    return safe_str(s).strip().upper()

def clean_num_str(x):
    """
    Keep IDs as text; remove float artifacts like 1004360.0 -> 1004360.
    """
    s = "" if x is None else str(x).strip()
    if s.endswith(".0"):
        try:
            f = float(s)
            if f.is_integer():
                s = str(int(f))
        except ValueError:
            pass
    return s

def parse_pasted_list(raw: str) -> List[str]:
    """
    Parse newline/comma/tab/space list -> de-duplicated, UPPER tokens.
    """
    if not raw:
        return []
    normalized = raw.replace(",", "\n").replace("\t", "\n")
    tokens = [t.strip() for t in normalized.split("\n") if t.strip()]
    split_tokens: List[str] = []
    for t in tokens:
        # split lightweight "word word" inputs on single spaces
        if " " in t and t.count(" ") < 3:
            split_tokens.extend([s for s in t.split(" ") if s.strip()])
        else:
            split_tokens.append(t)
    seen: Set[str] = set()
    out: List[str] = []
    for t in split_tokens:
        u = t.upper()
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

# =========================
# UI
# =========================
st.title("🔍 Credit Request Search Tool")
st.markdown(
    "Search by Ticket, Invoice, Item, Invoice+Item Pair, or use **bulk paste** for "
    "**Tickets, Invoices, Items, Customers, or RTNs**."
)

search_type = st.selectbox(
    "Search By",
    [
        "Ticket Number",
        "Invoice Number",
        "Item Number",
        "Invoice + Item Pair",
        "Multiple Tickets (paste list)",        # ✅ NEW
        "Multiple Invoices (paste list)",
        "Multiple Items (paste list)",
        "Multiple Customers (paste list)",
        "Multiple RTNs (paste list)",
    ],
)

input_ticket  = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item    = st.text_input("📦 Item Number")   if search_type in ["Item Number", "Invoice + Item Pair"] else None

uploaded_file = (
    st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'", type=["csv"])
    if search_type == "Invoice + Item Pair" else None
)

bulk_text = None
customer_mode = None
customer_search_name = None

if search_type in [
    "Multiple Tickets (paste list)",          # ✅ NEW
    "Multiple Invoices (paste list)",
    "Multiple RTNs (paste list)",
    "Multiple Items (paste list)",
    "Multiple Customers (paste list)",
]:
    if "Invoices" in search_type:
        label = "Paste Invoice Numbers (one per line/commas/spaces)"
        placeholder = "INV13727629\nINV13740599\nINV14015686"
    elif "Items" in search_type:
        label = "Paste Item Numbers (one per line/commas/spaces)"
        placeholder = "ABC-678\nITEM001\n12345"
    elif "Customers" in search_type:
        label = "Paste Customer Numbers OR Name Fragments (one per line/commas/spaces)"
        placeholder = "YAM\nSEI\nSST"
    elif "Tickets" in search_type:  # ✅ NEW
        label = "Paste Ticket Numbers (one per line/commas/spaces)"
        placeholder = "R-052066\nR-048500\nR-050321"
    else:
        label = f"Paste RTNs (use the '{RTN_FIELD}' values)"
        placeholder = "RTNCM0034858\nRTNCM0034999"

    bulk_text = st.text_area(f"📋 {label}", height=200, placeholder=placeholder)

    # Extra options only for Customers:
    if search_type == "Multiple Customers (paste list)":
        customer_mode = st.radio(
            "Match mode (customers):",
            ("Contains (default)", "Starts with", "Exact"),
            horizontal=True,
            index=0
        )
        customer_search_name = st.checkbox(
            f"Also search in **{CUSTOMER_NAME_FIELD}** (not just {CUSTOMER_FIELD})",
            value=True
        )

# =========================
# SEARCH
# =========================
if st.button("🔎 Search"):
    try:
        data = ref.get()
        matches: List[dict] = []
        not_found: List[str] = []
        pasted_values: List[str] = []

        if data:
            # ----- bulk list parsing -----
            if search_type in [
                "Multiple Tickets (paste list)",      # ✅ NEW
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",
            ]:
                pasted_values = parse_pasted_list(bulk_text or "")
                if not pasted_values:
                    st.warning("⚠️ Paste at least one value to search.")
                    st.stop()
            pasted_set = set(pasted_values)

            # ----- single inputs -----
            find_ticket  = norm(input_ticket)  if input_ticket  else ""
            find_invoice = norm(input_invoice) if input_invoice else ""
            find_item    = norm(input_item)    if input_item    else ""

            # ----- CSV pair set -----
            pair_wanted = set()
            pair_mode_with_csv = (search_type == "Invoice + Item Pair" and uploaded_file is not None)
            if pair_mode_with_csv:
                pair_df = pd.read_csv(uploaded_file)
                if not {INVOICE_FIELD, ITEM_FIELD}.issubset(pair_df.columns):
                    st.error(f"CSV must contain '{INVOICE_FIELD}' and '{ITEM_FIELD}' columns.")
                    st.stop()
                pair_df[INVOICE_FIELD] = pair_df[INVOICE_FIELD].astype(str).str.strip().str.upper()
                pair_df[ITEM_FIELD]    = pair_df[ITEM_FIELD].astype(str).str.strip().str.upper()
                pair_wanted = set(zip(pair_df[INVOICE_FIELD], pair_df[ITEM_FIELD]))

            # For fuzzy customer "not found" accounting
            found_tokens = set()

            # ----- iterate DB -----
            for key, record in (data or {}).items():
                inv     = norm(record.get(INVOICE_FIELD, ""))
                item    = norm(record.get(ITEM_FIELD, ""))
                ticket  = norm(record.get(TICKET_FIELD, ""))
                status  = norm(record.get(STATUS_FIELD, ""))
                rtn     = norm(record.get(RTN_FIELD, ""))
                cust_no = norm(record.get(CUSTOMER_FIELD, ""))
                cust_nm = norm(record.get(CUSTOMER_NAME_FIELD, "")) if CUSTOMER_NAME_FIELD in record else ""

                match = False

                if search_type == "Ticket Number":
                    if ticket and ticket == find_ticket:
                        match = True

                elif search_type == "Invoice Number":
                    if inv and inv == find_invoice:
                        match = True

                elif search_type == "Item Number":
                    if item and item == find_item:
                        match = True

                elif search_type == "Invoice + Item Pair":
                    if (not pair_mode_with_csv) and input_invoice and input_item:
                        if inv == find_invoice and item == find_item:
                            match = True

                elif search_type == "Multiple Tickets (paste list)":  # ✅ NEW
                    if ticket and ticket in pasted_set:
                        match = True

                elif search_type == "Multiple Invoices (paste list)":
                    if inv and inv in pasted_set:
                        match = True

                elif search_type == "Multiple Items (paste list)":
                    if item and item in pasted_set:
                        match = True

                elif search_type == "Multiple Customers (paste list)":
                    # fuzzy: tokens can match customer number and (optionally) name
                    if customer_mode == "Exact":
                        if cust_no in pasted_set:
                            found_tokens.add(cust_no); match = True
                        if customer_search_name and cust_nm in pasted_set:
                            found_tokens.add(cust_nm); match = True
                    elif customer_mode == "Starts with":
                        for tok in pasted_set:
                            if cust_no.startswith(tok) or (customer_search_name and cust_nm.startswith(tok)):
                                found_tokens.add(tok); match = True; break
                    else:  # Contains (default)
                        for tok in pasted_set:
                            if tok in cust_no or (customer_search_name and tok in cust_nm):
                                found_tokens.add(tok); match = True; break

                elif search_type == "Multiple RTNs (paste list)":
                    if rtn and rtn in pasted_set:
                        match = True

                if match:
                    out = dict(record)
                    out["Record ID"] = key
                    matches.append(out)

            # CSV pair matches post-iteration
            if pair_mode_with_csv and pair_wanted:
                for key, record in (data or {}).items():
                    inv2  = norm(record.get(INVOICE_FIELD, ""))
                    item2 = norm(record.get(ITEM_FIELD, ""))
                    if (inv2, item2) in pair_wanted:
                        out = dict(record)
                        out["Record ID"] = key
                        out["Search_Invoice"] = inv2
                        out["Search_Item"] = item2
                        matches.append(out)

            # ----- build not_found for all bulk modes -----
            if search_type in [
                "Multiple Tickets (paste list)",      # ✅ NEW
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",
            ]:
                if search_type == "Multiple Invoices (paste list)":
                    field_name = INVOICE_FIELD
                elif search_type == "Multiple Items (paste list)":
                    field_name = ITEM_FIELD
                elif search_type == "Multiple RTNs (paste list)":
                    field_name = RTN_FIELD
                elif search_type == "Multiple Tickets (paste list)":   # ✅ NEW
                    field_name = TICKET_FIELD
                else:
                    field_name = None  # customer uses found_tokens

                if search_type == "Multiple Customers (paste list)":
                    not_found = [v for v in pasted_values if v not in found_tokens]
                else:
                    matched_values = set()
                    for rec in matches:
                        val = norm(rec.get(field_name, ""))
                        if val:
                            matched_values.add(val)
                    not_found = [v for v in pasted_values if v not in matched_values]

        # =========================
        # RESULTS UI (clean display)
        # =========================
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            if search_type in [
                "Multiple Tickets (paste list)",      # ✅ NEW
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",
            ]:
                matched_count = len(set(pasted_values) - set(not_found))
                st.info(f"🔎 Pasted: {len(pasted_values)} • ✅ Matched: {matched_count} • ❌ Not found: {len(not_found)}")

            df_export = pd.DataFrame(matches)

            # Normalize display: keep IDs as text and uppercase
            for col in ID_FIELDS:
                if col in df_export.columns:
                    df_export[col] = df_export[col].map(clean_num_str).astype("string")
            for col in [INVOICE_FIELD, ITEM_FIELD, TICKET_FIELD, CUSTOMER_FIELD]:
                if col in df_export.columns:
                    df_export[col] = df_export[col].str.upper()

            # Money rounding to kill float noise
            for col in MONEY_FIELDS:
                if col in df_export.columns:
                    df_export[col] = pd.to_numeric(df_export[col], errors="coerce").round(2)

            # Render table
            st.dataframe(
                df_export,
                use_container_width=True,
                column_config={
                    INVOICE_FIELD:  st.column_config.TextColumn(),
                    ITEM_FIELD:     st.column_config.TextColumn(),
                    TICKET_FIELD:   st.column_config.TextColumn(),
                    CUSTOMER_FIELD: st.column_config.TextColumn(),
                    RTN_FIELD:      st.column_config.TextColumn(),
                    "Record ID":    st.column_config.TextColumn(),
                    "Credit Request Total": st.column_config.NumberColumn(format="%.2f"),
                    "Extended Price":       st.column_config.NumberColumn(format="%.2f"),
                    "Unit Price":           st.column_config.NumberColumn(format="%.2f"),
                    "Corrected Unit Price": st.column_config.NumberColumn(format="%.2f"),
                },
            )

# credit_request_search_app.py
from datetime import datetime
import io
from typing import List, Set

import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, db

# =========================
# CONFIG (edit as needed)
# =========================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")

DB_URL  = "https://creditapp-tm-default-rtdb.firebaseio.com/"
DB_NODE = "credit_requests"

# Field names in your Firebase records
RTN_FIELD              = "RTN_CR_No"
INVOICE_FIELD          = "Invoice Number"
ITEM_FIELD             = "Item Number"
TICKET_FIELD           = "Ticket Number"
CUSTOMER_FIELD         = "Customer Number"
CUSTOMER_NAME_FIELD    = "Customer Name"   # set to the correct column if different
STATUS_FIELD           = "Status"

MONEY_FIELDS = ["Credit Request Total", "Extended Price", "Unit Price", "Corrected Unit Price"]
ID_FIELDS    = [INVOICE_FIELD, ITEM_FIELD, TICKET_FIELD, RTN_FIELD, CUSTOMER_FIELD, "Record ID"]

# =========================
# AUTH
# =========================
def check_password() -> bool:
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

with st.sidebar:
    if st.button("Logout"):
        st.session_state.auth_ok = False
        st.rerun()

# =========================
# FIREBASE INIT
# =========================
firebase_config = dict(st.secrets["firebase"])
# Fix newline escaping in private key if needed
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {"databaseURL": DB_URL})
ref = db.reference(DB_NODE)

# =========================
# HELPERS
# =========================
def safe_str(v) -> str:
    return "" if v is None else str(v)

def norm(s: str) -> str:
    """Uppercase + strip for case-insensitive comparison."""
    return safe_str(s).strip().upper()

def clean_num_str(x):
    """
    Keep IDs as text; remove float artifacts like 1004360.0 -> 1004360.
    """
    s = "" if x is None else str(x).strip()
    if s.endswith(".0"):
        try:
            f = float(s)
            if f.is_integer():
                s = str(int(f))
        except ValueError:
            pass
    return s

def parse_pasted_list(raw: str) -> List[str]:
    """
    Parse newline/comma/tab/space list -> de-duplicated, UPPER tokens.
    """
    if not raw:
        return []
    normalized = raw.replace(",", "\n").replace("\t", "\n")
    tokens = [t.strip() for t in normalized.split("\n") if t.strip()]
    split_tokens: List[str] = []
    for t in tokens:
        # split lightweight "word word" inputs on single spaces
        if " " in t and t.count(" ") < 3:
            split_tokens.extend([s for s in t.split(" ") if s.strip()])
        else:
            split_tokens.append(t)
    seen: Set[str] = set()
    out: List[str] = []
    for t in split_tokens:
        u = t.upper()
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

# =========================
# UI
# =========================
st.title("🔍 Credit Request Search Tool")
st.markdown(
    "Search by Ticket, Invoice, Item, Invoice+Item Pair, or use **bulk paste** for "
    "**Tickets, Invoices, Items, Customers, or RTNs**."
)

search_type = st.selectbox(
    "Search By",
    [
        "Ticket Number",
        "Invoice Number",
        "Item Number",
        "Invoice + Item Pair",
        "Multiple Tickets (paste list)",        # ✅ NEW
        "Multiple Invoices (paste list)",
        "Multiple Items (paste list)",
        "Multiple Customers (paste list)",
        "Multiple RTNs (paste list)",
    ],
)

input_ticket  = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item    = st.text_input("📦 Item Number")   if search_type in ["Item Number", "Invoice + Item Pair"] else None

uploaded_file = (
    st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'", type=["csv"])
    if search_type == "Invoice + Item Pair" else None
)

bulk_text = None
customer_mode = None
customer_search_name = None

if search_type in [
    "Multiple Tickets (paste list)",          # ✅ NEW
    "Multiple Invoices (paste list)",
    "Multiple RTNs (paste list)",
    "Multiple Items (paste list)",
    "Multiple Customers (paste list)",
]:
    if "Invoices" in search_type:
        label = "Paste Invoice Numbers (one per line/commas/spaces)"
        placeholder = "INV13727629\nINV13740599\nINV14015686"
    elif "Items" in search_type:
        label = "Paste Item Numbers (one per line/commas/spaces)"
        placeholder = "ABC-678\nITEM001\n12345"
    elif "Customers" in search_type:
        label = "Paste Customer Numbers OR Name Fragments (one per line/commas/spaces)"
        placeholder = "YAM\nSEI\nSST"
    elif "Tickets" in search_type:  # ✅ NEW
        label = "Paste Ticket Numbers (one per line/commas/spaces)"
        placeholder = "R-052066\nR-048500\nR-050321"
    else:
        label = f"Paste RTNs (use the '{RTN_FIELD}' values)"
        placeholder = "RTNCM0034858\nRTNCM0034999"

    bulk_text = st.text_area(f"📋 {label}", height=200, placeholder=placeholder)

    # Extra options only for Customers:
    if search_type == "Multiple Customers (paste list)":
        customer_mode = st.radio(
            "Match mode (customers):",
            ("Contains (default)", "Starts with", "Exact"),
            horizontal=True,
            index=0
        )
        customer_search_name = st.checkbox(
            f"Also search in **{CUSTOMER_NAME_FIELD}** (not just {CUSTOMER_FIELD})",
            value=True
        )

# =========================
# SEARCH
# =========================
if st.button("🔎 Search"):
    try:
        data = ref.get()
        matches: List[dict] = []
        not_found: List[str] = []
        pasted_values: List[str] = []

        if data:
            # ----- bulk list parsing -----
            if search_type in [
                "Multiple Tickets (paste list)",      # ✅ NEW
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",
            ]:
                pasted_values = parse_pasted_list(bulk_text or "")
                if not pasted_values:
                    st.warning("⚠️ Paste at least one value to search.")
                    st.stop()
            pasted_set = set(pasted_values)

            # ----- single inputs -----
            find_ticket  = norm(input_ticket)  if input_ticket  else ""
            find_invoice = norm(input_invoice) if input_invoice else ""
            find_item    = norm(input_item)    if input_item    else ""

            # ----- CSV pair set -----
            pair_wanted = set()
            pair_mode_with_csv = (search_type == "Invoice + Item Pair" and uploaded_file is not None)
            if pair_mode_with_csv:
                pair_df = pd.read_csv(uploaded_file)
                if not {INVOICE_FIELD, ITEM_FIELD}.issubset(pair_df.columns):
                    st.error(f"CSV must contain '{INVOICE_FIELD}' and '{ITEM_FIELD}' columns.")
                    st.stop()
                pair_df[INVOICE_FIELD] = pair_df[INVOICE_FIELD].astype(str).str.strip().str.upper()
                pair_df[ITEM_FIELD]    = pair_df[ITEM_FIELD].astype(str).str.strip().str.upper()
                pair_wanted = set(zip(pair_df[INVOICE_FIELD], pair_df[ITEM_FIELD]))

            # For fuzzy customer "not found" accounting
            found_tokens = set()

            # ----- iterate DB -----
            for key, record in (data or {}).items():
                inv     = norm(record.get(INVOICE_FIELD, ""))
                item    = norm(record.get(ITEM_FIELD, ""))
                ticket  = norm(record.get(TICKET_FIELD, ""))
                status  = norm(record.get(STATUS_FIELD, ""))
                rtn     = norm(record.get(RTN_FIELD, ""))
                cust_no = norm(record.get(CUSTOMER_FIELD, ""))
                cust_nm = norm(record.get(CUSTOMER_NAME_FIELD, "")) if CUSTOMER_NAME_FIELD in record else ""

                match = False

                if search_type == "Ticket Number":
                    if ticket and ticket == find_ticket:
                        match = True

                elif search_type == "Invoice Number":
                    if inv and inv == find_invoice:
                        match = True

                elif search_type == "Item Number":
                    if item and item == find_item:
                        match = True

                elif search_type == "Invoice + Item Pair":
                    if (not pair_mode_with_csv) and input_invoice and input_item:
                        if inv == find_invoice and item == find_item:
                            match = True

                elif search_type == "Multiple Tickets (paste list)":  # ✅ NEW
                    if ticket and ticket in pasted_set:
                        match = True

                elif search_type == "Multiple Invoices (paste list)":
                    if inv and inv in pasted_set:
                        match = True

                elif search_type == "Multiple Items (paste list)":
                    if item and item in pasted_set:
                        match = True

                elif search_type == "Multiple Customers (paste list)":
                    # fuzzy: tokens can match customer number and (optionally) name
                    if customer_mode == "Exact":
                        if cust_no in pasted_set:
                            found_tokens.add(cust_no); match = True
                        if customer_search_name and cust_nm in pasted_set:
                            found_tokens.add(cust_nm); match = True
                    elif customer_mode == "Starts with":
                        for tok in pasted_set:
                            if cust_no.startswith(tok) or (customer_search_name and cust_nm.startswith(tok)):
                                found_tokens.add(tok); match = True; break
                    else:  # Contains (default)
                        for tok in pasted_set:
                            if tok in cust_no or (customer_search_name and tok in cust_nm):
                                found_tokens.add(tok); match = True; break

                elif search_type == "Multiple RTNs (paste list)":
                    if rtn and rtn in pasted_set:
                        match = True

                if match:
                    out = dict(record)
                    out["Record ID"] = key
                    matches.append(out)

            # CSV pair matches post-iteration
            if pair_mode_with_csv and pair_wanted:
                for key, record in (data or {}).items():
                    inv2  = norm(record.get(INVOICE_FIELD, ""))
                    item2 = norm(record.get(ITEM_FIELD, ""))
                    if (inv2, item2) in pair_wanted:
                        out = dict(record)
                        out["Record ID"] = key
                        out["Search_Invoice"] = inv2
                        out["Search_Item"] = item2
                        matches.append(out)

            # ----- build not_found for all bulk modes -----
            if search_type in [
                "Multiple Tickets (paste list)",      # ✅ NEW
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",
            ]:
                if search_type == "Multiple Invoices (paste list)":
                    field_name = INVOICE_FIELD
                elif search_type == "Multiple Items (paste list)":
                    field_name = ITEM_FIELD
                elif search_type == "Multiple RTNs (paste list)":
                    field_name = RTN_FIELD
                elif search_type == "Multiple Tickets (paste list)":   # ✅ NEW
                    field_name = TICKET_FIELD
                else:
                    field_name = None  # customer uses found_tokens

                if search_type == "Multiple Customers (paste list)":
                    not_found = [v for v in pasted_values if v not in found_tokens]
                else:
                    matched_values = set()
                    for rec in matches:
                        val = norm(rec.get(field_name, ""))
                        if val:
                            matched_values.add(val)
                    not_found = [v for v in pasted_values if v not in matched_values]

        # =========================
        # RESULTS UI (clean display)
        # =========================
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            if search_type in [
                "Multiple Tickets (paste list)",      # ✅ NEW
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",
            ]:
                matched_count = len(set(pasted_values) - set(not_found))
                st.info(f"🔎 Pasted: {len(pasted_values)} • ✅ Matched: {matched_count} • ❌ Not found: {len(not_found)}")

            df_export = pd.DataFrame(matches)

            # Normalize display: keep IDs as text and uppercase
            for col in ID_FIELDS:
                if col in df_export.columns:
                    df_export[col] = df_export[col].map(clean_num_str).astype("string")
            for col in [INVOICE_FIELD, ITEM_FIELD, TICKET_FIELD, CUSTOMER_FIELD]:
                if col in df_export.columns:
                    df_export[col] = df_export[col].str.upper()

            # Money rounding to kill float noise
            for col in MONEY_FIELDS:
                if col in df_export.columns:
                    df_export[col] = pd.to_numeric(df_export[col], errors="coerce").round(2)

            # Render table
            st.dataframe(
                df_export,
                use_container_width=True,
                column_config={
                    INVOICE_FIELD:  st.column_config.TextColumn(),
                    ITEM_FIELD:     st.column_config.TextColumn(),
                    TICKET_FIELD:   st.column_config.TextColumn(),
                    CUSTOMER_FIELD: st.column_config.TextColumn(),
                    RTN_FIELD:      st.column_config.TextColumn(),
                    "Record ID":    st.column_config.TextColumn(),
                    "Credit Request Total": st.column_config.NumberColumn(format="%.2f"),
                    "Extended Price":       st.column_config.NumberColumn(format="%.2f"),
                    "Unit Price":           st.column_config.NumberColumn(format="%.2f"),
                    "Corrected Unit Price": st.column_config.NumberColumn(format="%.2f"),
                },
            )

                st.subheader("📦 JSON view (per record)")
                for i, rec in enumerate(matches, 1):
                     with st.expander(f"Record {i} — Ticket: {rec.get(TICKET_FIELD, 'N/A')}"):
                        st.json(rec)

            # CSV download
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

            # CSV download
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

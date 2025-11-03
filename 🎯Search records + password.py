from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
from typing import List, Set

# =========================
# App & Auth
# =========================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")  # use Streamlit secrets in prod
RTN_FIELD = "RTN_CR_No"  # <-- change here if your RTN field differs
INVOICE_FIELD = "Invoice Number"
ITEM_FIELD = "Item Number"
TICKET_FIELD = "Ticket Number"
STATUS_FIELD = "Status"

def check_password() -> bool:
    """Simple password gate."""
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
# Firebase Init
# =========================
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
    })
ref = db.reference("credit_requests")

# =========================
# Helpers
# =========================
def safe_str(v) -> str:
    return "" if v is None else str(v)

def norm(s: str) -> str:
    """Normalize for case-insensitive exact matches."""
    return safe_str(s).strip().upper()

def parse_pasted_list(raw: str) -> List[str]:
    """
    Parse a pasted list of values separated by newlines/commas/tabs/spaces.
    - trims, dedupes (preserving order), drops empties
    - normalizes to uppercase for case-insensitive comparisons
    """
    if not raw:
        return []
    normalized = raw.replace(",", "\n").replace("\t", "\n")
    tokens = [t.strip() for t in normalized.split("\n") if t.strip()]
    split_tokens: List[str] = []
    for t in tokens:
        # split on spaces if there are a few (avoid splitting long sentences)
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
    "Search by Ticket, Invoice, Item, Invoice+Item Pair, or use **bulk paste** for Invoices or RTNs."
)

search_type = st.selectbox(
    "Search By",
    [
        "Ticket Number",
        "Invoice Number",
        "Item Number",
        "Invoice + Item Pair",
        "Multiple Invoices (paste list)",
        "Multiple RTNs (paste list)",
    ],
)

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None

uploaded_file = (
    st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'", type=["csv"])
    if search_type == "Invoice + Item Pair" else None
)

bulk_text = None
if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
    label = "Paste Invoice Numbers (one per line/commas/spaces)" if "Invoices" in search_type \
            else f"Paste RTNs (use the '{RTN_FIELD}' values)"
    bulk_text = st.text_area(f"📋 {label}", height=200, placeholder="inv13727629\ninv13740599\nINV14015686\nRTNCM0034858")

# =========================
# Search
# =========================
if st.button("🔎 Search"):
    try:
        data = ref.get()
        matches: List[dict] = []
        not_found: List[str] = []
        pasted_values: List[str] = []

        if data:
            # Pre-parse bulk lists (already normalized to UPPER)
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
                pasted_values = parse_pasted_list(bulk_text or "")
                if not pasted_values:
                    st.warning("⚠️ Paste at least one value to search.")
                    st.stop()
            pasted_set = set(pasted_values)

            # Normalize single-inputs to UPPER for comparisons
            find_ticket = norm(input_ticket) if input_ticket else ""
            find_invoice = norm(input_invoice) if input_invoice else ""
            find_item = norm(input_item) if input_item else ""

            # If CSV pair mode with file, prep pair set after loop
            pair_wanted = set()
            pair_mode_with_csv = (search_type == "Invoice + Item Pair" and uploaded_file is not None)
            if pair_mode_with_csv:
                pair_df = pd.read_csv(uploaded_file)
                if not {INVOICE_FIELD, ITEM_FIELD}.issubset(pair_df.columns):
                    st.error(f"CSV must contain '{INVOICE_FIELD}' and '{ITEM_FIELD}' columns.")
                    st.stop()
                pair_df[INVOICE_FIELD] = pair_df[INVOICE_FIELD].astype(str).str.strip().str.upper()
                pair_df[ITEM_FIELD] = pair_df[ITEM_FIELD].astype(str).str.strip().str.upper()
                pair_wanted = set(zip(pair_df[INVOICE_FIELD], pair_df[ITEM_FIELD]))

            # Iterate DB
            for key, record in data.items():
                inv = norm(record.get(INVOICE_FIELD, ""))
                item = norm(record.get(ITEM_FIELD, ""))
                ticket = norm(record.get(TICKET_FIELD, ""))
                status = norm(record.get(STATUS_FIELD, ""))
                rtn = norm(record.get(RTN_FIELD, ""))

                match = False

                if search_type == "Ticket Number":
                    # match exact ticket or if ticket text appears in status
                    if ticket and (ticket == find_ticket or (find_ticket and find_ticket in status)):
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
                    # CSV case handled after loop using pair_wanted

                elif search_type == "Multiple Invoices (paste list)":
                    if inv and inv in pasted_set:
                        match = True

                elif search_type == "Multiple RTNs (paste list)":
                    if rtn and rtn in pasted_set:
                        match = True

                if match:
                    out = dict(record)
                    out["Record ID"] = key
                    matches.append(out)

            # Handle CSV pair matches post-iteration
            if pair_mode_with_csv and pair_wanted:
                for key, record in data.items():
                    inv = norm(record.get(INVOICE_FIELD, ""))
                    item = norm(record.get(ITEM_FIELD, ""))
                    if (inv, item) in pair_wanted:
                        out = dict(record)
                        out["Record ID"] = key
                        out["Search_Invoice"] = inv
                        out["Search_Item"] = item
                        matches.append(out)

            # Build Not Found list for bulk modes
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
                field_name = INVOICE_FIELD if "Invoices" in search_type else RTN_FIELD
                matched_values = set()
                for rec in matches:
                    val = norm(rec.get(field_name, ""))
                    if val:
                        matched_values.add(val)
                not_found = [v for v in pasted_values if v not in matched_values]

        # =========================
        # Results UI
        # =========================
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            # Bulk summary
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
                matched_count = len(set(pasted_values) - set(not_found))
                st.info(f"🔎 Pasted: {len(pasted_values)} • ✅ Matched: {matched_count} • ❌ Not found: {len(not_found)}")

            df_export = pd.DataFrame(matches)
            st.dataframe(df_export, use_container_width=True)

            with st.expander("📦 JSON view (per record)"):
                for i, rec in enumerate(matches, 1):
                    with st.expander(f"Record {i} — Ticket: {rec.get(TICKET_FIELD, 'N/A')}"):
                        st.json(rec)

            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"] and not_found:
                with st.expander("❌ Not Found"):
                    st.code("\n".join(not_found))

            # Export CSV
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

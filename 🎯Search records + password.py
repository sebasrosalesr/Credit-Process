from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
from typing import List, Set

# -------------------------------------------------
# Basic password gate (no Firebase needed to login)
# -------------------------------------------------
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")  # uses Streamlit Secret in prod
RTN_FIELD = "RTN_CR_No"  # <-- change here if your RTN column name differs

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
# Helpers
# ---------------------------
def parse_pasted_list(raw: str) -> List[str]:
    """
    Parse a pasted list separated by newlines/commas/spaces.
    - Trims whitespace
    - Deduplicates while preserving order
    - Skips empty tokens
    """
    if not raw:
        return []
    # replace common separators with newline
    normalized = raw.replace(",", "\n").replace("\t", "\n")
    tokens = [t.strip() for t in normalized.split("\n")]
    # split any residual space-delimited tokens
    split_tokens: List[str] = []
    for t in tokens:
        if not t:
            continue
        if " " in t and t.count(" ") < 3:  # avoid aggressive split for long descriptions
            split_tokens.extend([s for s in t.split(" ") if s.strip()])
        else:
            split_tokens.append(t)
    # dedupe while preserving order
    seen: Set[str] = set()
    out: List[str] = []
    for t in split_tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def safe_str(val) -> str:
    return "" if val is None else str(val)

# ---------------------------
# App UI
# ---------------------------
st.title("🔍 Credit Request Search Tool")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, Invoice+Item Pair, or paste a list for bulk lookup (Invoices / RTNs).")

search_type = st.selectbox(
    "Search By",
    [
        "Ticket Number",
        "Invoice Number",
        "Item Number",
        "Invoice + Item Pair",
        "Multiple Invoices (paste list)",
        "Multiple RTNs (paste list)",
    ]
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
    label = "Paste Invoice Numbers (one per line or separated by commas/spaces)" if "Invoices" in search_type \
            else f"Paste RTNs (use the '{RTN_FIELD}' values)"
    bulk_text = st.text_area(f"📋 {label}", height=200, placeholder="RTNCM0034858\nRTNCM0034863\nRTNCM0036815")

if st.button("🔎 Search"):
    try:
        data = ref.get()
        matches = []
        not_found: List[str] = []
        pasted_values: List[str] = []

        if data:
            # Preload pasted list if needed
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
                pasted_values = parse_pasted_list(bulk_text or "")
                if not pasted_values:
                    st.warning("⚠️ Paste at least one value to search.")
                    st.stop()

            # Build fast lookup sets for bulk modes
            pasted_set = set(pasted_values)

            # For efficiency, if doing bulk search, build a mapping of value -> list of records
            for key, record in data.items():
                inv = safe_str(record.get("Invoice Number", "")).strip()
                item = safe_str(record.get("Item Number", "")).strip()
                ticket = safe_str(record.get("Ticket Number", "")).strip()
                status = safe_str(record.get("Status", "")).strip()
                rtn = safe_str(record.get(RTN_FIELD, "")).strip()

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
                            st.stop()
                        # We'll evaluate after we load full df; set match below
                        # (We can check row-by-row match directly)
                        # Nothing here; handled after loop
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

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

            # Special handling: CSV pair lookup (evaluate after iterating)
            if search_type == "Invoice + Item Pair" and uploaded_file:
                pair_df = pd.read_csv(uploaded_file)
                pair_df["Invoice Number"] = pair_df["Invoice Number"].astype(str).str.strip()
                pair_df["Item Number"] = pair_df["Item Number"].astype(str).str.strip()
                # Build a set of tuples for quick membership test
                wanted = set(zip(pair_df["Invoice Number"], pair_df["Item Number"]))
                for key, record in data.items():
                    inv = safe_str(record.get("Invoice Number", "")).strip()
                    item = safe_str(record.get("Item Number", "")).strip()
                    if (inv, item) in wanted:
                        out = dict(record)
                        out["Record ID"] = key
                        out["Search_Invoice"] = inv
                        out["Search_Item"] = item
                        matches.append(out)

            # Not found list (only for bulk modes)
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
                field_name = "Invoice Number" if "Invoices" in search_type else RTN_FIELD
                matched_values = set()
                for rec in matches:
                    val = safe_str(rec.get(field_name, "")).strip()
                    if val:
                        matched_values.add(val)
                not_found = [v for v in pasted_values if v not in matched_values]

        # ---- Results UI ----
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")
            # Summary for bulk
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"]:
                st.info(f"🔎 Pasted values: {len(pasted_values)} • ✅ Matched: {len(set(pasted_values) - set(not_found))} • ❌ Not found: {len(not_found)}")

            # Show table + expanders
            df_export = pd.DataFrame(matches)
            st.dataframe(df_export, use_container_width=True)

            with st.expander("📦 JSON view (per record)"):
                for i, rec in enumerate(matches, 1):
                    with st.expander(f"Record {i} — Ticket: {rec.get('Ticket Number', 'N/A')}"):
                        st.json(rec)

            # Not found list (bulk only)
            if search_type in ["Multiple Invoices (paste list)", "Multiple RTNs (paste list)"] and not_found:
                with st.expander("❌ Not Found"):
                    st.code("\n".join(not_found))

            # Export
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

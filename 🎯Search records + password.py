from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
from typing import List, Set

# =========================
# CONFIG (edit as needed)
# =========================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")

APP_PASSWORD   = st.secrets.get("APP_PASSWORD", "test123")
DB_URL         = "https://creditapp-tm-default-rtdb.firebaseio.com/"
DB_NODE        = "credit_requests"

# Field names (adjust if you reindex/rename)
RTN_FIELD       = "RTN_CR_No"
INVOICE_FIELD   = "Invoice Number"
ITEM_FIELD      = "Item Number"
TICKET_FIELD    = "Ticket Number"
CUSTOMER_FIELD  = "Customer Number"   # <-- NEW
STATUS_FIELD    = "Status"

MONEY_FIELDS = ["Credit Request Total", "Extended Price", "Unit Price", "Corrected Unit Price"]
ID_FIELDS    = [INVOICE_FIELD, ITEM_FIELD, TICKET_FIELD, RTN_FIELD, CUSTOMER_FIELD, "Record ID"]  # <-- UPDATED

# ... [auth + firebase init + helpers stay the same] ...

# =========================
# UI
# =========================
st.title("🔍 Credit Request Search Tool")
st.markdown("Search by Ticket, Invoice, Item, Invoice+Item Pair, or use **bulk paste** for Invoices, Items, Customers, or RTNs.")

search_type = st.selectbox(
    "Search By",
    [
        "Ticket Number",
        "Invoice Number",
        "Item Number",
        "Invoice + Item Pair",
        "Multiple Invoices (paste list)",
        "Multiple Items (paste list)",
        "Multiple Customers (paste list)",   # <-- NEW
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
if search_type in [
    "Multiple Invoices (paste list)",
    "Multiple RTNs (paste list)",
    "Multiple Items (paste list)",
    "Multiple Customers (paste list)",    # <-- NEW
]:
    if "Invoices" in search_type:
        label = "Paste Invoice Numbers (one per line/commas/spaces)"
    elif "Items" in search_type:
        label = "Paste Item Numbers (one per line/commas/spaces)"
    elif "Customers" in search_type:      # <-- NEW
        label = "Paste Customer Numbers (one per line/commas/spaces)"
    else:
        label = f"Paste RTNs (use the '{RTN_FIELD}' values)"
    bulk_text = st.text_area(f"📋 {label}", height=200, placeholder="12345\nABC-678\nITEM001")

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
            # bulk list
            if search_type in [
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",  # <-- NEW
            ]:
                pasted_values = parse_pasted_list(bulk_text or "")
                if not pasted_values:
                    st.warning("⚠️ Paste at least one value to search.")
                    st.stop()
            pasted_set = set(pasted_values)

            # single inputs
            find_ticket  = norm(input_ticket)  if input_ticket  else ""
            find_invoice = norm(input_invoice) if input_invoice else ""
            find_item    = norm(input_item)    if input_item    else ""

            # CSV pair set
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

            # iterate DB
            for key, record in (data or {}).items():
                inv     = norm(record.get(INVOICE_FIELD, ""))
                item    = norm(record.get(ITEM_FIELD, ""))
                ticket  = norm(record.get(TICKET_FIELD, ""))
                status  = norm(record.get(STATUS_FIELD, ""))
                rtn     = norm(record.get(RTN_FIELD, ""))
                cust_no = norm(record.get(CUSTOMER_FIELD, ""))   # <-- NEW

                match = False
                if search_type == "Ticket Number":
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
                elif search_type == "Multiple Invoices (paste list)":
                    if inv and inv in pasted_set:
                        match = True
                elif search_type == "Multiple Items (paste list)":
                    if item and item in pasted_set:
                        match = True
                elif search_type == "Multiple Customers (paste list)":    # <-- NEW
                    if cust_no and cust_no in pasted_set:
                        match = True
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

            # not-found list for bulk modes (includes Customers)
            if search_type in [
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",  # <-- NEW
            ]:
                if "Invoices" in search_type:
                    field_name = INVOICE_FIELD
                elif "Items" in search_type:
                    field_name = ITEM_FIELD
                elif "Customers" in search_type:
                    field_name = CUSTOMER_FIELD   # <-- NEW
                else:
                    field_name = RTN_FIELD

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
                "Multiple Invoices (paste list)",
                "Multiple RTNs (paste list)",
                "Multiple Items (paste list)",
                "Multiple Customers (paste list)",  # <-- NEW
            ]:
                matched_count = len(set(pasted_values) - set(not_found))
                st.info(f"🔎 Pasted: {len(pasted_values)} • ✅ Matched: {matched_count} • ❌ Not found: {len(not_found)}")

            df_export = pd.DataFrame(matches)

            # Normalize display: IDs as text + uppercase
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

            # Render
            st.dataframe(
                df_export,
                use_container_width=True,
                column_config={
                    INVOICE_FIELD:  st.column_config.TextColumn(),
                    ITEM_FIELD:     st.column_config.TextColumn(),
                    TICKET_FIELD:   st.column_config.TextColumn(),
                    CUSTOMER_FIELD: st.column_config.TextColumn(),   # <-- NEW
                    RTN_FIELD:      st.column_config.TextColumn(),
                    "Record ID":    st.column_config.TextColumn(),
                    "Credit Request Total": st.column_config.NumberColumn(format="%.2f"),
                    "Extended Price":       st.column_config.NumberColumn(format="%.2f"),
                    "Unit Price":           st.column_config.NumberColumn(format="%.2f"),
                    "Corrected Unit Price": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            with st.expander("📦 JSON view (per record)"):
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

# app.py
from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
import re

# ------------------------------
# Optional: install pdfplumber if needed (Streamlit Cloud)
# ------------------------------
# import sys, subprocess
# subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=True)
import pdfplumber

# ==============================
# Firebase Initialization
# ==============================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")
st.title("🔍 Credit Request Search Tool")
st.markdown("Search by Ticket Number, Invoice Number, Item Number, or Invoice+Item Pair. "
            "Upload the **Case Files PDF** to display Background notes for each matching record's Case Number.")

firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# ==============================
# PDF Upload (case files)
# ==============================
pdf_file = st.file_uploader("📄 Upload the Case Files PDF (Background pages)", type=["pdf"])

# ==============================
# PDF Helpers (cached)
# ==============================
CASE_RE = re.compile(r"(?mi)[\u2022\-\*]?\s*Case\s*Number:\s*([A-Za-z0-9\-_]+)")
BACKGROUND_HEADER_RE = re.compile(r"(?mi)^[ \t]*Background[ \t]*:?[ \t]*$", re.MULTILINE)

def first_case_number(text: str) -> str | None:
    if not text:
        return None
    m = CASE_RE.search(text)
    return m.group(1).strip() if m else None

def is_background_page(text: str) -> bool:
    if not text:
        return False
    return bool(BACKGROUND_HEADER_RE.search(text)) and bool(CASE_RE.search(text))

@st.cache_data(show_spinner=False)
def load_pdf_pages_text(pdf_bytes: bytes) -> list[str]:
    """
    Returns a list of page texts for the PDF (index aligned to page order).
    """
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    return pages

def extract_case_notes_from_pages(pages_text: list[str], target_case: str) -> tuple[list[tuple[int, str]], str]:
    """
    Scans page-by-page. Start when we hit Background page with matching Case Number.
    Keep collecting pages (including non-background continuation pages).
    Stop at the next Background page whose Case Number is different.

    Returns:
      - collected: list of (1-based page_number, text)
      - message: "" if ok, else a warning string
    """
    target_case_norm = (target_case or "").strip().lower()
    collected: list[tuple[int, str]] = []
    started = False

    for i, txt in enumerate(pages_text, start=1):
        if not started:
            if is_background_page(txt):
                page_case = first_case_number(txt)
                if page_case and page_case.strip().lower() == target_case_norm:
                    started = True
                    collected.append((i, txt))
        else:
            # Already collecting
            if is_background_page(txt):
                page_case = first_case_number(txt)
                # If we reached the next Background page with a DIFFERENT case, we stop BEFORE this page
                if page_case and page_case.strip().lower() != target_case_norm:
                    break
                # Same case -> keep collecting
                collected.append((i, txt))
            else:
                # Continuation page (no Background header)
                collected.append((i, txt))

    if not collected:
        return collected, f"⚠️ Case Number '{target_case}' not found in PDF."
    return collected, ""

# ==============================
# Search UI
# ==============================
search_type = st.selectbox("Search By", ["Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"])

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None
uploaded_file = st.file_uploader("📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'",
                                 type=["csv"]) if search_type == "Invoice + Item Pair" else None

# ==============================
# Search Action
# ==============================
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

                # Ticket Number
                if search_type == "Ticket Number":
                    ticket_search = (input_ticket or "").strip().lower()
                    if ticket.lower() == ticket_search or ticket_search in status.lower():
                        match = True

                # Invoice Number
                elif search_type == "Invoice Number":
                    if inv == (input_invoice or "").strip():
                        match = True

                # Item Number
                elif search_type == "Item Number":
                    if item == (input_item or "").strip():
                        match = True

                # Invoice + Item Pair
                elif search_type == "Invoice + Item Pair":
                    if uploaded_file:
                        pair_df = pd.read_csv(uploaded_file)
                        if not {'Invoice Number', 'Item Number'}.issubset(pair_df.columns):
                            st.error("CSV must contain 'Invoice Number' and 'Item Number' columns.")
                            break
                        for _, row in pair_df.iterrows():
                            target_inv = str(row['Invoice Number']).strip()
                            target_item = str(row['Item Number']).strip()
                            if inv == target_inv and item == target_item:
                                match = True
                                record["Search_Invoice"] = target_inv
                                record["Search_Item"] = target_item
                                break
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                if match:
                    record = dict(record)  # copy
                    record["Record ID"] = key
                    matches.append(record)

        # --------------------------
        # Results + PDF Background Notes
        # --------------------------
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            # Load PDF pages once (if provided)
            pages_text = None
            if pdf_file is not None:
                pages_text = load_pdf_pages_text(pdf_file.read())

            for i, record in enumerate(matches, start=1):
                header = f"📌 Record {i} — Ticket: {record.get('Ticket Number', 'N/A')}"
                with st.expander(header, expanded=False):
                    # Show Firebase record
                    st.subheader("Firebase Record")
                    st.json(record)

                    # Show Background notes (if we have a Case Number + PDF uploaded)
                    case_num = str(record.get("Case Number", "")).strip()
                    if case_num and pages_text is not None:
                        st.subheader(f"Background Notes — Case {case_num}")
                        collected, msg = extract_case_notes_from_pages(pages_text, case_num)
                        if msg:
                            st.warning(msg)
                        else:
                            # Pretty print each collected page
                            for pg, txt in collected:
                                st.markdown(f"**Page {pg}**")
                                # Use a text_area to allow scrolling without breaking layout
                                st.text_area(label=f"Page {pg} text",
                                             value=txt,
                                             height=300,
                                             key=f"case_{case_num}_page_{pg}")
                    else:
                        if not case_num:
                            st.info("ℹ️ This record has no 'Case Number' field. Add 'Case Number' in Firebase to pull notes.")
                        elif pages_text is None:
                            st.info("ℹ️ Upload the Case Files PDF above to display Background notes.")

            # Download CSV of results (unchanged)
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

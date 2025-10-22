# app.py
from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
import re
import sys, subprocess
import pdfplumber  # type: ignore


# ==============================
# Streamlit page
# ==============================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")
st.title("🔍 Credit Request Search Tool")
st.markdown(
    "Search by **Ticket Number**, **Invoice Number**, **Item Number**, or **Invoice + Item Pair**. "
    "Upload the **Case Files PDF** to display Background notes for each matching **Ticket Number** "
    "(which equals the PDF’s **Case Number**)."
)

# ==============================
# Firebase Initialization
# ==============================
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
# Regex & Helpers
# ==============================
# Accepts bullets like "•" optionally, and captures the case value (letters/digits/dashes/underscores)
CASE_RE = re.compile(r"(?mi)[\u2022\-\*]?\s*Case\s*Number:\s*([A-Za-z0-9\-_]+)")
BACKGROUND_HEADER_RE = re.compile(r"(?mi)^[ \t]*Background[ \t]*:?[ \t]*$", re.MULTILINE)

def norm_case(s: str | None) -> str:
    """
    Normalize ticket/case number for robust comparisons.
    - Trim spaces
    - Uppercase
    - Replace fancy dashes with standard '-'
    - Collapse multiple spaces
    """
    if not s:
        return ""
    x = s.strip().upper()
    # normalize dash variants
    x = x.replace("–", "-").replace("—", "-").replace("-", "-").replace("–", "-")
    # collapse spaces
    x = re.sub(r"\s+", "", x)  # most cases are like R-051442 -> keep dash only
    return x

def first_case_number(text: str) -> str | None:
    if not text:
        return None
    m = CASE_RE.search(text)
    return norm_case(m.group(1)) if m else None

def is_background_page(text: str) -> bool:
    if not text:
        return False
    return bool(BACKGROUND_HEADER_RE.search(text)) and bool(CASE_RE.search(text))

@st.cache_data(show_spinner=False)
def load_pdf_pages_text(pdf_bytes: bytes) -> list[str]:
    """
    Read all pages as text (list aligned to page order).
    """
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    return pages

def extract_case_notes_from_pages(pages_text: list[str], target_ticket: str) -> tuple[list[tuple[int, str]], str]:
    """
    Given the full PDF text (page by page) and a target ticket number,
    start collecting at the Background page whose Case Number == ticket,
    continue through subsequent pages (including non-background continuation pages),
    and stop at the next Background page whose Case Number is DIFFERENT.

    Returns:
      - collected: list of (1-based page_number, page_text)
      - message: "" if ok, else warning.
    """
    target_norm = norm_case(target_ticket)
    if not target_norm:
        return [], "⚠️ Empty ticket number provided."

    collected: list[tuple[int, str]] = []
    started = False

    for i, txt in enumerate(pages_text, start=1):
        if not started:
            if is_background_page(txt):
                page_case = first_case_number(txt)
                if page_case and page_case == target_norm:
                    started = True
                    collected.append((i, txt))
        else:
            if is_background_page(txt):
                page_case = first_case_number(txt)
                if page_case and page_case != target_norm:
                    break  # stop BEFORE this new case
                collected.append((i, txt))
            else:
                collected.append((i, txt))  # continuation page

    if not collected:
        return collected, f"⚠️ Ticket '{target_ticket}' was not found in the PDF (as Case Number)."
    return collected, ""

# ==============================
# Search UI
# ==============================
search_type = st.selectbox("Search By", ["Ticket Number", "Invoice Number", "Item Number", "Invoice + Item Pair"])

input_ticket = st.text_input("🎫 Ticket Number") if search_type == "Ticket Number" else None
input_invoice = st.text_input("📄 Invoice Number") if search_type in ["Invoice Number", "Invoice + Item Pair"] else None
input_item = st.text_input("📦 Item Number") if search_type in ["Item Number", "Invoice + Item Pair"] else None
uploaded_file = st.file_uploader(
    "📤 (Optional) Upload CSV with 'Invoice Number' and 'Item Number'",
    type=["csv"]
) if search_type == "Invoice + Item Pair" else None

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
                    r = dict(record)  # copy to avoid mutating
                    r["Record ID"] = key
                    matches.append(r)

        # --------------------------
        # Results + PDF Background Notes by Ticket
        # --------------------------
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            # Load PDF once if provided
            pages_text = load_pdf_pages_text(pdf_file.read()) if pdf_file else None

            for i, record in enumerate(matches, start=1):
                header = f"📌 Record {i} — Ticket: {record.get('Ticket Number', 'N/A')}"
                with st.expander(header, expanded=False):
                    # Firebase record
                    st.subheader("Firebase Record")
                    st.json(record)

                    # Background notes using Ticket Number (equals Case Number in PDF)
                    ticket_val = str(record.get("Ticket Number", "")).strip()
                    if ticket_val and pages_text is not None:
                        st.subheader(f"Background Notes — Case/Ticket {ticket_val}")
                        collected, msg = extract_case_notes_from_pages(pages_text, ticket_val)
                        if msg:
                            st.warning(msg)
                        else:
                            for pg, txt in collected:
                                st.markdown(f"**Page {pg}**")
                                st.text_area(
                                    label=f"Page {pg} text",
                                    value=txt,
                                    height=300,
                                    key=f"ticket_{norm_case(ticket_val)}_pg_{pg}"
                                )
                    else:
                        if not ticket_val:
                            st.info("ℹ️ This record has no 'Ticket Number'. Add it in Firebase to pull notes.")
                        elif pages_text is None:
                            st.info("ℹ️ Upload the Case Files PDF above to display Background notes.")

            # Download CSV of results
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

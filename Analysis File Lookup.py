# app.py
from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io, re, sys, subprocess
import pdfplumber

# ==============================
# Streamlit setup
# ==============================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")
st.title("🔍 Credit Request Search Tool")
st.markdown("""
Search by **Ticket Number**, **Invoice Number**, **Item Number**, or **Invoice + Item Pair**.  
Upload the **Case Files PDF** to display Background notes for each matching **Ticket Number**.
""")

# ==============================
# Firebase initialization
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
# PDF Upload
# ==============================
pdf_file = st.file_uploader("📄 Upload the Case Files PDF (Background pages)", type=["pdf"])

# ==============================
# Regex helpers
# ==============================
CASE_RE = re.compile(r"(?mi)[\u2022\-\*]?\s*Case\s*Number:\s*([A-Za-z0-9\-_]+)")
BACKGROUND_HEADER_RE = re.compile(r"(?mi)^[ \t]*Background[ \t]*:?[ \t]*$", re.MULTILINE)

def norm_case(s: str | None) -> str:
    if not s:
        return ""
    s = s.strip().upper().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", s)

def first_case_number(text: str) -> str | None:
    if not text:
        return None
    m = CASE_RE.search(text)
    return norm_case(m.group(1)) if m else None

def is_background_page(text: str) -> bool:
    return bool(BACKGROUND_HEADER_RE.search(text) and CASE_RE.search(text))

@st.cache_data(show_spinner=False)
def load_pdf_pages_text(pdf_bytes: bytes) -> list[str]:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    return pages

def extract_case_notes_from_pages(pages_text: list[str], target_ticket: str):
    """Collect all pages for a case until the next Background with a different case number."""
    target_norm = norm_case(target_ticket)
    collected = []
    started = False
    for i, txt in enumerate(pages_text, start=1):
        if not started:
            if is_background_page(txt):
                page_case = first_case_number(txt)
                if page_case == target_norm:
                    started = True
                    collected.append((i, txt))
        else:
            if is_background_page(txt):
                page_case = first_case_number(txt)
                if page_case and page_case != target_norm:
                    break
                collected.append((i, txt))
            else:
                collected.append((i, txt))
    if not collected:
        return collected, f"⚠️ Ticket '{target_ticket}' not found in PDF."
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
                        df = pd.read_csv(uploaded_file)
                        for _, row in df.iterrows():
                            if inv == str(row['Invoice Number']).strip() and item == str(row['Item Number']).strip():
                                match = True
                                break
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                if match:
                    r = dict(record)
                    r["Record ID"] = key
                    matches.append(r)

        # =====================
        # Results + Notes
        # =====================
        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")

            pages_text = load_pdf_pages_text(pdf_file.read()) if pdf_file else None

            for rec_index, record in enumerate(matches, start=1):
                header = f"📌 Record {rec_index} — Ticket: {record.get('Ticket Number', 'N/A')}"
                with st.expander(header, expanded=False):
                    st.subheader("Firebase Record")
                    st.json(record)

                    ticket_val = str(record.get("Ticket Number", "")).strip()
                    if ticket_val and pages_text is not None:
                        st.subheader(f"Background Notes — Ticket {ticket_val}")
                        collected, msg = extract_case_notes_from_pages(pages_text, ticket_val)
                        if msg:
                            st.warning(msg)
                        else:
                            for idx, (pg, txt) in enumerate(collected, start=1):
                                st.markdown(f"**Page {pg}**")
                                # ✅ Unique key includes record index
                                st.text_area(
                                    label=f"Page {pg} text",
                                    value=txt,
                                    height=300,
                                    key=f"ticket_{norm_case(ticket_val)}_rec_{rec_index}_pg_{pg}"
                                )
                    else:
                        if not ticket_val:
                            st.info("ℹ️ This record has no 'Ticket Number'. Add one in Firebase.")
                        elif pages_text is None:
                            st.info("ℹ️ Upload the Case Files PDF above to display Background notes.")

            # Download CSV
            df_export = pd.DataFrame(matches)
            buf = io.StringIO()
            df_export.to_csv(buf, index=False)
            st.download_button(
                label="⬇️ Download Results as CSV",
                data=buf.getvalue(),
                file_name="credit_request_results.csv",
                mime="text/csv"
            )
        else:
            st.warning("❌ No matching records found.")

    except Exception as e:
        st.error(f"🔥 Error retrieving records: {e}")

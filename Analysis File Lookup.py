# app.py
from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io, re, sys, subprocess

# --- install pdfplumber dynamically ---
try:
    import pdfplumber
except ModuleNotFoundError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=True)
    import pdfplumber

# ==============================
# Streamlit setup
# ==============================
st.set_page_config(page_title="Credit Request Search Tool", layout="wide")
st.title("🔍 Credit Request Search Tool")
st.markdown("""
Search by **Ticket Number**, **Invoice Number**, **Item Number**, or **Invoice + Item Pair**.  
Upload the **Case Files PDF** to display Background notes that match each Firebase record's **Ticket (Case)** + **Invoice** + **Item**.
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
# Regex & normalizers
# ==============================
CASE_RE         = re.compile(r"(?mi)[\u2022\-\*]?\s*Case\s*Number:\s*([A-Za-z0-9\-_]+)")
BACKGROUND_HDR  = re.compile(r"(?mi)^[ \t]*Background[ \t]*:?[ \t]*$", re.MULTILINE)
INVOICE_RE      = re.compile(r"(?mi)[\u2022\-\*]?\s*Invoice\s*Number:\s*([A-Za-z0-9\-\_]+)")
ITEM_RE         = re.compile(r"(?mi)[\u2022\-\*]?\s*Item\s*Number:\s*([A-Za-z0-9\-\_/]+)")

def norm_case(s: str | None) -> str:
    if not s: return ""
    s = s.strip().upper().replace("–","-").replace("—","-")
    return re.sub(r"\s+", "", s)

def norm_invoice(s: str | None) -> str:
    """Lower, strip spaces/dashes, keep alnum only; keep leading 'inv' if present to be consistent."""
    if not s: return ""
    s = s.strip().lower()
    s = s.replace("–","-").replace("—","-")
    s = re.sub(r"[^a-z0-9]", "", s)  # keep letters+digits
    return s

def norm_item(s: str | None) -> str:
    """Upper, remove spaces; keep dashes/letters/digits by removing spaces then lowering case sensitivity."""
    if not s: return ""
    s = s.strip().upper().replace("–","-").replace("—","-")
    s = re.sub(r"\s+", "", s)
    return s

def first_case_number(text: str) -> str | None:
    m = CASE_RE.search(text or "")
    return norm_case(m.group(1)) if m else None

def is_background_page(text: str) -> bool:
    t = text or ""
    return bool(BACKGROUND_HDR.search(t) and CASE_RE.search(t))

def parse_form_fields(text: str) -> dict:
    """
    Extract Case/Invoice/Item from a Background page.
    Returns dict with raw & normalized versions.
    """
    t = text or ""
    case_m    = CASE_RE.search(t)
    inv_m     = INVOICE_RE.search(t)
    item_m    = ITEM_RE.search(t)
    raw_case  = case_m.group(1) if case_m else ""
    raw_inv   = inv_m.group(1) if inv_m else ""
    raw_item  = item_m.group(1) if item_m else ""
    return {
        "case_raw": raw_case,
        "invoice_raw": raw_inv,
        "item_raw": raw_item,
        "case": norm_case(raw_case),
        "invoice": norm_invoice(raw_inv),
        "item": norm_item(raw_item),
    }

@st.cache_data(show_spinner=False)
def load_pdf_pages_text(pdf_bytes: bytes) -> list[str]:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    return pages

def collect_pages_for_case(pages_text: list[str], target_ticket: str) -> list[tuple[int, str]]:
    """
    Collect all pages for the given ticket (== case), stopping at the next Background with different case.
    """
    target_norm = norm_case(target_ticket)
    out, started = [], False
    for i, txt in enumerate(pages_text, start=1):
        if not started:
            if is_background_page(txt):
                fields = parse_form_fields(txt)
                if fields["case"] == target_norm:
                    started = True
                    out.append((i, txt))
        else:
            if is_background_page(txt):
                fields = parse_form_fields(txt)
                if fields["case"] and fields["case"] != target_norm:
                    break
                out.append((i, txt))
            else:
                out.append((i, txt))
    return out

def match_notes_to_record(pages_for_case: list[tuple[int, str]], record_invoice: str, record_item: str):
    """
    From the collected pages for the case, return only the subset whose form block (on a Background page)
    has Invoice+Item matching the Firebase record (normalized). Continuation pages after a matching
    Background page are included until the next Background page (which will be handled by the caller).
    """
    inv_norm = norm_invoice(record_invoice)
    item_norm = norm_item(record_item)

    matched_pages = []
    include = False  # are we currently in a matching block?
    for i, txt in pages_for_case:
        if is_background_page(txt):
            fields = parse_form_fields(txt)
            # start a new block; decide include based on form fields
            include = (fields["invoice"] == inv_norm) and (fields["item"] == item_norm)
            if include:
                matched_pages.append((i, txt))
        else:
            # continuation page: include only if the previous Background matched
            if include:
                matched_pages.append((i, txt))

    return matched_pages

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
                        if not {'Invoice Number', 'Item Number'}.issubset(df.columns):
                            st.error("CSV must contain 'Invoice Number' and 'Item Number'.")
                            break
                        for _, row in df.iterrows():
                            if (inv == str(row['Invoice Number']).strip()
                                and item == str(row['Item Number']).strip()):
                                match = True
                                break
                    elif input_invoice and input_item:
                        if inv == input_invoice.strip() and item == input_item.strip():
                            match = True

                if match:
                    r = dict(record)
                    r["Record ID"] = key
                    matches.append(r)

        if matches:
            st.success(f"✅ {len(matches)} record(s) found.")
            pages_text = load_pdf_pages_text(pdf_file.read()) if pdf_file else None

            for rec_index, record in enumerate(matches, start=1):
                header = f"📌 Record {rec_index} — Ticket: {record.get('Ticket Number', 'N/A')}"
                with st.expander(header, expanded=False):
                    st.subheader("Firebase Record")
                    st.json(record)

                    ticket_val = str(record.get("Ticket Number", "")).strip()
                    inv_val    = str(record.get("Invoice Number", "")).strip()
                    item_val   = str(record.get("Item Number", "")).strip()

                    if ticket_val and pages_text is not None:
                        # collect the pages for the ticket/case
                        pages_for_case = collect_pages_for_case(pages_text, ticket_val)

                        if not pages_for_case:
                            st.warning(f"⚠️ Ticket '{ticket_val}' not found in PDF.")
                        else:
                            # Narrow to invoice+item match
                            matched = match_notes_to_record(pages_for_case, inv_val, item_val)

                            if matched:
                                st.subheader(f"Background Notes — {ticket_val} | Invoice {inv_val} | Item {item_val}")
                                for idx, (pg, txt) in enumerate(matched, start=1):
                                    st.markdown(f"**Page {pg}**")
                                    st.text_area(
                                        label=f"Page {pg} text",
                                        value=txt,
                                        height=300,
                                        key=f"ticket_{norm_case(ticket_val)}_rec_{rec_index}_pg_{pg}"
                                    )
                            else:
                                # show quick peek of what PDF has for the first page (to help debug mismatch)
                                # parse first Background page fields for transparency
                                first_bg_idx = next((i for (i, t) in pages_for_case if is_background_page(t)), None)
                                fields = parse_form_fields(next((t for (_, t) in pages_for_case if is_background_page(t)), ""))

                                st.info(
                                    "ℹ️ No Background pages matched both Invoice and Item for this record.\n\n"
                                    f"**Record:** Invoice `{inv_val}`, Item `{item_val}`  \n"
                                    f"**PDF (first Background for case {ticket_val}):** "
                                    f"Invoice `{fields.get('invoice_raw','')}`, Item `{fields.get('item_raw','')}`"
                                )
                    else:
                        if not ticket_val:
                            st.info("ℹ️ This record has no 'Ticket Number'. Add one in Firebase.")
                        elif pages_text is None:
                            st.info("ℹ️ Upload the Case Files PDF above to display Background notes.")

            # Download CSV of results
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

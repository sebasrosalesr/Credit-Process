# ============================
# TwinMed Invoice → Standard Schema (Streamlit, clean UI)
# ============================
from __future__ import annotations
import io, os, re, json, tempfile
from typing import List, Dict, Optional

import streamlit as st
import pandas as pd

# ---------- UI CONFIG ----------
st.set_page_config(page_title="TwinMed Invoice → Standard Schema", layout="wide")
st.title("🧾 TwinMed Invoice → Standard Schema")
st.caption("Parses TwinMed invoice PDFs and outputs rows in your standard format. "
           "Unit Price comes from the **Price** column when available.")

STANDARD_COLUMNS = [
    'Date','Credit Type','Issue Type','Customer Number','Invoice Number',
    'Item Number','QTY','Unit Price','Extended Price','Corrected Unit Price',
    'Extended Correct Price','Item Non-Taxable Credit','Item Taxable Credit',
    'Credit Request Total','Requested By','Reason for Credit','Status','Ticket Number'
]

DEFAULTS = {
    'Credit Type': '',
    'Issue Type': '',
    'Corrected Unit Price': '',
    'Extended Correct Price': '',
    'Item Non-Taxable Credit': '',
    'Item Taxable Credit': '',
    'Credit Request Total': '',
    'Requested By': '',
    'Reason for Credit': '',
    'Status': '',
    'Ticket Number': ''
}

# ---------- HELPERS ----------
def norm_money(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.strip().replace('$', '')
    s = re.sub(r',(?!\d{3}\b)', '', s)
    neg = s.startswith('(') and s.endswith(')')
    s = s.replace('(', '').replace(')', '')
    m = re.search(r'-?\d+(?:\.\d{2})?', s)
    if not m:
        return None
    v = float(m.group(0))
    return -v if neg else v

def first_match(pattern: str, text: str, flags=re.I|re.M) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

def get_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def parse_header(text: str) -> Dict[str, Optional[str]]:
    # Invoice No
    invoice_no = first_match(r'^\s*Invoice\s*No\s*:\s*([A-Z0-9\-]+)\s*$', text) \
              or first_match(r'Invoice\s*No\s*:\s*([A-Z0-9\-]+)', text)

    # Invoice Date (ONLY from "Invoice Date:")
    date_pat = r'([A-Za-z]{3,}\s+\d{1,2},?\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
    invoice_date_raw = first_match(rf'^\s*Invoice\s*Date\s*:\s*{date_pat}\s*$', text) \
                    or first_match(rf'Invoice\s*Date\s*:\s*{date_pat}', text)
    invoice_date = None
    if invoice_date_raw:
        parsed = pd.to_datetime(invoice_date_raw, errors='coerce')
        invoice_date = parsed.date().isoformat() if not pd.isna(parsed) else invoice_date_raw

    # Customer Account FLD02 No.: 808
    account_code = None
    account_no = None
    m = re.search(r'^\s*Customer\s+Account\s+([A-Z0-9\-]+)\s+No\.\s*:\s*([A-Z0-9\-]+)\s*$',
                  text, flags=re.I|re.M)
    if m:
        account_code, account_no = m.group(1).strip(), m.group(2).strip()
    else:
        account_code = first_match(r'Customer\s+Account\s+([A-Z0-9\-]+)\b', text)
        account_no   = first_match(r'Customer\s+(?:No\.|Number)\s*:\s*([A-Z0-9\-]+)', text)

    # Prefer the numeric customer number if present; else fall back to account code
    customer_no = account_no or account_code

    # Totals (for sanity check)
    subtotal = first_match(r'^\s*Sub\s*Total\s+([$\(\)0-9,.\-]+)\s*$', text) \
           or first_match(r'^\s*Subtotal\s+([$\(\)0-9,.\-]+)\s*$', text)
    tax      = first_match(r'^\s*Tax\s+([$\(\)0-9,.\-]+)\s*$', text)
    total    = first_match(r'^\s*(?:Invoice\s+)?Total\s+([$\(\)0-9,.\-]+)\s*$', text)

    return {
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "customer_no": customer_no,
        "account_code": account_code,
        "account_no": account_no,
        "subtotal": norm_money(subtotal) if subtotal else None,
        "tax": norm_money(tax) if tax else None,
        "total": norm_money(total) if total else None,
    }

def camelot_extract_tempfile(pdf_bytes: bytes):
    try:
        import camelot
    except Exception:
        return []
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    dfs = []
    try:
        try:
            t = camelot.read_pdf(tmp_path, flavor="lattice", pages="all")
            if len(t): dfs.extend([x.df for x in t])
        except Exception:
            pass
        try:
            t = camelot.read_pdf(tmp_path, flavor="stream", pages="all", row_tol=10, column_tol=15)
            if len(t): dfs.extend([x.df for x in t])
        except Exception:
            pass
    finally:
        try: os.remove(tmp_path)
        except Exception: pass
    return dfs

def is_item_row(cells: List[str]) -> bool:
    if not cells: return False
    first = str(cells[0]).strip()
    if not re.fullmatch(r'[A-Z0-9\-\/]{4,}', first): return False
    return re.search(r'\$?\d+(?:,\d{3})*(?:\.\d{2})?', " ".join(map(str, cells))) is not None

def _normalize_headers(cells):
    return [re.sub(r'\s+', ' ', str(x).strip().lower()) for x in cells]

def _build_col_map(header_cells):
    h = _normalize_headers(header_cells)
    idx = { "item": None, "price": None, "unit": None, "qty": None, "total": None, "desc": None }
    for i, val in enumerate(h):
        if idx["item"]  is None and ("twinmed item" in val or val.startswith("item")): idx["item"]  = i
        if idx["price"] is None and ("price" in val and "unit" not in val and "total" not in val): idx["price"] = i
        if idx["unit"]  is None and (val == "unit" or "uom" in val): idx["unit"]  = i
        if idx["qty"]   is None and ("qty" in val or "quantity" in val): idx["qty"]   = i
        if idx["total"] is None and ("total" in val): idx["total"] = i
        if idx["desc"]  is None and ("desc" in val or "description" in val): idx["desc"]  = i
    if idx["item"] is None and len(h) > 0: idx["item"] = 0
    return idx

def pick_items_table(dfs):
    if not dfs: return None
    def score(df):
        headers = " ".join(df.iloc[0].astype(str).tolist()).lower() if len(df) else ""
        hits = sum(kw in headers for kw in ["item", "twinmed", "qty", "unit", "price", "total", "description"])
        rowscore = 0
        for i in range(min(len(df), 60)):
            row = df.iloc[i].astype(str).tolist()
            if is_item_row(row): rowscore += 1
        return (hits, rowscore)
    return max(dfs, key=score)

def parse_items_from_table(df: pd.DataFrame) -> List[Dict[str, Optional[str]]]:
    if df is None or df.empty: return []
    header_idx = None
    for r in range(min(3, len(df))):
        cells = df.iloc[r].astype(str).tolist()
        lc = " ".join(_normalize_headers(cells))
        if any(w in lc for w in ["twinmed item", "description", "price", "qty", "unit", "total"]):
            header_idx = r; break
    rows = []
    if header_idx is not None:
        colmap = _build_col_map(df.iloc[header_idx].astype(str).tolist())
        for i in range(header_idx + 1, len(df)):
            cells = df.iloc[i].astype(str).tolist()
            # Item
            item_no = None
            if colmap["item"] is not None and colmap["item"] < len(cells):
                cand = cells[colmap["item"]].strip()
                if re.fullmatch(r'[A-Z0-9\-\/]{4,}', cand): item_no = cand
            if not item_no: continue
            # Qty
            qty = None
            if colmap["qty"] is not None and colmap["qty"] < len(cells):
                qraw = cells[colmap["qty"]].strip()
                if re.fullmatch(r'\d{1,4}', qraw): qty = int(qraw)
            # Prices
            unit_price = None
            if colmap["price"] is not None and colmap["price"] < len(cells):
                unit_price = norm_money(cells[colmap["price"]])
            ext_price = None
            if colmap["total"] is not None and colmap["total"] < len(cells):
                ext_price = norm_money(cells[colmap["total"]])
            # Gentle fallback
            if unit_price is None or ext_price is None:
                monies = [norm_money(c) for c in cells if norm_money(c) is not None]
                if unit_price is None and len(monies) >= 2: unit_price = monies[-2]
                if ext_price  is None and len(monies) >= 1: ext_price  = monies[-1]
            rows.append({"Item Number": item_no, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
        return rows
    # legacy
    for i in range(len(df)):
        cells = df.iloc[i].astype(str).tolist()
        if not is_item_row(cells): continue
        item_no = cells[0].strip()
        qty = None
        for c in cells:
            if re.fullmatch(r'\d{1,4}', c.strip()):
                qty = int(c.strip()); break
        monies = [norm_money(c) for c in cells if norm_money(c) is not None]
        unit_price = ext_price = None
        if len(monies) >= 2:
            unit_price, ext_price = monies[-2], monies[-1]
        elif len(monies) == 1:
            ext_price = monies[-1]
        rows.append({"Item Number": item_no, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
    return rows

def regex_items_fallback(text: str) -> List[Dict[str, Optional[str]]]:
    """
    Match lines like:
    1008275 ... 14.70 BX 3 44.10
                 ^price ^unit ^qty ^total
    """
    out = []
    UNIT_TOKENS = r'(?:EA|BX|CS|PK|BG|BT|DZ|PR|RL|ST|CT)'  # non-capturing so group indexes stay stable
    item_line = re.compile(r'^([A-Z0-9][A-Z0-9\-\/]{3,})\b(.*)$')

    for ln in text.splitlines():
        ln = ln.strip()
        m0 = item_line.match(ln)
        if not m0:
            continue

        item_no, tail = m0.group(1), m0.group(2)

        m = re.search(
            rf'(\$?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s+{UNIT_TOKENS}\s+(\d{{1,4}})\s+(\$?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*$',
            tail, flags=re.I
        )
        if m:
            unit_price = norm_money(m.group(1))
            try:
                qty = int(m.group(2))
            except Exception:
                qty = None
            ext_price  = norm_money(m.group(3))
        else:
            monies = re.findall(r'\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?', tail)
            if not monies:
                continue
            ext_price = norm_money(monies[-1])
            unit_price = norm_money(monies[-2]) if len(monies) >= 2 else None
            ints = re.findall(r'\b\d{1,4}\b', tail)
            qty = int(ints[-1]) if ints else None

        out.append({
            "Item Number": item_no,
            "QTY": qty,
            "Unit Price": unit_price,
            "Extended Price": ext_price
        })
    return out

def to_standard_rows(header: Dict[str,str], items: List[Dict[str, Optional[str]]]) -> List[Dict[str, Optional[str]]]:
    rows = []
    for it in items:
        rows.append({
            'Date': header.get('invoice_date') or '',
            'Credit Type': DEFAULTS['Credit Type'],
            'Issue Type': DEFAULTS['Issue Type'],
            'Customer Number': header.get('customer_no') or '',
            'Invoice Number': header.get('invoice_no') or '',
            'Item Number': it.get('Item Number'),
            'QTY': it.get('QTY'),
            'Unit Price': it.get('Unit Price'),
            'Extended Price': it.get('Extended Price'),
            'Corrected Unit Price': DEFAULTS['Corrected Unit Price'],
            'Extended Correct Price': DEFAULTS['Extended Correct Price'],
            'Item Non-Taxable Credit': DEFAULTS['Item Non-Taxable Credit'],
            'Item Taxable Credit': DEFAULTS['Item Taxable Credit'],
            'Credit Request Total': DEFAULTS['Credit Request Total'],
            'Requested By': DEFAULTS['Requested By'],
            'Reason for Credit': DEFAULTS['Reason for Credit'],
            'Status': DEFAULTS['Status'],
            'Ticket Number': DEFAULTS['Ticket Number'],
        })
    return rows

def pdf_to_standard_df(pdf_bytes: bytes) -> pd.DataFrame:
    text = get_text_from_pdf_bytes(pdf_bytes)
    header = parse_header(text)
    dfs = camelot_extract_tempfile(pdf_bytes)
    items = []
    if dfs:
        table = pick_items_table(dfs)
        if table is not None:
            items = parse_items_from_table(table)
    if not items:
        items = regex_items_fallback(text)
    rows = to_standard_rows(header, items)
    df = pd.DataFrame(rows, columns=STANDARD_COLUMNS)
    if not df.empty:
        # Helpful header echo (not part of your schema)
        df.insert(0, "Header: Customer", header.get("customer_no"))
        df.insert(1, "Header: Invoice", header.get("invoice_no"))
        df.insert(2, "Header: Date", header.get("invoice_date"))
    return df

# ---------- UI: Upload & Parse ----------
uploaded = st.file_uploader("Upload a TwinMed PDF invoice", type=["pdf"], accept_multiple_files=False)

if uploaded:
    try:
        st.info(f"Parsing **{uploaded.name}** …")
        pdf_bytes = uploaded.read()
        df = pdf_to_standard_df(pdf_bytes)
        if df.empty:
            st.error("No line items detected in the PDF.")
        else:
            st.success(f"Parsed {len(df)} rows.")
            st.dataframe(df.head(50), use_container_width=True)
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download CSV",
                data=csv_bytes,
                file_name=f"{os.path.splitext(uploaded.name)[0]}_standard.csv",
                mime="text/csv",
            )
    except Exception as e:
        st.error(f"Failed to parse PDF: {e}")
        with st.expander("Show error details"):
            st.exception(e)
else:
    st.caption("Drop a PDF above to begin.")

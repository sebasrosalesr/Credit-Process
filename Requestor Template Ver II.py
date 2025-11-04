import streamlit as st
import pandas as pd
import io, re, tempfile, os

# =========================
# CONFIG / CONSTANTS
# =========================
ACCOUNT_CODE_AS_CUSTOMER_NUMBER = True  # Use FLD02 (account code) as Customer Number

standard_columns = [
    'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
    'Extended Correct Price',
    'Item Non-Taxable Credit', 'Item Taxable Credit',
    'Credit Request Total',
    'Requested By', 'Reason for Credit', 'Status', 'Ticket Number'
]

# --- Macro File Mapping ---
macro_mapping = {
    'Date': 'Req Date',
    'Credit Type': 'CRType',
    'Issue Type': 'Type',
    'Customer Number': 'Cust ID',
    'Invoice Number': 'Doc No',
    'Item Number': 'Item No.',
    'Item Non-Taxable Credit': 'Item Non-Taxable Credit',
    'Item Taxable Credit': 'Item Taxable Credit',
    'Requested By': 'Requested By',
    'Reason for Credit': 'Reason',
    'Status': 'Status'
}

# --- DOC Analysis Mapping (with alternate names) ---
doc_analysis_mapping = {
    'Date': ['DOCDATE', 'Doc Date'],
    'Credit Type': None,
    'Issue Type': None,
    'Customer Number': ['CUSTNMBR','Cust Number'],
    'Invoice Number': ['SOPNUMBE', 'SOP Number'],
    'Item Number': ['ITEMNMBR', 'Item Number'],
    'QTY': ['QUANTITY', 'Qty on Invoice'],
    'Unit Price': ['UNITPRCE', 'UOM Price'],
    'Extended Price': ['XTNDPRCE', 'Extended Price'],
    'Corrected Unit Price': None,
    'Extended Correct Price': None,
    'Item Non-Taxable Credit': None,
    'Item Taxable Credit': None,
    'Credit Request Total': None,
    'Requested By': None,
    'Reason for Credit': None,
    'Status': None,
    'Ticket Number': None
}

# --- JF Request Mapping ---
jf_mapping = {
    'Date': 'Doc Date',
    'Credit Type': None,
    'Issue Type': None,
    'Customer Number': 'Cust Number',
    'Invoice Number': 'SOP Number',
    'Item Number': 'Item Number',
    'QTY': 'Qty on Invoice',
    'Unit Price': 'UOM Price',
    'Extended Price': 'Extended Price',
    'Corrected Unit Price': 'New UOM Price',
    'Extended Correct Price': 'New Extended Price',
    'Item Non-Taxable Credit': None,
    'Item Taxable Credit': None,
    'Credit Request Total': 'Difference to Be Credited',
    'Requested By': None,
    'Reason for Credit': None,
    'Status': None,
    'Ticket Number': None
}

# =========================
# COMMON HELPERS
# =========================
def _money_to_float(s):
    if pd.isna(s): return None
    s = str(s).strip()
    if s == "": return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.replace("$","").replace(",","").replace("−","-")
    if neg: s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return None

def convert_money_columns(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].apply(_money_to_float)
    return df

def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# =========================
# EXCEL FLOWS
# =========================
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    for i in range(min(10, len(raw_df))):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if any(col in row.values for col in ['SOPNUMBE', 'SOP NUMBER']) and \
           any(col in row.values for col in ['ITEMNMBR', 'ITEM NUMBER']):
            header_row = i
            break
    if header_row is None:
        raise ValueError("❌ Could not detect header row. Need SOPNUMBE/SOP Number and ITEMNMBR/Item Number.")
    df = pd.read_excel(file, header=header_row)
    df.columns = df.columns.str.strip()
    return df

def filter_doc_analysis(df):
    for col in ['UNITPRCE', 'Unit Price', 'UOM Price']:
        if col in df.columns:
            return df[df[col] != 0]
    return df

def convert_file(df, mapping):
    df_out = pd.DataFrame(columns=standard_columns)
    cols_upper = {col.strip().upper(): col for col in df.columns}

    for std_col in standard_columns:
        source = mapping.get(std_col)
        if isinstance(source, list):
            found = None
            for alt in source:
                match = cols_upper.get(alt.strip().upper())
                if match:
                    found = match
                    break
            df_out[std_col] = df[found] if found else None
        elif isinstance(source, str):
            match = cols_upper.get(source.strip().upper())
            df_out[std_col] = df[match] if match else None
        else:
            df_out[std_col] = None
    return df_out

# =========================
# PDF PARSING (TwinMed)
# =========================
def norm_money_pdf(s: str):
    if not s: return None
    s = s.strip().replace('$', '')
    s = re.sub(r',(?!\d{3}\b)', '', s)
    neg = s.startswith('(') and s.endswith(')')
    s = s.replace('(', '').replace(')', '')
    m = re.search(r'-?\d+(?:\.\d{2})?', s)
    if not m: return None
    v = float(m.group(0))
    return -v if neg else v

def first_match(pattern: str, text: str, flags=re.I|re.M):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

def get_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def parse_header_from_text(text: str):
    invoice_no = first_match(r'Invoice\s*No\s*:\s*([A-Z0-9\-]+)', text)
    date_pat = r'([A-Za-z]{3,}\s+\d{1,2},?\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
    invoice_date_raw = first_match(rf'Invoice\s*Date\s*:\s*{date_pat}', text)
    invoice_date = None
    if invoice_date_raw:
        parsed = pd.to_datetime(invoice_date_raw, errors='coerce')
        invoice_date = parsed.date().isoformat() if not pd.isna(parsed) else invoice_date_raw

    m = re.search(r'Customer\s+Account\s+([A-Z0-9\-]+)\s+No\.\s*:\s*([A-Z0-9\-]+)', text, re.I)
    if m:
        account_code, account_no = m.group(1).strip(), m.group(2).strip()
        customer_no = account_code if ACCOUNT_CODE_AS_CUSTOMER_NUMBER else account_no
    else:
        account_code = first_match(r'Customer\s+Account\s+([A-Z0-9\-]+)\b', text)
        account_no   = first_match(r'Customer\s+(?:No\.|Number)\s*:\s*([A-Z0-9\-]+)', text)
        customer_no  = account_code if ACCOUNT_CODE_AS_CUSTOMER_NUMBER and account_code else account_no

    return {"invoice_no": invoice_no, "invoice_date": invoice_date, "customer_no": customer_no}

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

def is_item_row(cells):
    if not cells: return False
    first = str(cells[0]).strip()
    if not re.fullmatch(r'[A-Z0-9\-\/]{4,}', first): return False
    return re.search(r'\$?\d+(?:,\d{3})*(?:\.\d{2})?', " ".join(map(str, cells))) is not None

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

def parse_items_from_table(df):
    if df is None or df.empty: return []
    # try to find header row in first 3 rows
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
            # item
            item_no = None
            if colmap["item"] is not None and colmap["item"] < len(cells):
                cand = cells[colmap["item"]].strip()
                if re.fullmatch(r'[A-Z0-9\-\/]{4,}', cand):
                    item_no = cand
            if not item_no: continue
            # qty (only if numeric)
            qty = None
            if colmap["qty"] is not None and colmap["qty"] < len(cells):
                qraw = cells[colmap["qty"]].strip()
                if re.fullmatch(r'\d{1,4}', qraw): 
                    qty = int(qraw)
            # prices
            unit_price = None
            if colmap["price"] is not None and colmap["price"] < len(cells):
                unit_price = norm_money_pdf(cells[colmap["price"]])
            ext_price = None
            if colmap["total"] is not None and colmap["total"] < len(cells):
                ext_price = norm_money_pdf(cells[colmap["total"]])
            # gentle fallback if needed
            if unit_price is None or ext_price is None:
                monies = [norm_money_pdf(c) for c in cells if norm_money_pdf(c) is not None]
                if unit_price is None and len(monies) >= 2: unit_price = monies[-2]
                if ext_price  is None and len(monies) >= 1: ext_price  = monies[-1]
            rows.append({"Item Number": item_no, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
        return rows

    # legacy heuristic if no headers found
    for i in range(len(df)):
        cells = df.iloc[i].astype(str).tolist()
        if not is_item_row(cells): continue
        first = cells[0].strip()
        qty = None
        for c in cells:
            tok = c.strip()
            if re.fullmatch(r'\d{1,4}', tok):
                qty = int(tok); break
        monies = [norm_money_pdf(c) for c in cells if norm_money_pdf(c) is not None]
        unit_price = ext_price = None
        if len(monies) >= 2:
            unit_price, ext_price = monies[-2], monies[-1]
        elif len(monies) == 1:
            ext_price = monies[-1]
        rows.append({"Item Number": first, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
    return rows

def regex_items_fallback(text: str):
    """
    Parse lines like:
    1008275 ... 14.70 BX 3 44.10
                ^price ^unit ^qty ^total
    """
    out = []
    UNIT_TOKENS = r'(EA|BX|CS|PK|BG|BT|DZ|PR|RL|ST|CT)'
    item_line = re.compile(r'^([A-Z0-9][A-Z0-9\-\/]{3,})\b(.*)$')

    for ln in text.splitlines():
        ln = ln.strip()
        m0 = item_line.match(ln)
        if not m0: continue
        item_no, tail = m0.group(1), m0.group(2)

        m = re.search(
            rf'(\$?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s+{UNIT_TOKENS}\s+(\d{{1,4}})\s+(\$?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*$',
            tail, flags=re.I
        )
        if m:
            unit_price = norm_money_pdf(m.group(1))
            qty_raw    = m.group(2)
            qty        = int(qty_raw) if qty_raw.isdigit() else None
            ext_price  = norm_money_pdf(m.group(3))
        else:
            monies = re.findall(r'\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?', tail)
            if not monies: continue
            ext_price  = norm_money_pdf(monies[-1])
            unit_price = norm_money_pdf(monies[-2]) if len(monies) >= 2 else None
            ints = re.findall(r'\b\d{1,4}\b', tail)
            qty  = int(ints[-1]) if ints and ints[-1].isdigit() else None

        out.append({"Item Number": item_no, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
    return out

def pdf_to_standard_rows(pdf_bytes: bytes):
    text = get_text_from_pdf_bytes(pdf_bytes)
    header = parse_header_from_text(text)

    dfs = camelot_extract_tempfile(pdf_bytes)
    items = []
    if dfs:
        table = pick_items_table(dfs)
        items = parse_items_from_table(table)
    if not items:
        items = regex_items_fallback(text)

    rows = []
    for it in items:
        rows.append({
            'Date': header.get('invoice_date') or '',
            'Credit Type': '',
            'Issue Type': '',
            'Customer Number': header.get('customer_no') or '',
            'Invoice Number': header.get('invoice_no') or '',
            'Item Number': it.get('Item Number'),
            'QTY': it.get('QTY'),
            'Unit Price': it.get('Unit Price'),
            'Extended Price': it.get('Extended Price'),
            'Corrected Unit Price': '',
            'Extended Correct Price': '',
            'Item Non-Taxable Credit': '',
            'Item Taxable Credit': '',
            'Credit Request Total': '',
            'Requested By': '',
            'Reason for Credit': '',
            'Status': '',
            'Ticket Number': '',
        })
    df = pd.DataFrame(rows, columns=standard_columns)
    if not df.empty:
        df['Source File'] = 'PDF Invoice'
        df['Format'] = 'TwinMed Invoice'
    return df

# =========================
# STREAMLIT UI
# =========================
st.set_page_config(page_title="Credit Request Template Converter", layout="wide")
st.title("📄 Credit Request Template Converter")

uploaded_files = st.file_uploader(
    "Upload Excel or PDF files",
    type=['xlsx', 'xls', 'xlsm', 'pdf'],
    accept_multiple_files=True
)
converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        name = uploaded_file.name
        suffix = os.path.splitext(name)[1].lower()

        # ---------- PDF ----------
        if suffix == ".pdf":
            try:
                st.info(f"🧾 Parsing PDF Invoice — {name}")
                pdf_bytes = uploaded_file.read()
                df_pdf = pdf_to_standard_rows(pdf_bytes)
                if df_pdf is None or df_pdf.empty:
                    st.warning(f"⚠️ No line items detected in `{name}`.")
                else:
                    converted_frames.append(df_pdf)
                    st.success(f"✅ Parsed {len(df_pdf)} rows from `{name}`")
                    st.dataframe(df_pdf.head(15), use_container_width=True)
            except Exception as e:
                st.warning(f"⚠️ Skipped PDF `{name}`: {e}")
            continue

        # ---------- EXCEL ----------
        try:
            df_sample = pd.read_excel(uploaded_file, nrows=5)
            sample_cols = set(df_sample.columns.str.strip())

            # 1) Macro
            if {'Req Date', 'Cust ID', 'Total Credit Amt'}.issubset(sample_cols):
                st.info(f"📘 Format Detected: Macro File — {name}")
                df_full = pd.read_excel(uploaded_file)
                converted = convert_file(df_full, macro_mapping)
                converted['Credit Request Total'] = df_full.get('Total Credit Amt')
                converted['Source File'] = name
                converted['Format'] = 'Macro File'
                converted_frames.append(converted)
                continue

            # 2) JF Request
            jf_hits = {'Doc Date', 'SOP Number', 'Cust Number'}
            if jf_hits.issubset(sample_cols) or 'Difference to Be Credited' in sample_cols:
                st.info(f"🟣 Format Detected: JF Request — {name}")
                df_full = pd.read_excel(uploaded_file)
                df_full = convert_money_columns(
                    df_full,
                    ['UOM Price','Extended Price','New UOM Price','New Extended Price','Difference to Be Credited']
                )
                converted = convert_file(df_full, jf_mapping)
                converted['Source File'] = name
                converted['Format'] = 'JF Request'
                converted_frames.append(converted)
                continue

            # 3) DOC Analysis
            st.info(f"🔍 Trying to detect DOC Analysis format — {name}")
            df_doc = load_doc_analysis_file(uploaded_file)
            df_doc = filter_doc_analysis(df_doc)
            converted = convert_file(df_doc, doc_analysis_mapping)
            converted['Source File'] = name
            converted['Format'] = 'DOC Analysis'
            converted_frames.append(converted)

        except Exception as e:
            st.warning(f"⚠️ Skipped file `{name}`: {e}")

    if converted_frames:
        final_df = pd.concat(converted_frames, ignore_index=True)
        # numeric consistency
        numeric_like = [
            'QTY','Unit Price','Extended Price','Corrected Unit Price',
            'Extended Correct Price','Item Non-Taxable Credit','Item Taxable Credit',
            'Credit Request Total'
        ]
        for c in numeric_like:
            if c in final_df.columns:
                final_df[c] = pd.to_numeric(final_df[c], errors='coerce')

        st.success(f"✅ Combined Rows: {final_df.shape[0]}")
        st.dataframe(final_df, use_container_width=True)

        excel_bytes = convert_df_to_excel(final_df)
        st.download_button(
            label="📥 Download Combined Excel",
            data=excel_bytes,
            file_name="Converted_Credit_Requests.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.error("❌ No valid files were processed.")

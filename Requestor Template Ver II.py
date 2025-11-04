# ============================
# TwinMed Invoice → Standard Schema (with preview; robust unit/qty parsing)
# ============================
# Requirements:
#   pip install pdfplumber camelot-py[cv] pandas
#   (Linux/Colab) apt-get install -y ghostscript poppler-utils
#
# If your PDF is scanned (no text layer), OCR it first with ocrmypdf:
#   apt-get install -y ocrmypdf tesseract-ocr
#   ocrmypdf --force-ocr --rotate-pages --deskew input.pdf output_searchable.pdf

from __future__ import annotations
import re, json
from typing import List, Dict, Optional, Tuple

import pandas as pd
import pdfplumber

# ---------- CONFIG ----------
INPUT_PDF = "/content/drive/MyDrive/Sales/TwinMed Darren/FLD02 INV14181150.pdf"  # ← set your path
OUTPUT_CSV = "/content/INV14181150_to_standard_schema.csv"

# Use the ACCOUNT CODE (e.g., FLD02) as the Customer Number
ACCOUNT_CODE_AS_CUSTOMER_NUMBER = True

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

# ---------- Regex helpers (tightened) ----------
ITEM_RE = re.compile(r'(?:\d{5,}|[A-Z0-9]{2,}[A-Z0-9\-]{3,})$')  # Item #; no slashes, 5+ chars overall
DATE_TOKEN_RE = re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b')        # e.g., 11/4/25

# ---------- MONEY / TEXT HELPERS ----------
def norm_money(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.strip().replace('$', '')
    s = re.sub(r',(?!\d{3}\b)', '', s)  # drop stray commas
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

def get_text(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

# ---------- HEADER PARSE ----------
def parse_header(text: str) -> Dict[str, Optional[str]]:
    # Invoice No
    invoice_no = first_match(r'^\s*Invoice\s*No\s*:\s*([A-Z0-9\-]+)\s*$', text) \
              or first_match(r'Invoice\s*No\s*:\s*([A-Z0-9\-]+)', text)

    # Invoice Date (ONLY from "Invoice Date:", never from page timestamp)
    date_pat = r'([A-Za-z]{3,}\s+\d{1,2},?\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
    invoice_date_raw = first_match(rf'^\s*Invoice\s*Date\s*:\s*{date_pat}\s*$', text) \
                    or first_match(rf'Invoice\s*Date\s*:\s*{date_pat}', text)
    invoice_date = None
    if invoice_date_raw:
        parsed = pd.to_datetime(invoice_date_raw, errors='coerce')
        invoice_date = parsed.date().isoformat() if not pd.isna(parsed) else invoice_date_raw

    # Customer Account FLD02 No.: 808  → prefer FLD02 if flag is True
    account_code, account_no = None, None
    m = re.search(r'^\s*Customer\s+Account\s+([A-Z0-9\-]+)\s+No\.\s*:\s*([A-Z0-9\-]+)\s*$',
                  text, flags=re.I|re.M)
    if m:
        account_code, account_no = m.group(1).strip(), m.group(2).strip()
        customer_no = account_code if ACCOUNT_CODE_AS_CUSTOMER_NUMBER else account_no
    else:
        account_code = first_match(r'Customer\s+Account\s+([A-Z0-9\-]+)\b', text)
        account_no   = first_match(r'Customer\s+(?:No\.|Number)\s*:\s*([A-Z0-9\-]+)', text)
        customer_no  = account_code if ACCOUNT_CODE_AS_CUSTOMER_NUMBER and account_code else account_no

    # Totals (optional sanity check)
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

# ---------- TABLE EXTRACTION (Camelot optional) ----------
def camelot_extract(pdf_path: str) -> List[pd.DataFrame]:
    try:
        import camelot
    except Exception:
        return []
    # lattice first
    try:
        t = camelot.read_pdf(pdf_path, flavor="lattice", pages="all")
        if len(t): return [x.df for x in t]
    except Exception:
        pass
    # stream fallback
    try:
        t = camelot.read_pdf(pdf_path, flavor="stream", pages="all", row_tol=10, column_tol=15)
        if len(t): return [x.df for x in t]
    except Exception:
        pass
    return []

# ---------- ROW IDENTIFICATION / HEADER MAP ----------
def is_item_row(row: List[str]) -> bool:
    if not row or not isinstance(row[0], str):
        return False
    tok = row[0].strip()
    if '/' in tok or DATE_TOKEN_RE.search(tok):
        return False
    return bool(ITEM_RE.fullmatch(tok)) and (
        re.search(r'\$?\d+(?:,\d{3})*(?:\.\d{2})?', " ".join(map(str, row))) is not None
    )

def _normalize_headers(cells):
    return [re.sub(r'\s+', ' ', str(x).strip().lower()) for x in cells]

def _build_col_map(header_cells):
    """
    Map fuzzy header names to indices.
    Looks for: item, price, unit, qty, total, description.
    """
    h = _normalize_headers(header_cells)
    idx = { "item": None, "price": None, "unit": None, "qty": None, "total": None, "desc": None }
    for i, val in enumerate(h):
        if idx["item"]  is None and ("twinmed item" in val or val.startswith("item")): idx["item"]  = i
        if idx["price"] is None and ("price" in val and "unit" not in val and "total" not in val): idx["price"] = i
        if idx["unit"]  is None and (val == "unit" or "uom" in val): idx["unit"]  = i
        if idx["qty"]   is None and ("qty" in val or "quantity" in val): idx["qty"]   = i
        if idx["total"] is None and ("total" in val): idx["total"] = i
        if idx["desc"]  is None and ("desc" in val or "description" in val): idx["desc"]  = i
    if idx["item"] is None and len(h) > 0: idx["item"] = 0  # fallback
    return idx

# ---------- TABLE → ITEMS (Column-aware) ----------
def parse_items_from_table(df: pd.DataFrame) -> List[Dict[str, Optional[str]]]:
    """
    Column-aware parsing:
    - Detect header row by expected header words.
    - Map Price -> Unit Price, Qty -> QTY, Total -> Extended Price.
    - If headers not found, use a legacy heuristic.
    """
    if df is None or df.empty:
        return []

    # Find header row (within first 3 rows)
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

            # Item Number
            item_no = None
            if colmap["item"] is not None and colmap["item"] < len(cells):
                candidate = cells[colmap["item"]].strip()
                if '/' not in candidate and ITEM_RE.fullmatch(candidate) and not DATE_TOKEN_RE.search(candidate):
                    item_no = candidate
            if not item_no:
                continue  # skip non-item rows

            # QTY (strictly integer)
            qty = None
            if colmap["qty"] is not None and colmap["qty"] < len(cells):
                qraw = cells[colmap["qty"]].strip()
                if re.fullmatch(r'\d{1,4}', qraw):
                    qty = int(qraw)

            # Unit Price (from 'Price' column)
            unit_price = None
            if colmap["price"] is not None and colmap["price"] < len(cells):
                unit_price = norm_money(cells[colmap["price"]])

            # Extended Price (from 'Total' column)
            ext_price = None
            if colmap["total"] is not None and colmap["total"] < len(cells):
                ext_price = norm_money(cells[colmap["total"]])

            # Gentle fallback inside the same row
            if unit_price is None or ext_price is None:
                monies = [norm_money(c) for c in cells if norm_money(c) is not None]
                if unit_price is None and len(monies) >= 2: unit_price = monies[-2]
                if ext_price  is None and len(monies) >= 1: ext_price  = monies[-1]

            rows.append({"Item Number": item_no, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
        return rows

    # Legacy/backup heuristic if no headers found
    return _old_style_row_heuristic(df)

def _old_style_row_heuristic(df: pd.DataFrame) -> List[Dict[str, Optional[str]]]:
    rows = []
    for i in range(len(df)):
        cells = df.iloc[i].astype(str).tolist()
        if not cells:
            continue
        first = cells[0].strip()
        if '/' in first or DATE_TOKEN_RE.search(first) or not ITEM_RE.fullmatch(first):
            continue

        qty = None
        for c in cells:
            tok = c.strip()
            if re.fullmatch(r'\d{1,4}', tok):
                qty = int(tok); break

        monies = [norm_money(c) for c in cells if norm_money(c) is not None]
        unit_price = ext_price = None
        if len(monies) >= 2:
            unit_price, ext_price = monies[-2], monies[-1]
        elif len(monies) == 1:
            ext_price = monies[-1]

        rows.append({"Item Number": first, "QTY": qty, "Unit Price": unit_price, "Extended Price": ext_price})
    return rows

# ---------- TEXT REGEX FALLBACK ----------
def regex_items_fallback(text: str) -> List[Dict[str, Optional[str]]]:
    """
    Parse lines that look like:
      1008275 ... 14.70 BX 3 44.10
                    ^price ^unit ^qty ^total
    """
    out = []
    UNIT_TOKENS = r'(EA|BX|CS|PK|BG|BT|DZ|PR|RL|ST|CT)'
    # Item numbers cannot contain slashes and must be 5+ chars
    item_line = re.compile(r'^([A-Z0-9][A-Z0-9\-]{4,})\b(.*)$')

    for ln in text.splitlines():
        ln = ln.strip()
        if DATE_TOKEN_RE.search(ln):  # skip timestamp-like lines
            continue

        m0 = item_line.match(ln)
        if not m0:
            continue

        item_no, tail = m0.group(1), m0.group(2)

        # Prefer explicit "... <price> <unit> <qty> <total>" at the end of the line
        m = re.search(
            rf'(\$?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s+{UNIT_TOKENS}\s+(\d{{1,4}})\s+(\$?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)\s*$',
            tail, flags=re.I
        )
        if m:
            unit_price = norm_money(m.group(1))
            qty_txt    = m.group(2)
            qty        = int(qty_txt) if qty_txt.isdigit() else None
            ext_price  = norm_money(m.group(3))
        else:
            # Fallback: last two monies + last small int
            monies = re.findall(r'\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?', tail)
            if not monies:
                continue
            ext_price  = norm_money(monies[-1])
            unit_price = norm_money(monies[-2]) if len(monies) >= 2 else None
            ints = re.findall(r'\b\d{1,4}\b', tail)
            qty  = int(ints[-1]) if ints and ints[-1].isdigit() else None

        out.append({
            "Item Number": item_no,
            "QTY": qty,
            "Unit Price": unit_price,
            "Extended Price": ext_price
        })
    return out

# ---------- MAP TO STANDARD ROWS ----------
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

# ---------- MAIN ----------
def parse_invoice_to_schema(pdf_path: str, out_csv: str) -> pd.DataFrame:
    text = get_text(pdf_path)
    header = parse_header(text)

    # Try Camelot tables first
    dfs = camelot_extract(pdf_path)
    items = []
    if dfs:
        # Pick the most "item-table-looking" DF
        def score(df: pd.DataFrame) -> Tuple[int,int]:
            headers = " ".join(df.iloc[0].astype(str).tolist()).lower() if len(df) else ""
            hits = sum(k in headers for k in ["item", "twinmed", "qty", "unit", "price", "total", "description"])
            rowscore = 0
            for i in range(min(len(df), 60)):
                row = df.iloc[i].astype(str).tolist()
                if is_item_row(row): rowscore += 1
            return (hits, rowscore)
        best = max(dfs, key=score)
        items = parse_items_from_table(best)

    # Fallback to regex-from-text
    if not items:
        items = regex_items_fallback(text)

    # Build DF
    rows = to_standard_rows(header, items)
    df = pd.DataFrame(rows, columns=STANDARD_COLUMNS)

    # ---- Cleanup: remove any accidental date-as-item rows ----
    if not df.empty:
        mask_ok = ~df['Item Number'].astype(str).str.contains(r'/', regex=True)
        mask_ok &= ~df['Item Number'].astype(str).str.match(r'\d{1,2}/\d{1,2}/\d{2,4}$')
        df = df[mask_ok].reset_index(drop=True)

    # Save
    df.to_csv(out_csv, index=False)

    # ---- Preview / sanity prints ----
    print("Saved:", out_csv)
    print("\n--- HEADER ---")
    print(json.dumps(header, indent=2))

    print("\n--- PREVIEW (first 10 rows) ---")
    try:
        from IPython.display import display
        display(df.head(10))
    except Exception:
        print(df.head(10))

    # Totals sanity (if invoice total detected)
    if header.get("total") is not None and 'Extended Price' in df.columns:
        sum_ext = pd.to_numeric(df['Extended Price'], errors='coerce').fillna(0).sum()
        diff = abs(sum_ext - float(header["total"]))
        print(f"\nSanity: sum(Extended Price) = {sum_ext:.2f} "
              f"vs Invoice Total = {header['total']:.2f}  (Δ = {diff:.2f})")
    else:
        print("\nSanity: invoice total not detected; skipping totals check.")

    return df

# ---- Run as script ----
if __name__ == "__main__":
    _ = parse_invoice_to_schema(INPUT_PDF, OUTPUT_CSV)

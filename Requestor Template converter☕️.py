import streamlit as st
import pandas as pd
import io
import re

# --- Standard Output Schema ---
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

# --- NEW: JF Request Mapping ---
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

# -------- Helpers --------
def _money_to_float(s):
    """coerce money-like strings to float (handles $, commas, parentheses)"""
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

# --- Detect header row in DOC Analysis ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    for i in range(10):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if any(col in row.values for col in ['SOPNUMBE', 'SOP NUMBER']) and \
           any(col in row.values for col in ['ITEMNMBR', 'ITEM NUMBER']):
            header_row = i
            break
    if header_row is None:
        raise ValueError("❌ Could not detect header row. Ensure SOPNUMBE/SOP Number and ITEMNMBR/Item Number exist.")
    df = pd.read_excel(file, header=header_row)
    df.columns = df.columns.str.strip()
    return df

# --- Filter DOC rows where price is zero ---
def filter_doc_analysis(df):
    for col in ['UNITPRCE', 'Unit Price', 'UOM Price']:
        if col in df.columns:
            return df[df[col] != 0]
    return df

# --- Convert any file to standard format ---
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

# --- Excel Export ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- Streamlit App ---
st.set_page_config(page_title="Credit Request Template Converter", layout="wide")
st.title("📄 Credit Request Template Converter")

uploaded_files = st.file_uploader("Upload Excel files", type=['xlsx', 'xls', 'xlsm'], accept_multiple_files=True)
converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        try:
            df_sample = pd.read_excel(uploaded_file, nrows=5)
            sample_cols = set(df_sample.columns.str.strip())

            # 1) Macro format detection
            if {'Req Date', 'Cust ID', 'Total Credit Amt'}.issubset(sample_cols):
                st.info(f"📘 Format Detected: Macro File — {uploaded_file.name}")
                df_full = pd.read_excel(uploaded_file)
                converted = convert_file(df_full, macro_mapping)

                # Pull total directly
                converted['Credit Request Total'] = df_full.get('Total Credit Amt')
                converted['Source File'] = uploaded_file.name
                converted['Format'] = 'Macro File'
                converted_frames.append(converted)
                continue

            # 2) JF Request detection (Doc Date + Difference to Be Credited present)
            jf_hits = {'Doc Date', 'SOP Number', 'Cust Number'}
            if jf_hits.issubset(sample_cols) or 'Difference to Be Credited' in sample_cols:
                st.info(f"🟣 Format Detected: JF Request — {uploaded_file.name}")
                df_full = pd.read_excel(uploaded_file)
                # make sure money-like columns are numeric
                df_full = convert_money_columns(
                    df_full,
                    ['UOM Price','Extended Price','New UOM Price','New Extended Price','Difference to Be Credited']
                )
                converted = convert_file(df_full, jf_mapping)
                converted['Source File'] = uploaded_file.name
                converted['Format'] = 'JF Request'
                converted_frames.append(converted)
                continue

            # 3) Fallback to DOC Analysis (with header sniff)
            st.info(f"🔍 Trying to detect DOC Analysis format — {uploaded_file.name}")
            df_doc = load_doc_analysis_file(uploaded_file)
            df_doc = filter_doc_analysis(df_doc)
            converted = convert_file(df_doc, doc_analysis_mapping)
            converted['Source File'] = uploaded_file.name
            converted['Format'] = 'DOC Analysis'
            converted_frames.append(converted)

        except Exception as e:
            st.warning(f"⚠️ Skipped file `{uploaded_file.name}`: {e}")

    if converted_frames:
        final_df = pd.concat(converted_frames, ignore_index=True)

        # optional: ensure numeric in standard numeric columns for consistency
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


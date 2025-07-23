import streamlit as st
import pandas as pd
import io

# --- Standard Output Schema ---
standard_columns = [
    'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
    'Extended Correct Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit', 'Status', 'Ticket Number'
]

# --- Macro File Mapping ---
macro_mapping = {
    'Date': 'Req Date',
    'Credit Type': 'CRType',
    'Issue Type': 'Type',
    'Customer Number': 'Cust ID',
    'Invoice Number': 'Doc No',
    'Item Number': 'Item No.',
    'Credit Request Total': 'Total Credit Amt',
    'Requested By': 'Requested By',
    'Reason for Credit': 'Reason',
    'Status': 'Status'
    # Other fields will default to None
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
    'Unit Price': ['UNITPRCE'],
    'Extended Price': ['XTNDPRCE', 'Extended Price'],
    'Corrected Unit Price': None,
    'Extended Correct Price': None,
    'Credit Request Total': None,
    'Requested By': None,
    'Reason for Credit': None,
    'Status': None,
    'Ticket Number': None
}

# --- Detect header row in DOC Analysis ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    for i in range(10):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if any(col in row.values for col in ['SOPNUMBE', 'SOP NUMBER']) and any(col in row.values for col in ['ITEMNMBR', 'ITEM NUMBER']):
            header_row = i
            break
    if header_row is None:
        raise ValueError("❌ Could not detect header row. Please ensure SOPNUMBE or SOP Number and ITEMNMBR or Item Number exist.")
    df = pd.read_excel(file, header=header_row)
    df.columns = df.columns.str.strip()
    return df

# --- Filter DOC rows where price is zero ---
def filter_doc_analysis(df):
    for col in ['UNITPRCE', 'Unit Price']:
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
            for alt in source:
                match = cols_upper.get(alt.strip().upper())
                if match:
                    df_out[std_col] = df[match]
                    break
            else:
                df_out[std_col] = None
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

            # Macro format detection
            if 'Req Date' in sample_cols and 'Cust ID' in sample_cols and 'Total Credit Amt' in sample_cols:
                st.info(f"📘 Format Detected: Macro File - {uploaded_file.name}")
                df_full = pd.read_excel(uploaded_file)
                converted = convert_file(df_full, macro_mapping)
                converted['Source File'] = uploaded_file.name
                converted['Format'] = 'Macro File'
                converted_frames.append(converted)
            else:
                st.info(f"🔍 Trying to detect DOC Analysis format - {uploaded_file.name}")
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
        st.success(f"✅ Combined Rows: {final_df.shape[0]}")
        st.dataframe(final_df)

        excel_bytes = convert_df_to_excel(final_df)
        st.download_button(
            label="📥 Download Combined Excel",
            data=excel_bytes,
            file_name="Converted_Credit_Requests.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.error("❌ No valid files were processed.")


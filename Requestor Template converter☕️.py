import streamlit as st
import pandas as pd
import io

# --- Standard output schema ---
standard_columns = [
    'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
    'Extended Correct Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit', 'Status', 'Ticket Number'
]

# --- Format A: Macro File Mapping ---
macro_mapping = {
    'Date': 'Req Date',
    'Credit Type': 'CRType',
    'Issue Type': 'Type',
    'Customer Number': 'Cust ID',
    'Invoice Number': 'Doc No',
    'Item Number': 'Item No.',
    'QTY': None,
    'Unit Price': None,
    'Extended Price': None,
    'Corrected Unit Price': None,
    'Extended Correct Price': None,
    'Credit Request Total': 'Total Credit Amt',
    'Requested By': 'Requested By',
    'Reason for Credit': 'Reason',
    'Status': 'Status',
    'Ticket Number': None
}

# --- DOC Analysis Mapping ---
doc_analysis_mapping = {
    'Date': 'DOCDATE',
    'Credit Type': None,
    'Issue Type': None,
    'Customer Number': 'CUSTNMBR',
    'Invoice Number': 'SOPNUMBE',
    'Item Number': 'ITEMNMBR',
    'QTY': 'QUANTITY',
    'Unit Price': 'UNITPRCE',
    'Extended Price': 'XTNDPRCE',
    'Corrected Unit Price': None,
    'Extended Correct Price': None,
    'Credit Request Total': None,
    'Requested By': None,
    'Reason for Credit': None,
    'Status': None,
    'Ticket Number': None
}

# --- Load DOC Analysis with fallback ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    for i in range(min(10, len(raw_df))):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if "SOPNUMBE" in row.values and "ITEMNMBR" in row.values:
            header_row = i
            break

    df = pd.read_excel(file, header=header_row if header_row is not None else 0)
    df.columns = df.columns.str.upper().str.strip()

    if not {'SOPNUMBE', 'ITEMNMBR'}.issubset(df.columns):
        return None

    return df

# --- Filter rows with zero price ---
def filter_doc_analysis(df):
    return df[df['UNITPRCE'] != 0]

# --- Convert output to Excel ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- Mapping-based conversion ---
def convert_file(df, mapping):
    df_out = pd.DataFrame(columns=standard_columns)
    for out_col in standard_columns:
        source_col = mapping.get(out_col)
        if source_col and source_col in df.columns:
            df_out[out_col] = df[source_col]
        else:
            df_out[out_col] = None
    return df_out

# --- Streamlit App ---
st.set_page_config(page_title="Credit Request Template Converter", layout="centered")
st.title("📄 Credit Request Template Converter")

uploaded_files = st.file_uploader("Upload Excel files", type=['xlsx', 'xls', 'xlsm'], accept_multiple_files=True)
converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        try:
            df_preview = pd.read_excel(uploaded_file, nrows=5)
            cols = set(df_preview.columns)

            if 'Req Date' in cols and 'Cust ID' in cols and 'Total Credit Amt' in cols:
                st.info(f"📘 Format Detected: Macro File - {uploaded_file.name}")
                df = pd.read_excel(uploaded_file)
                converted = convert_file(df, macro_mapping)
                converted['Source File'] = uploaded_file.name
                converted['Format'] = 'Macro File'
                converted_frames.append(converted)

            else:
                st.info(f"🔍 Trying to detect DOC Analysis format - {uploaded_file.name}")
                df = load_doc_analysis_file(uploaded_file)
                if df is None:
                    raise ValueError("❌ Could not detect DOC Analysis columns 'SOPNUMBE' and 'ITEMNMBR'.")
                df = filter_doc_analysis(df)
                converted = convert_file(df, doc_analysis_mapping)
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


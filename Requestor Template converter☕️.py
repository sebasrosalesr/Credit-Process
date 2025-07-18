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

# --- DOC Analysis Mapping (formerly pump orders) ---
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

# --- Header Detection for DOC Analysis ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None

    for i in range(10):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if "SOPNUMBE" in row.values and "ITEMNMBR" in row.values:
            header_row = i
            break

    if header_row is None:
        raise ValueError("❌ Could not detect header row. Please ensure 'SOPNUMBE' and 'ITEMNMBR' are present.")

    df = pd.read_excel(file, header=header_row)
    df.columns = df.columns.str.strip()
    return df

# --- Filter DOC Analysis rows with zero price ---
def filter_doc_analysis(df):
    return df[df['UNITPRCE'] != 0]

# --- Excel Export Function ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- Convert based on mapping ---
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
st.title("📄 Credit Request Template Converter")

uploaded_files = st.file_uploader("Upload Excel files", type=['xlsx', 'xls', 'xlsm'], accept_multiple_files=True)

converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        try:
            df = pd.read_excel(uploaded_file, nrows=5)
            cols = set(df.columns)

            # Detect Macro File
            if 'Req Date' in cols and 'Cust ID' in cols and 'Total Credit Amt' in cols:
                st.info("📘 Format Detected: Macro File")
                df = pd.read_excel(uploaded_file)
                converted = convert_file(df, macro_mapping)
                converted['Source File'] = uploaded_file.name
                converted['Format'] = 'Macro File'
                converted_frames.append(converted)

            # Try DOC Analysis detection
            else:
                st.info("🔍 Trying to detect DOC Analysis format...")
                df = load_doc_analysis_file(uploaded_file)
                df = filter_doc_analysis(df)
                converted = convert_file(df, doc_analysis_mapping)
                converted['Source File'] = uploaded_file.name
                converted['Format'] = 'DOC Analysis'
                converted_frames.append(converted)

        except Exception as e:
            st.warning(f"⚠️ Skipped file `{uploaded_file.name}`: {e}")

    # Combine and display results
    if converted_frames:
        final_df = pd.concat(converted_frames, ignore_index=True)
        st.success(f"✅ Combined Rows: {final_df.shape[0]}")
        st.dataframe(final_df)

        # Download button
        excel_bytes = convert_df_to_excel(final_df)
        st.download_button(
            label="📥 Download Combined Excel",
            data=excel_bytes,
            file_name="Converted_Credit_Requests.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.error("❌ No valid files were processed.")

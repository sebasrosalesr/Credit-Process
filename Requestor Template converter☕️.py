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

# --- DOC Analysis Mapping ---
doc_analysis_mapping = {
    'Date': 'DOCDATE',
    'Customer Number': 'CUSTNMBR',
    'Invoice Number': ['SOPNUMBE', 'SOP Number'],
    'Item Number': ['ITEMNMBR', 'Item Number'],
    'QTY': 'QUANTITY',
    'Unit Price': 'UNITPRCE',
    'Extended Price': 'XTNDPRCE'
    # Other fields will default to None
}

# --- Header Detection for DOC Analysis ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    
    for i in range(10):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if any(col.upper() in row.values for col in ['SOPNUMBE', 'SOP NUMBER']) and \
           any(col.upper() in row.values for col in ['ITEMNMBR', 'ITEM NUMBER']):
            header_row = i
            break

    if header_row is None:
        raise ValueError("❌ Could not detect header row. Please ensure SOP number and Item columns exist.")

    df = pd.read_excel(file, header=header_row)
    df.columns = df.columns.str.strip()
    return df

# --- Filter out rows with zero price ---
def filter_doc_analysis(df):
    return df[df['UNITPRCE'] != 0] if 'UNITPRCE' in df.columns else df

# --- Excel Export Helper ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- Apply Mapping to Match Standard Output ---
def convert_file(df, mapping):
    df_out = pd.DataFrame(columns=standard_columns)
    for col in standard_columns:
        source = mapping.get(col)
        if source:
            if isinstance(source, list):
                for alt in source:
                    if alt in df.columns:
                        df_out[col] = df[alt]
                        break
            elif source in df.columns:
                df_out[col] = df[source]
    return df_out

# --- Streamlit App ---
st.set_page_config(page_title="Credit Request Template Converter", layout="wide")
st.title("📄 Credit Request Template Converter")

uploaded_files = st.file_uploader("Upload Excel files", type=['xlsx', 'xls', 'xlsm'], accept_multiple_files=True)
converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        try:
            df_sample = pd.read_excel(uploaded_file, nrows=5)
            cols = set(df_sample.columns.str.strip())

            # Detect Macro File
            if 'Req Date' in cols and 'Cust ID' in cols and 'Total Credit Amt' in cols:
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

    # Combine and show
    if converted_frames:
        final_df = pd.concat(converted_frames, ignore_index=True)
        st.success(f"✅ Combined Rows: {final_df.shape[0]}")
        st.dataframe(final_df)

        excel_data = convert_df_to_excel(final_df)
        st.download_button(
            label="📥 Download Combined Excel",
            data=excel_data,
            file_name="Converted_Credit_Requests.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.error("❌ No valid files were processed.")


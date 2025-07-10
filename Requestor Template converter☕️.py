import streamlit as st
import pandas as pd
import os
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

# --- Format B: Pump Orders Mapping ---
pump_mapping = {
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

# --- Convert with mapping ---
def convert_file(df, mapping):
    df_out = pd.DataFrame(columns=standard_columns)
    for out_col in standard_columns:
        source_col = mapping.get(out_col)
        if source_col and source_col in df.columns:
            df_out[out_col] = df[source_col]
        else:
            df_out[out_col] = None
    return df_out

# --- Filter Pump Orders with zero price ---
def filter_pump(df):
    return df[df['UNITPRCE'] != 0]

# --- Excel Export Function ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- Streamlit App ---
st.title("📄 Credit Request Template Converter")

uploaded_files = st.file_uploader("Upload Excel files", type=['xlsx', 'xls', 'xlsm'], accept_multiple_files=True)

converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        df = pd.read_excel(uploaded_file)
        st.markdown(f"✅ **Loaded:** `{uploaded_file.name}` | Rows: {df.shape[0]} | Columns: {df.shape[1]}")

        # Format detection
        cols = set(df.columns)

        if 'Req Date' in cols and 'Cust ID' in cols and 'Total Credit Amt' in cols:
            st.info("📎 Format Detected: Macro File")
            converted = convert_file(df, macro_mapping)
            converted['Source File'] = uploaded_file.name
            converted['Format'] = 'Macro File'
            converted_frames.append(converted)

        elif 'CUSTNMBR' in cols and 'ITEMNMBR' in cols and 'UNITPRCE' in cols:
            st.info("🔧 Format Detected: Format B")
            df = filter_pump(df)
            converted = convert_file(df, pump_mapping)
            converted['Source File'] = uploaded_file.name
            converted['Format'] = 'Pump Order'
            converted_frames.append(converted)

        else:
            st.warning("⚠️ Unrecognized format — skipped")

    # Combine all
    if converted_frames:
        final_df = pd.concat(converted_frames, ignore_index=True)
        st.success(f"✅ Combined Rows: {final_df.shape[0]}")
        st.dataframe(final_df)

        # Download
        excel_bytes = convert_df_to_excel(final_df)
        st.download_button(
            label="📥 Download Combined Excel",
            data=excel_bytes,
            file_name="Converted_Credit_Requests.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.error("❌ No valid files to convert.")

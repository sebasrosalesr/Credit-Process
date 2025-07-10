import streamlit as st
import pandas as pd

# --- Final standardized schema ---
standard_columns = [
    'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
    'Extended Correct Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit', 'Status', 'Ticket Number'
]

# --- Macro mapping ---
macro_mapping = {
    'Date': 'Req Date',
    'Credit Type': 'CRType',
    'Issue Type': None,
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

# --- Conversion function ---
def convert_macro_file(df_macro):
    df_out = pd.DataFrame(columns=standard_columns)
    for col_out, col_in in macro_mapping.items():
        df_out[col_out] = df_macro[col_in] if col_in in df_macro.columns else None
    return df_out

# --- Streamlit App ---
st.title("📄 Credit Request File Converter")
uploaded_files = st.file_uploader("Upload one or more Excel files", type=["xlsx", "xlsm", "xls"], accept_multiple_files=True)

if uploaded_files:
    converted_dataframes = []
    
    for file in uploaded_files:
        df = pd.read_excel(file)
        st.success(f"✅ Loaded: {file.name} | Rows: {df.shape[0]} | Columns: {df.shape[1]}")
        st.write("📋 Columns:", list(df.columns))

        # Detect Macro Format
        cols = set(df.columns)
        if {'Req Date', 'Cust ID', 'Total Credit Amt'}.issubset(cols):
            st.info("🧠 Detected Macro Format – Converting...")
            df_converted = convert_macro_file(df)
            converted_dataframes.append(df_converted)
        else:
            st.warning("⚠️ Format not recognized – skipping this file")

    if converted_dataframes:
        final_df = pd.concat(converted_dataframes, ignore_index=True)
        st.success(f"✅ Combined Converted Files: {final_df.shape}")
        st.dataframe(final_df)

        # --- Download as Excel ---
        output_file = "converted_credit_requests.xlsx"
        final_df.to_excel(output_file, index=False)
        with open(output_file, "rb") as f:
            st.download_button("📥 Download Converted File", f, file_name=output_file)

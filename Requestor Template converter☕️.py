import streamlit as st
import pandas as pd

# --- Final Standard Schema ---
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

# --- Format B Mapping ---
format_b_mapping = {
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
    'Credit Request Total': 'XTNDPRCE',
    'Requested By': None,
    'Reason for Credit': None,
    'Status': None,
    'Ticket Number': None
}

# --- Identify File Types ---
def is_macro_file(df):
    return {'Req Date', 'Cust ID', 'Total Credit Amt'}.issubset(df.columns)

def is_format_b_file(df):
    return {'DOCDATE', 'CUSTNMBR', 'SOPNUMBE', 'ITEMNMBR', 'UNITPRCE'}.issubset(df.columns)

# --- Convert with Mapping ---
def convert_with_mapping(df, mapping, skip_zero_price=False):
    if skip_zero_price and 'UNITPRCE' in df.columns:
        df = df[df['UNITPRCE'].fillna(0) > 0]

    output_df = pd.DataFrame(columns=standard_columns)
    for std_col, source_col in mapping.items():
        output_df[std_col] = df[source_col] if source_col in df.columns else None
    return output_df

# --- Streamlit App UI ---
st.title("🧾 Excel Credit Request Converter")

uploaded_files = st.file_uploader("📂 Upload Excel Files", type=["xls", "xlsx", "xlsm"], accept_multiple_files=True)

if uploaded_files:
    converted_dataframes = []

    for file in uploaded_files:
        df = pd.read_excel(file)
        st.success(f"✅ Loaded: {file.name} | Rows: {df.shape[0]}")
        st.caption("📋 Columns: " + ", ".join(df.columns.astype(str)))

        if is_macro_file(df):
            st.info("🧠 Detected: Macro File — Applying Mapping")
            converted_dataframes.append(convert_with_mapping(df, macro_mapping))

        elif is_format_b_file(df):
            st.info("🔧 Detected: Format B — Filtering Unit Price > 0")
            converted_dataframes.append(convert_with_mapping(df, format_b_mapping, skip_zero_price=True))

        else:
            st.warning("⚠️ Format not recognized — Skipping")

    if converted_dataframes:
        final_df = pd.concat(converted_dataframes, ignore_index=True)
        st.success(f"✅ Combined Rows: {final_df.shape[0]}")
        st.dataframe(final_df.head(50))

        # Download button
        @st.cache_data
        def convert_df_to_excel(df):
            return df.to_excel(index=False, engine='openpyxl')

        excel_bytes = convert_df_to_excel(final_df)
        st.download_button(
            label="📥 Download Combined Excel",
            data=excel_bytes,
            file_name="Converted_Credit_Requests.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

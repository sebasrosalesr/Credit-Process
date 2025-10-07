import re
import io
import pandas as pd
import streamlit as st
from typing import Dict, List, Tuple, Optional

# ------------------------------
# Page setup
# ------------------------------
st.set_page_config(page_title="📊 Item Comparison: Two Price Files vs SOP", layout="wide")
st.title("📊 Item Comparison: Two Price Files vs SOP")
st.caption("Upload two *Item Price Changes* Excel files and one *SOP Doc File Analysis* file. You can enter one or more Item Numbers to compare across files.")

# ------------------------------
# Helper functions
# ------------------------------
def detect_header_row(file_like, sample_rows: int = 10) -> int:
    file_like.seek(0)
    temp = pd.read_excel(file_like, header=None, nrows=sample_rows)
    best_idx, best_score = 0, -1
    for i, row in temp.iterrows():
        non_null_ratio = row.notna().mean()
        text_ratio = row.dropna().apply(lambda x: isinstance(x, str) and bool(re.search(r"[A-Za-z]", x))).mean()
        score = 0.6 * non_null_ratio + 0.4 * text_ratio
        if score > best_score:
            best_idx, best_score = i, score
    file_like.seek(0)
    return int(best_idx)

def read_excel_smart(uploaded_file: st.runtime.uploaded_file_manager.UploadedFile) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    raw = uploaded_file.read()
    bio = io.BytesIO(raw)
    header_row = detect_header_row(bio)
    df = pd.read_excel(bio, header=header_row)
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace(r"[^A-Za-z0-9]+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )
    return df

def map_columns(df: pd.DataFrame, aliases: Dict[str, List[str]]) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    cols = set(df.columns)
    mapping = {}
    out = pd.DataFrame(index=df.index)
    for target, options in aliases.items():
        found = next((c for c in options if c in cols or c.lower() in [x.lower() for x in cols]), None)
        if found:
            real = next(col for col in df.columns if col.lower() == found.lower())
            out[target] = df[real]
        else:
            out[target] = pd.NA
        mapping[target] = found
    return out.reset_index(drop=True), mapping

PRICE_ALIASES = {
    "Item_Number": ["Item_Number", "ITEMNMBR", "Item"],
    "UOFM": ["UOFM", "UOM", "Unit_of_Measure"],
    "Captured_Process": ["Captured_Process", "CapturedProcess"],
    "Captured_Login_ID": ["Captured_Login_ID", "Login_ID", "User"],
    "Captured_Time_Stamp": ["Captured_Time_Stamp", "Timestamp", "Captured_Time"],
}

SOP_ALIASES = {
    "SOP_Number": ["SOP_Number", "SOPNo", "SOP"],
    "Doc_Date": ["Doc_Date", "Date", "Document_Date"],
    "Item_Number": ["Item_Number", "ITEMNMBR", "Item"],
    "Base_U_of_M": ["Base_U_of_M", "Base_UOM"],
    "Qty_on_Invoice": ["Qty_on_Invoice", "Quantity_on_Invoice"],
    "Extended_Price": ["Extended_Price", "Ext_Price"],
}

# ------------------------------
# File Uploads
# ------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    f1 = st.file_uploader("📂 Item Price Changes – File 1", type=["xls", "xlsx"])
with col2:
    f2 = st.file_uploader("📂 Item Price Changes – File 2", type=["xls", "xlsx"])
with col3:
    f3 = st.file_uploader("📂 SOP Doc File Analysis", type=["xls", "xlsx"])

df1 = read_excel_smart(f1)
df2 = read_excel_smart(f2)
df3 = read_excel_smart(f3)

if not df1.empty:
    df1, _ = map_columns(df1, PRICE_ALIASES)
if not df2.empty:
    df2, _ = map_columns(df2, PRICE_ALIASES)
if not df3.empty:
    df3, _ = map_columns(df3, SOP_ALIASES)

# ------------------------------
# Input section
# ------------------------------
st.markdown("---")
st.subheader("🔎 Search by Multiple Item Numbers")

item_text = st.text_area("Enter item numbers (comma, space, or newline separated):", height=120)
match_mode = st.radio("Match Mode", ["Exact", "Contains"], horizontal=True)

items = sorted(set(re.split(r"[,\\s;]+", item_text.strip()))) if item_text.strip() else []

if items and (not df1.empty or not df2.empty or not df3.empty):

    def filter_items(df, col="Item_Number"):
        if df.empty or col not in df.columns:
            return pd.DataFrame()
        s = df[col].astype(str).str.upper().str.strip()
        if match_mode == "Exact":
            mask = s.isin([i.upper().strip() for i in items])
        else:
            pattern = "|".join(re.escape(i.upper()) for i in items)
            mask = s.str.contains(pattern, na=False)
        return df[mask].reset_index(drop=True)

    q1 = filter_items(df1)
    q2 = filter_items(df2)
    q3 = filter_items(df3)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.write("**Price File 1**")
        st.dataframe(q1 if not q1.empty else pd.DataFrame({"Result": ["No matches."]}), use_container_width=True)
    with c2:
        st.write("**Price File 2**")
        st.dataframe(q2 if not q2.empty else pd.DataFrame({"Result": ["No matches."]}), use_container_width=True)
    with c3:
        st.write("**SOP File**")
        if not q3.empty and "Doc_Date" in q3:
            q3["Doc_Date"] = pd.to_datetime(q3["Doc_Date"], errors="coerce").dt.date
        st.dataframe(q3 if not q3.empty else pd.DataFrame({"Result": ["No matches."]}), use_container_width=True)

    # ------------------------------
    # Merge results
    # ------------------------------
    st.markdown("### 🔗 Combined Comparison (P1 ↔ P2 ↔ SOP)")
    merged = pd.DataFrame()
    if not q1.empty or not q2.empty:
        both = pd.merge(q1, q2, on="Item_Number", how="outer", suffixes=("_P1", "_P2"))
        merged = pd.merge(both, q3, on="Item_Number", how="left")
        st.dataframe(merged, use_container_width=True)
        csv_bytes = merged.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Merged CSV", csv_bytes, "merged_items.csv", "text/csv")
else:
    st.info("Upload your files and enter item numbers to see results.")

st.markdown("""
---
**Tips**
- Enter multiple item numbers separated by commas, spaces, or newlines.
- Use *Contains* for partial matches (e.g., 'MDSM' to match 'MDSM3ACUFFA').
- The app auto-detects header rows and normalizes columns for flexibility.
""")

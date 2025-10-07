import re
import io
import pandas as pd
import streamlit as st
from typing import Dict, List, Tuple, Optional

# ------------------------------
# Page setup
# ------------------------------
st.set_page_config(
    page_title="Item Comparison – Two Price Files vs SOP",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Item Comparison: Two Price Change Files vs SOP (by Item Number)")
st.write(
    "Upload **two Item Price Changes Excel files** and **one SOP Doc File Analysis** Excel. Type an Item Number to view side‑by‑side matches and a merged comparison."
)

# ------------------------------
# Helpers
# ------------------------------

def detect_header_row(file_like, sample_rows: int = 10) -> int:
    """Detect likely header row by scanning first N rows for a row with many non‑NA string‑ish values."""
    file_like.seek(0)
    temp = pd.read_excel(file_like, header=None, nrows=sample_rows)
    best_idx, best_score = 0, -1
    for i, row in temp.iterrows():
        values = row.dropna()
        non_null_ratio = row.notna().mean()
        string_like = values.apply(lambda x: isinstance(x, str) and bool(re.search(r"[A-Za-z]", x))).mean() if len(values) else 0
        score = non_null_ratio * 0.6 + string_like * 0.4
        if score > best_score:
            best_idx, best_score = i, score
    file_like.seek(0)
    return int(best_idx)


def read_excel_smart(uploaded_file) -> pd.DataFrame:
    """Read an Excel file while auto‑detecting the header row and standardizing column names."""
    if uploaded_file is None:
        return pd.DataFrame()
    raw = uploaded_file.read()
    bio = io.BytesIO(raw)
    header_row = detect_header_row(bio)
    df = pd.read_excel(bio, header=header_row)
    # Standardize column names (human and machine friendly)
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.replace("/", " ", regex=False)
        .str.replace("-", " ", regex=False)
        .str.replace("%", " pct ", regex=False)
    )
    df.columns = (
        df.columns.str.strip()
        .str.replace(r"[^A-Za-z0-9]+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )
    return df

PRICE_ALIASES: Dict[str, List[str]] = {
    "Item_Number": ["Item_Number", "ITEMNMBR", "ITEM_NUMBER", "Item", "ItemNo", "ITEM"],
    "UOFM": ["UOFM", "UOM", "Unit_of_Measure"],
    "Captured_Process": ["Captured_Process", "Captured_Process_", "CapturedProcess"],
    "Captured_Login_ID": ["Captured_Login_ID", "Captured_Login_Id", "Login_ID", "User", "Captured_User"],
    "Captured_Time_Stamp": ["Captured_Time_Stamp", "Captured_Timestamp", "Time_Stamp", "Timestamp", "Captured_Time"],
}

SOP_ALIASES: Dict[str, List[str]] = {
    "SOP_Number": ["SOP_Number", "SOPNo", "SOP_Number_", "SOP_Doc", "SOP"],
    "Doc_Date": ["Doc_Date", "Document_Date", "DocDate", "Date"],
    "Item_Number": ["Item_Number", "Item", "ITEMNMBR", "ItemNo", "ITEM"],
    "Base_U_of_M": ["Base_U_of_M", "Base_U_of_M_Qty", "Base_U_of_M_", "Base_UOM", "Base_U_of_M_QTY"],
    "Qty_on_Invoice": ["Qty_on_Invoice", "QTY_on_Invoice", "Quantity_on_Invoice", "Qty", "Qty_Invoiced"],
    "Extended_Price": ["Extended_Price", "Ext_Price", "ExtendedPrice", "ExtPrice"],
}


def map_columns(df: pd.DataFrame, aliases: Dict[str, List[str]]) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    """Map a DataFrame's columns to target names using alias lists; returns (mapped_df, mapping)."""
    cols = set(df.columns)
    mapping: Dict[str, Optional[str]] = {}
    out = pd.DataFrame(index=df.index)
    for target, choices in aliases.items():
        found = None
        for c in choices:
            if c in cols:
                found = c
                break
            lc = c.lower()
            matches = [col for col in cols if col.lower() == lc]
            if matches:
                found = matches[0]
                break
        mapping[target] = found
        out[target] = df[found] if found is not None else pd.NA
    return out, mapping

# ------------------------------
# UI – Upload three files
# ------------------------------
col_u1, col_u2, col_u3 = st.columns(3)
with col_u1:
    up_price1 = st.file_uploader("Upload **Item Price Changes – File 1**", type=["xls", "xlsx"], key="price1")
with col_u2:
    up_price2 = st.file_uploader("Upload **Item Price Changes – File 2**", type=["xls", "xlsx"], key="price2")
with col_u3:
    up_sop = st.file_uploader("Upload **SOP Doc File Analysis**", type=["xls", "xlsx"], key="sop")

price1_df = pd.DataFrame(); price2_df = pd.DataFrame(); sop_df = pd.DataFrame()

if up_price1 is not None:
    raw1 = read_excel_smart(up_price1)
    price1_df, _ = map_columns(raw1, PRICE_ALIASES)
if up_price2 is not None:
    raw2 = read_excel_smart(up_price2)
    price2_df, _ = map_columns(raw2, PRICE_ALIASES)
if up_sop is not None:
    raw3 = read_excel_smart(up_sop)
    sop_df, _ = map_columns(raw3, SOP_ALIASES)

# ------------------------------
# Status & Preview
# ------------------------------
col_p1, col_p2, col_p3 = st.columns(3)
with col_p1:
    st.subheader("Price Changes – File 1")
    if not price1_df.empty:
        st.dataframe(price1_df.head(10))
    else:
        st.info("Waiting for File 1…")
with col_p2:
    st.subheader("Price Changes – File 2")
    if not price2_df.empty:
        st.dataframe(price2_df.head(10))
    else:
        st.info("Waiting for File 2…")
with col_p3:
    st.subheader("SOP Doc File Analysis")
    if not sop_df.empty:
        st.dataframe(sop_df.head(10))
    else:
        st.info("Waiting for SOP Doc file…")

# ------------------------------
# Query by Item Number
# ------------------------------
st.markdown("---")
st.subheader("🔎 Search by Item Number")
item = st.text_input("Type an Item Number (exact or partial)", placeholder="e.g., MDSM3ACUFFA or 12345")
match_mode = st.radio("Match mode", ["Exact", "Contains"], horizontal=True)

if item and (not price1_df.empty or not price2_df.empty or not sop_df.empty):
    def norm(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip()

    def filter_df(df_in: pd.DataFrame) -> pd.DataFrame:
        if df_in.empty or "Item_Number" not in df_in:
            return pd.DataFrame(columns=df_in.columns)
        s = norm(df_in["Item_Number"])
        key = item.strip().upper()
        if match_mode == "Exact":
            m = s.str.upper() == key
        else:
            m = s.str.upper().str.contains(re.escape(key), na=False)
        return df_in[m].copy()

    p1_q = filter_df(price1_df)
    p2_q = filter_df(price2_df)
    sop_q = filter_df(sop_df)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.write("**Price File 1 – Matches**")
        if not p1_q.empty:
            st.dataframe(p1_q[[c for c in ["Item_Number", "UOFM", "Captured_Process", "Captured_Login_ID", "Captured_Time_Stamp"] if c in p1_q.columns]])
        else:
            st.warning("No matches in File 1.")
    with c2:
        st.write("**Price File 2 – Matches**")
        if not p2_q.empty:
            st.dataframe(p2_q[[c for c in ["Item_Number", "UOFM", "Captured_Process", "Captured_Login_ID", "Captured_Time_Stamp"] if c in p2_q.columns]])
        else:
            st.warning("No matches in File 2.")
    with c3:
        st.write("**SOP Doc – Matches**")
        if not sop_q.empty:
            if "Doc_Date" in sop_q:
                sop_q["Doc_Date"] = pd.to_datetime(sop_q["Doc_Date"], errors="coerce").dt.date
            st.dataframe(sop_q[[c for c in ["SOP_Number", "Doc_Date", "Item_Number", "Base_U_of_M", "Qty_on_Invoice", "Extended_Price"] if c in sop_q.columns]])
        else:
            st.warning("No matches in SOP.")

    # ------------------------------
    # Merged comparison: Price1 ↔ Price2, then join SOP on Item_Number
    # ------------------------------
    st.markdown("### 🔗 Merged Comparison (P1 ↔ P2 ↔ SOP)")
    merged = None
    if not p1_q.empty or not p2_q.empty:
        if not p1_q.empty and not p2_q.empty:
            both = pd.merge(
                p1_q,
                p2_q,
                on="Item_Number",
                how="outer",
                suffixes=("_P1", "_P2"),
                indicator=False,
            )
        else:
            both = pd.concat([p1_q, p2_q], axis=0, ignore_index=True)
        if not sop_q.empty:
            merged = pd.merge(both, sop_q, on="Item_Number", how="left")
        else:
            merged = both

        # Choose clean column order if present
        keep_cols = []
        # Common key
        keep_cols += ["Item_Number"] if "Item_Number" in (merged.columns) else []
        # Price 1
        for c in ["UOFM_P1", "Captured_Process_P1", "Captured_Login_ID_P1", "Captured_Time_Stamp_P1"]:
            if c in merged.columns: keep_cols.append(c)
        # Price 2
        for c in ["UOFM_P2", "Captured_Process_P2", "Captured_Login_ID_P2", "Captured_Time_Stamp_P2"]:
            if c in merged.columns: keep_cols.append(c)
        # If we concatenated instead of suffix merge, fall back to base names
        for c in ["UOFM", "Captured_Process", "Captured_Login_ID", "Captured_Time_Stamp"]:
            if c in merged.columns and c not in keep_cols: keep_cols.append(c)
        # SOP
        for c in ["SOP_Number", "Doc_Date", "Base_U_of_M", "Qty_on_Invoice", "Extended_Price"]:
            if c in merged.columns: keep_cols.append(c)

        st.dataframe(merged[keep_cols] if keep_cols else merged)

        # Download
        csv_bytes = (merged[keep_cols] if keep_cols else merged).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download merged CSV",
            data=csv_bytes,
            file_name=f"item_{re.sub(r'[^A-Za-z0-9]+','_', item)}_P1_P2_SOP_comparison.csv",
            mime="text/csv",
        )
    else:
        st.info("Provide matching items in at least one Price file to generate the merged view.")

# Footer tip
st.markdown("""
---
**Tips**
- The app auto‑detects header rows and normalizes column names.
- Works even if files have slightly different column spellings (aliases are mapped).
- Use **Contains** mode for partial item codes.
""")

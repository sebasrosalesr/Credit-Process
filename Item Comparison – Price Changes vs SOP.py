import re
import io
import pandas as pd
import streamlit as st
from typing import Dict, List, Tuple, Optional

# ------------------------------
# Page setup
# ------------------------------
st.set_page_config(
    page_title="Item Comparison – Price Changes vs SOP",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Item Comparison: Price Changes vs SOP (by Item Number)")
st.write(
    "Upload the two Excel files (Price Changes and SOP Doc Analysis), then type an **Item Number** to view matching records and side‑by‑side details."
)

# ------------------------------
# Helpers
# ------------------------------

def detect_header_row(file_like, sample_rows: int = 10) -> int:
    """Detect likely header row by scanning first N rows for a row with many non‑NA stringish values."""
    file_like.seek(0)
    temp = pd.read_excel(file_like, header=None, nrows=sample_rows)
    best_idx, best_score = 0, -1
    for i, row in temp.iterrows():
        values = row.dropna()
        # score by fraction non-null + how many look like strings (letters, words)
        non_null_ratio = row.notna().mean()
        string_like = values.apply(lambda x: isinstance(x, str) and bool(re.search(r"[A-Za-z]", x))).mean() if len(values) else 0
        score = non_null_ratio * 0.6 + string_like * 0.4
        if score > best_score:
            best_idx, best_score = i, score
    file_like.seek(0)
    return int(best_idx)


def read_excel_smart(uploaded_file) -> pd.DataFrame:
    """Read an Excel file while auto-detecting the header row and standardizing column names."""
    if uploaded_file is None:
        return pd.DataFrame()
    # Work on a BytesIO copy so we can seek repeatedly
    raw = uploaded_file.read()
    bio = io.BytesIO(raw)
    header_row = detect_header_row(bio)
    df = pd.read_excel(bio, header=header_row)
    # Standardize column names
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\n", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.replace("/", " ", regex=False)
        .str.replace("-", " ", regex=False)
        .str.replace("%", " pct ", regex=False)
    )
    # Also provide a machine-friendly version
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
    "Captured_Time_Stamp": ["Captured_Time_Stamp", "Captured_Timestamp", "Time_Stamp", "Timestamp", "Captured_Time"]
}

SOP_ALIASES: Dict[str, List[str]] = {
    "SOP_Number": ["SOP_Number", "SOPNo", "SOP_Number_", "SOP_Doc", "SOP"],
    "Doc_Date": ["Doc_Date", "Document_Date", "DocDate", "Date"],
    "Item_Number": ["Item_Number", "Item", "ITEMNMBR", "ItemNo", "ITEM"],
    "Base_U_of_M": ["Base_U_of_M", "Base_U_of_M_Qty", "Base_U_of_M_", "Base_UOM", "Base_U_of_M_QTY"],
    "Qty_on_Invoice": ["Qty_on_Invoice", "QTY_on_Invoice", "Quantity_on_Invoice", "Qty", "Qty_Invoiced"],
    "Extended_Price": ["Extended_Price", "Ext_Price", "ExtendedPrice", "ExtPrice"]
}


def map_columns(df: pd.DataFrame, aliases: Dict[str, List[str]]) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    """Map a DataFrame's columns to target names using alias lists.
    Returns (df_mapped, mapping_dict) where df_mapped has standardized target columns when found.
    """
    cols = set(df.columns)
    mapping: Dict[str, Optional[str]] = {}
    out = pd.DataFrame(index=df.index)
    for target, choices in aliases.items():
        found = None
        for c in choices:
            if c in cols:
                found = c
                break
            # try lower-case fallback
            lc = c.lower()
            matches = [col for col in cols if col.lower() == lc]
            if matches:
                found = matches[0]
                break
        mapping[target] = found
        if found is not None:
            out[target] = df[found]
        else:
            out[target] = pd.NA
    return out, mapping


def detect_dataset_type(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    price_keys = {"ITEMNMBR", "Captured_Process", "Captured_Login_ID", "Captured_Time_Stamp", "Item_Number", "UOFM"}
    sop_keys = {"SOP_Number", "Doc_Date", "Item_Number", "Base_U_of_M", "Qty_on_Invoice", "Extended_Price"}
    price_score = len({c for c in cols if c in price_keys})
    sop_score = len({c for c in cols if c in sop_keys})
    if price_score >= sop_score and price_score > 0:
        return "price"
    if sop_score > 0:
        return "sop"
    return "unknown"


# ------------------------------
# UI – Upload
# ------------------------------
col_up1, col_up2 = st.columns(2)
with col_up1:
    up_price = st.file_uploader("Upload **Item Price Changes** Excel", type=["xls", "xlsx"], key="price")
with col_up2:
    up_sop = st.file_uploader("Upload **SOP Doc File Analysis** Excel", type=["xls", "xlsx"], key="sop")

# Allow drag-drop in any order; we'll auto-detect
c1, c2 = st.columns(2)

price_df, sop_df = pd.DataFrame(), pd.DataFrame()
price_map, sop_map = {}, {}

if up_price is not None:
    raw1 = read_excel_smart(up_price)
    kind1 = detect_dataset_type(raw1)
    if kind1 == "price":
        price_df, price_map = map_columns(raw1, PRICE_ALIASES)
    elif kind1 == "sop":
        sop_df, sop_map = map_columns(raw1, SOP_ALIASES)
    else:
        st.warning("Could not detect the type of the first upload. Please ensure it is either Price Changes or SOP.")

if up_sop is not None:
    raw2 = read_excel_smart(up_sop)
    kind2 = detect_dataset_type(raw2)
    if kind2 == "price":
        price_df, price_map = map_columns(raw2, PRICE_ALIASES)
    elif kind2 == "sop":
        sop_df, sop_map = map_columns(raw2, SOP_ALIASES)
    else:
        st.warning("Could not detect the type of the second upload. Please ensure it is either Price Changes or SOP.")

# If both uploads ended up same type, allow manual override
if up_price and up_sop and (price_df.empty or sop_df.empty):
    st.info("If auto-detection misclassified files, assign them below.")
    assign_col1, assign_col2 = st.columns(2)
    with assign_col1:
        assign_price_as = st.selectbox("Treat first upload as:", ["auto", "price", "sop"], index=0, key="ap")
    with assign_col2:
        assign_sop_as = st.selectbox("Treat second upload as:", ["auto", "price", "sop"], index=0, key="as")
    # Re-map if needed
    if assign_price_as in ("price", "sop"):
        up_price.seek(0)
        raw1 = read_excel_smart(up_price)
        if assign_price_as == "price":
            price_df, price_map = map_columns(raw1, PRICE_ALIASES)
        else:
            sop_df, sop_map = map_columns(raw1, SOP_ALIASES)
    if assign_sop_as in ("price", "sop"):
        up_sop.seek(0)
        raw2 = read_excel_smart(up_sop)
        if assign_sop_as == "price":
            price_df, price_map = map_columns(raw2, PRICE_ALIASES)
        else:
            sop_df, sop_map = map_columns(raw2, SOP_ALIASES)

# ------------------------------
# UI – Status & Preview
# ------------------------------
status1, status2 = st.columns(2)
with status1:
    st.subheader("Item Price Changes – Mapped Columns")
    if not price_df.empty:
        st.dataframe(price_df.head(10))
        st.caption(f"Columns mapped: {', '.join(price_df.columns)}")
    else:
        st.info("Waiting for a valid Price Changes file…")
with status2:
    st.subheader("SOP Doc File Analysis – Mapped Columns")
    if not sop_df.empty:
        st.dataframe(sop_df.head(10))
        st.caption(f"Columns mapped: {', '.join(sop_df.columns)}")
    else:
        st.info("Waiting for a valid SOP Doc file…")

# ------------------------------
# UI – Query by Item Number
# ------------------------------
st.markdown("---")
st.subheader("🔎 Search by Item Number")
item = st.text_input("Type an Item Number (exact or partial)", placeholder="e.g., MDSM3ACUFFA or 12345")
match_mode = st.radio("Match mode", ["Exact", "Contains"], horizontal=True)

if item and (not price_df.empty or not sop_df.empty):
    # Normalize for matching
    def norm(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip()

    price_q = pd.DataFrame()
    sop_q = pd.DataFrame()

    if not price_df.empty:
        s = norm(price_df["Item_Number"]) if "Item_Number" in price_df else pd.Series(dtype=str)
        if match_mode == "Exact":
            price_q = price_df[s.str.upper() == item.strip().upper()].copy()
        else:
            price_q = price_df[s.str.upper().str.contains(re.escape(item.strip().upper()), na=False)].copy()

    if not sop_df.empty:
        s = norm(sop_df["Item_Number"]) if "Item_Number" in sop_df else pd.Series(dtype=str)
        if match_mode == "Exact":
            sop_q = sop_df[s.str.upper() == item.strip().upper()].copy()
        else:
            sop_q = sop_df[s.str.upper().str.contains(re.escape(item.strip().upper()), na=False)].copy()

    # Display results in two columns
    r1, r2 = st.columns(2)
    with r1:
        st.write("**Item Price Changes (matching)**")
        if not price_q.empty:
            st.dataframe(price_q[[c for c in ["Item_Number", "UOFM", "Captured_Process", "Captured_Login_ID", "Captured_Time_Stamp"] if c in price_q.columns]])
        else:
            st.warning("No matches found in Price Changes.")
    with r2:
        st.write("**SOP Doc File Analysis (matching)**")
        if not sop_q.empty:
            # Attempt to coerce Doc_Date to date for nicer display
            if "Doc_Date" in sop_q:
                sop_q["Doc_Date"] = pd.to_datetime(sop_q["Doc_Date"], errors="coerce").dt.date
            st.dataframe(sop_q[[c for c in ["SOP_Number", "Doc_Date", "Item_Number", "Base_U_of_M", "Qty_on_Invoice", "Extended_Price"] if c in sop_q.columns]])
        else:
            st.warning("No matches found in SOP Doc Analysis.")

    # Merged view for convenience (left join price -> SOP)
    st.markdown("### 🔗 Merged View (Price ↔ SOP)")
    if not price_q.empty or not sop_q.empty:
        left = price_q.copy()
        right = sop_q.copy()
        if not left.empty and "Item_Number" in left and not right.empty and "Item_Number" in right:
            merged = pd.merge(
                left,
                right,
                on="Item_Number",
                how="left",
                suffixes=("_Price", "_SOP"),
            )
        else:
            # If one side empty, just concatenate whatever is available
            merged = pd.concat([left, right], axis=0, ignore_index=True)
        # Keep only requested columns if present
        keep_cols = [
            "Item_Number",
            "UOFM", "Captured_Process", "Captured_Login_ID", "Captured_Time_Stamp",
            "SOP_Number", "Doc_Date", "Base_U_of_M", "Qty_on_Invoice", "Extended_Price",
        ]
        keep_cols = [c for c in keep_cols if c in merged.columns]
        st.dataframe(merged[keep_cols])

        # Download buttons
        csv_bytes = merged[keep_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download merged CSV",
            data=csv_bytes,
            file_name=f"item_{re.sub(r'[^A-Za-z0-9]+','_', item)}_comparison.csv",
            mime="text/csv",
        )
    else:
        st.info("Upload files and enter an Item Number to see merged results.")

# Footer tip
st.markdown("""
---
**Tips**
- If your files have extra rows at the top, the app auto-detects the header row.
- Column names are standardized (spaces → underscores) to avoid merge issues.
- Use **Contains** mode if your Item Numbers have variable suffixes/prefixes.
""")

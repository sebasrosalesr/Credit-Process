# app.py
import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Invoice/Item Lookup", layout="wide")
st.title("🔎 Invoice + Item Lookup (Two-Workbook Viewer)")

# --------------------- helpers ---------------------
def norm_invoice(x: str) -> str:
    if x is None:
        return ""
    # keep letters+digits only, lower-case
    return re.sub(r"[^a-z0-9]", "", str(x).strip().lower())

def norm_item(x: str) -> str:
    if x is None:
        return ""
    # normalize dashes to "-" and remove spaces; keep letters/digits/dash
    s = str(x).strip().upper().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^A-Z0-9\-_/]", "", s)
    return s

def read_any_excel(uploaded) -> pd.DataFrame | None:
    if not uploaded:
        return None
    try:
        xls = pd.ExcelFile(uploaded)
        sheet = st.selectbox(
            f"Select sheet for **{uploaded.name}**",
            xls.sheet_names,
            index=0,
            key=f"sheet_{uploaded.name}",
        )
        return pd.read_excel(xls, sheet_name=sheet)
    except Exception as e:
        st.error(f"Could not read {getattr(uploaded,'name','file')}: {e}")
        return None

def get_col_index(df: pd.DataFrame, label: str) -> int | None:
    """Find a column by fuzzy label (case/space/punct insensitive)."""
    def norm_label(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())
    wanted = norm_label(label)
    for i, c in enumerate(df.columns):
        if norm_label(str(c)) == wanted:
            return i
    return None

def slice_cols_range(df: pd.DataFrame, start_label: str, end_label: str) -> pd.DataFrame:
    """Return df with columns from start_label..end_label (inclusive) by position."""
    si = get_col_index(df, start_label)
    ei = get_col_index(df, end_label)
    if si is None or ei is None:
        missing = []
        if si is None: missing.append(start_label)
        if ei is None: missing.append(end_label)
        st.warning(f"Columns not found: {', '.join(missing)}. Showing all columns for debugging.")
        return df
    if si > ei:
        si, ei = ei, si
    return df.iloc[:, si:ei+1]

def filter_by_invoice_item(df: pd.DataFrame, inv_col_guess: str, item_col_guess: str,
                           invoice_in: str, item_in: str) -> pd.DataFrame:
    inv_i = get_col_index(df, inv_col_guess)
    it_i  = get_col_index(df, item_col_guess)
    if inv_i is None or it_i is None:
        st.warning(f"Could not find `{inv_col_guess}` or `{item_col_guess}` in: {list(df.columns)}")
        return pd.DataFrame(columns=df.columns)

    df2 = df.copy()
    df2["_inv_norm_"]  = df2.iloc[:, inv_i].map(norm_invoice)
    df2["_item_norm_"] = df2.iloc[:, it_i].map(norm_item)

    inv_norm  = norm_invoice(invoice_in)
    item_norm = norm_item(item_in)

    return df2[(df2["_inv_norm_"] == inv_norm) & (df2["_item_norm_"] == item_norm)].drop(columns=["_inv_norm_","_item_norm_"])

def download_link(df: pd.DataFrame, filename: str, label: str):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(label=label, data=buf.getvalue(), file_name=filename, mime="text/csv")

# --------------------- inputs ---------------------
colL, colR = st.columns(2)
with colL:
    req_file = st.file_uploader("📥 Upload **Requestor Template** (Excel)", type=["xlsx", "xls", "csv"])
with colR:
    upd_file = st.file_uploader("📥 Upload **Updated Credit Calculation** (Excel)", type=["xlsx", "xls", "csv"])

st.markdown("---")
inv_in = st.text_input("📄 Invoice Number", placeholder="e.g., INV14165606")
item_in = st.text_input("🔢 Item Number", placeholder="e.g., 005-503356")

if st.button("Search"):
    # ---------- Requestor Template ----------
    if req_file:
        if req_file.name.lower().endswith(".csv"):
            req_df = pd.read_csv(req_file)
        else:
            req_df = read_any_excel(req_file)
        if req_df is not None:
            # The requestor template: display D..L (Invoice Number .. Reason for Credit)
            # First filter by invoice+item using best-guess column names
            req_filtered = filter_by_invoice_item(
                req_df, inv_col_guess="Invoice Number", item_col_guess="Item Number",
                invoice_in=inv_in, item_in=item_in
            )
            if req_filtered.empty:
                st.info("No matching rows in **Requestor Template** for this invoice + item.")
            else:
                req_slice = slice_cols_range(req_filtered, "Invoice Number", "Reason for Credit")
                st.subheader("📄 Requestor Template (Columns D–L)")
                st.dataframe(req_slice, use_container_width=True)
                download_link(req_slice, "requestor_D_to_L.csv", "⬇️ Download Requestor Slice")
    else:
        st.warning("Upload the **Requestor Template**.")

    # ---------- Updated Credit Calculation ----------
    if upd_file:
        if upd_file.name.lower().endswith(".csv"):
            upd_df = pd.read_csv(upd_file)
        else:
            upd_df = read_any_excel(upd_file)
        if upd_df is not None:
            # The updated calc: display D..O (Subbed_QTY .. Credit_AM), filtered by invoice+item
            # Guess invoice & item column labels as in your screenshot
            upd_filtered = filter_by_invoice_item(
                upd_df, inv_col_guess="Invoice_No", item_col_guess="Item_No",
                invoice_in=inv_in, item_in=item_in
            )
            if upd_filtered.empty:
                st.info("No matching rows in **Updated Credit Calculation** for this invoice + item.")
            else:
                upd_slice = slice_cols_range(upd_filtered, "Subbed_QTY", "Credit_AM")
                st.subheader("📊 Updated Credit Calculation (Columns D–O)")
                st.dataframe(upd_slice, use_container_width=True)
                download_link(upd_slice, "updated_calc_D_to_O.csv", "⬇️ Download Updated Calc Slice")
    else:
        st.warning("Upload the **Updated Credit Calculation** file.")

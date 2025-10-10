# streamlit_app.py
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="GL Code Lookup by Item", layout="wide")
st.title("🔎 GL Code Lookup by Item Number")
st.caption("Paste item numbers, upload your Item Master, and get GL Code + Class mapping.")

# -----------------------------
# 1) Hard-coded Item Class → GL Code table (from your image)
# -----------------------------
CLASS_TABLE = pd.DataFrame([
    {"Item Class ID": "EQI-002", "Item Class Description": "Equipment",                   "GL Code": 5130},
    {"Item Class ID": "GLO-003", "Item Class Description": "Gloves",                      "GL Code": None},
    {"Item Class ID": "INC-004", "Item Class Description": "Incontinence Supplies",       "GL Code": 5133},
    {"Item Class ID": "NUR-005", "Item Class Description": "Nursing Supplies",            "GL Code": 5130},
    {"Item Class ID": "NUT-006", "Item Class Description": "Nutrition Products",          "GL Code": 5655},
    {"Item Class ID": "OST-007", "Item Class Description": "Ostomy Products",             "GL Code": None},
    {"Item Class ID": "OTC-008", "Item Class Description": "Over the Counter Drugs",      "GL Code": 5130},
    {"Item Class ID": "P&P-009", "Item Class Description": "Paper & Plastic",             "GL Code": 4515},
    {"Item Class ID": "RES-010", "Item Class Description": "Respiratory Products",        "GL Code": 5130},
    {"Item Class ID": "RET-011", "Item Class Description": "Restraints",                  "GL Code": None},
    {"Item Class ID": "SOL-012", "Item Class Description": "Solutions",                   "GL Code": None},
    {"Item Class ID": "TEX-013", "Item Class Description": "Textile Products",            "GL Code": None},
    {"Item Class ID": "JAN-016", "Item Class Description": "Janitorial / Sanitation",     "GL Code": None},
])

# -----------------------------
# 2) Helpers
# -----------------------------
def normalize_colname(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", str(s).strip().lower()).strip()

def pick_column(df: pd.DataFrame, candidates: list[str], fallback_index: int | None = None):
    norm_map = {c: normalize_colname(c) for c in df.columns}
    for col, norm in norm_map.items():
        if norm in candidates:
            return col
    if fallback_index is not None and 0 <= fallback_index < len(df.columns):
        return df.columns[fallback_index]
    return None

def parse_item_numbers(raw: str) -> list[str]:
    import re
    tokens = re.split(r"[,\n;\t ]+", raw.strip())
    items, seen = [], set()
    for t in tokens:
        t = t.strip()
        if t and t not in seen:
            seen.add(t); items.append(t)
    return items

def load_item_master(upload) -> pd.DataFrame:
    """Load Item Master (Excel/CSV)."""
    name = upload.name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(upload, engine="openpyxl")
    if name.endswith(".csv"):
        return pd.read_csv(upload)
    # Try Excel then CSV
    try:
        return pd.read_excel(upload, engine="openpyxl")
    except Exception:
        upload.seek(0)
        return pd.read_csv(upload)

# -----------------------------
# 3) UI: Inputs
# -----------------------------
left, right = st.columns([1,1.2], gap="large")

with left:
    raw_items = st.text_area(
        "📥 Paste Item Numbers",
        placeholder="E.g.\n12345\nABC-001, 987654\nP&P-009-ITEM",
        height=160
    )
    st.caption("You can paste one per line, or separated by commas/spaces.")

with right:
    im_file = st.file_uploader(
        "📄 Upload Item Master (Excel/CSV)",
        type=["xlsx","xlsm","xls","csv"],
        help="Must contain Item Number in column A (or a column named 'Item Number') and Item Class ID in column D (or a column named like 'Item Class ID')."
    )

# -----------------------------
# 4) Process
# -----------------------------
if raw_items and im_file:
    try:
        items = parse_item_numbers(raw_items)
        st.write(f"**Items detected:** {len(items)}")
        st.code(", ".join(items[:30]) + (" …" if len(items) > 30 else ""))

        df_im = load_item_master(im_file)
        if df_im.empty:
            st.error("Uploaded Item Master seems empty.")
            st.stop()

        # Locate columns in Item Master
        item_col = pick_column(
            df_im,
            candidates=["item number", "item #", "item id", "item", "number", "sku", "itemno", "itemnum"],
            fallback_index=0  # Column A
        )
        class_col = pick_column(
            df_im,
            candidates=["item class id", "item class", "class id", "class"],
            fallback_index=3  # Column D
        )
        desc_col = pick_column(
            df_im,
            candidates=["description", "item description", "item name", "desc"],
            fallback_index=None
        )

        missing = [n for n,(v) in [("Item # (A)", item_col), ("Item Class ID (D)", class_col)] if v is None]
        if missing:
            st.error(f"Could not find required column(s) in Item Master: {', '.join(missing)}.")
            st.stop()

        keep_cols = [c for c in [item_col, desc_col, class_col] if c is not None]
        df_im = df_im[keep_cols].copy()

        rename_map = {}
        if item_col: rename_map[item_col] = "Item #"
        if desc_col: rename_map[desc_col] = "Description"
        if class_col: rename_map[class_col] = "Item Class ID"
        df_im = df_im.rename(columns=rename_map)

        df_filtered = df_im[df_im["Item #"].astype(str).isin(items)].copy()
        if df_filtered.empty:
            st.warning("No matching Item Numbers found in the uploaded Item Master.")
            st.stop()

        df_out = df_filtered.merge(CLASS_TABLE, on="Item Class ID", how="left")

        for col in ["Description", "Item Class Description", "GL Code"]:
            if col not in df_out.columns:
                df_out[col] = None

        df_out = df_out[["GL Code", "Item #", "Description", "Item Class ID", "Item Class Description"]]

        st.subheader("✅ Results")
        st.dataframe(df_out, use_container_width=True)

        csv = df_out.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv, file_name="gl_code_lookup_results.csv", mime="text/csv")

        with st.expander("ℹ️ Column detection details"):
            st.write(f"Detected **Item #** column: `{item_col}`")
            st.write(f"Detected **Item Class ID** column: `{class_col}`")
            st.write(f"Detected **Description** column: `{desc_col or 'None'}`")

    except Exception as e:
        st.error(f"Something went wrong: {e}")

elif not raw_items:
    st.info("Paste your Item Numbers to begin.")
elif not im_file:
    st.info("Upload your Item Master to continue.")

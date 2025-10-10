# streamlit_app.py
import re
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="GL Code Lookup by Item", layout="wide")
st.title("🔎 GL Code Lookup by Item Number")
st.caption("Paste item numbers, upload your Customer Master, and get GL Code + Class mapping.")

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
    return re.sub(r"[^a-z0-9]+", " ", str(s).strip().lower()).strip()

def pick_column(df: pd.DataFrame, candidates: list[str], fallback_index: int | None = None):
    """
    Try to find a column by name (case/space tolerant). If not found and fallback_index is set,
    return the column at that 0-based index (e.g., 0 -> column A, 3 -> column D).
    """
    norm_map = {c: normalize_colname(c) for c in df.columns}
    for col, norm in norm_map.items():
        if norm in candidates:
            return col
    if fallback_index is not None and 0 <= fallback_index < len(df.columns):
        return df.columns[fallback_index]
    return None

def parse_item_numbers(raw: str) -> list[str]:
    # split on commas, semicolons, newlines, tabs, and spaces—but keep hyphens/letters/digits
    tokens = re.split(r"[,\n;\t ]+", raw.strip())
    items = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # Keep as-is (item numbers can have letters, dashes, etc.)
        items.append(t)
    # Preserve order but unique
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def load_customer_master(upload) -> pd.DataFrame:
    # Supports Excel and CSV
    name = upload.name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(upload, engine="openpyxl")
    elif name.endswith(".csv"):
        df = pd.read_csv(upload)
    else:
        # try excel by default
        try:
            df = pd.read_excel(upload, engine="openpyxl")
        except Exception:
            upload.seek(0)
            df = pd.read_csv(upload)
    return df

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
    cm_file = st.file_uploader(
        "📄 Upload Customer Master (Excel/CSV)",
        type=["xlsx","xlsm","xls","csv"],
        help="Must contain Item Number in column A (or a column named 'Item Number') and Item Class ID in column D (or a column named like 'Item Class ID')."
    )

# -----------------------------
# 4) Process
# -----------------------------
if raw_items and cm_file:
    try:
        items = parse_item_numbers(raw_items)
        st.write(f"**Items detected:** {len(items)}")
        st.code(", ".join(items) if len(items) <= 30 else f"{', '.join(items[:30])}, …")

        df_cm = load_customer_master(cm_file)
        if df_cm.empty:
            st.error("Uploaded file seems empty.")
            st.stop()

        # Try to locate columns
        item_col = pick_column(
            df_cm,
            candidates=[
                "item number", "item #", "item id", "item", "number", "sku", "itemno", "itemnum"
            ],
            fallback_index=0  # Column A
        )
        class_col = pick_column(
            df_cm,
            candidates=["item class id", "item class", "class id", "class"],
            fallback_index=3  # Column D
        )
        desc_col = pick_column(
            df_cm,
            candidates=["description", "item description", "item name", "desc"],
            fallback_index=None
        )

        missing = [n for n,(v) in [("Item # (A)", item_col), ("Item Class ID (D)", class_col)] if v is None]
        if missing:
            st.error(f"Could not find required column(s): {', '.join(missing)}.")
            st.stop()

        # Keep only the columns we need
        keep_cols = [c for c in [item_col, desc_col, class_col] if c is not None]
        df_cm = df_cm[keep_cols].copy()

        # Rename to standard names
        rename_map = {}
        if item_col: rename_map[item_col] = "Item #"
        if desc_col: rename_map[desc_col] = "Description"
        if class_col: rename_map[class_col] = "Item Class ID"
        df_cm = df_cm.rename(columns=rename_map)

        # Filter by requested items
        df_filtered = df_cm[df_cm["Item #"].astype(str).isin(items)].copy()
        if df_filtered.empty:
            st.warning("No matching Item Numbers found in the uploaded Customer Master.")
            st.stop()

        # Merge with hard-coded table
        df_out = df_filtered.merge(CLASS_TABLE, on="Item Class ID", how="left")

        # Reorder & final columns
        for col in ["Description", "Item Class Description", "GL Code"]:
            if col not in df_out.columns:
                df_out[col] = None

        df_out = df_out[["GL Code", "Item #", "Description", "Item Class ID", "Item Class Description"]]

        st.subheader("✅ Results")
        st.dataframe(df_out, use_container_width=True)

        # Download
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
elif not cm_file:
    st.info("Upload your Customer Master to continue.")

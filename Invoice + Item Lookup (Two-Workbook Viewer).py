# app.py
import io, re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Credit Comparison", layout="wide")
st.title("🧮 Credit Comparison — Requestor vs Updated Calculator")

# ---------------- helpers ----------------
def norm_invoice(x: str) -> str:
    if x is None: return ""
    return re.sub(r"[^a-z0-9]", "", str(x).strip().lower())

def norm_item(x: str) -> str:
    if x is None: return ""
    s = str(x).strip().upper().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)
    return s

def to_number(x):
    """Convert currency/strings to float; NaN -> 0 (or None if you prefer)."""
    if pd.isna(x): return 0.0
    s = str(x).replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0

def fuzzy_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Pick the first column whose normalized name matches any candidate."""
    def norm(s): return re.sub(r"[^a-z0-9]", "", str(s).lower())
    cols = {norm(c): c for c in df.columns}
    for want in candidates:
        c = cols.get(norm(want))
        if c: return c
    return None

def read_tabular(uploaded):
    if uploaded.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded)
    return pd.read_excel(uploaded)

def download_csv(df: pd.DataFrame, filename: str, label: str):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(label, data=buf.getvalue(), file_name=filename, mime="text/csv")

# ---------------- inputs ----------------
c1, c2 = st.columns(2)
with c1:
    req_file = st.file_uploader("📥 Requestor file (e.g., *Pricing Credits.xlsx* or template)", type=["xlsx","xls","csv"])
with c2:
    calc_file = st.file_uploader("📥 Updated Credits Calculator file", type=["xlsx","xls","csv"])

with st.expander("⚙️ Column mapping (auto-detected; edit if needed)"):
    st.caption("We’ll try to find these; adjust if your headers differ.")
    req_inv_label  = st.text_input("Requestor: Invoice column", value="Invoice Number")
    req_item_label = st.text_input("Requestor: Item column", value="Item Number")
    req_amt_label  = st.text_input("Requestor: Credit amount column", value="Credit Request Total")

    calc_inv_label  = st.text_input("Calculator: Invoice column", value="Invoice_No")
    calc_item_label = st.text_input("Calculator: Item column", value="Item_No")
    calc_amt_label  = st.text_input("Calculator: Credit amount column", value="Credit_AM")

tol = st.number_input("Amount tolerance (treat differences ≤ tolerance as equal)", min_value=0.0, value=0.01, step=0.01)

# ---------------- run ----------------
if st.button("🔎 Compare"):
    if not req_file or not calc_file:
        st.warning("Upload both files to run the comparison.")
        st.stop()

    # Read
    req_df  = read_tabular(req_file)
    calc_df = read_tabular(calc_file)

    # Detect columns
    req_inv_col  = fuzzy_col(req_df, [req_inv_label, "Invoice Number", "Invoice_Number", "Invoice"])
    req_item_col = fuzzy_col(req_df, [req_item_label, "Item Number", "Item_Number", "Item No", "Item_No"])
    req_amt_col  = fuzzy_col(req_df, [req_amt_label, "Credit Request Total", "Credit_Total", "Credit Amount"])

    calc_inv_col  = fuzzy_col(calc_df, [calc_inv_label, "Invoice_No", "Invoice Number", "Invoice"])
    calc_item_col = fuzzy_col(calc_df, [calc_item_label, "Item_No", "Item Number", "Item"])
    calc_amt_col  = fuzzy_col(calc_df, [calc_amt_label, "Credit_AM", "Credit Amount", "Credit"])

    missing = [name for name, col in [
        ("Requestor: Invoice", req_inv_col),
        ("Requestor: Item", req_item_col),
        ("Requestor: Amount", req_amt_col),
        ("Calculator: Invoice", calc_inv_col),
        ("Calculator: Item", calc_item_col),
        ("Calculator: Amount", calc_amt_col),
    ] if col is None]

    if missing:
        st.error("Could not find columns: " + ", ".join(missing))
        st.stop()

    # Normalize & prep keys
    req = req_df.copy()
    req["_inv"]  = req[req_inv_col].map(norm_invoice)
    req["_item"] = req[req_item_col].map(norm_item)
    req["_amt_req"] = req[req_amt_col].map(to_number)

    calc = calc_df.copy()
    calc["_inv"]  = calc[calc_inv_col].map(norm_invoice)
    calc["_item"] = calc[calc_item_col].map(norm_item)
    calc["_amt_calc"] = calc[calc_amt_col].map(to_number)

    # --- INNER MERGE (matched) ---
    matched = pd.merge(
        req, calc,
        on=["_inv","_item"],
        how="inner",
        suffixes=("_req","_calc")
    )

    if matched.empty:
        st.warning("No matches found on Invoice + Item. Check headers or normalization.")
    else:
        matched["diff"] = matched["_amt_req"] - matched["_amt_calc"]
        matched["match_status"] = matched["diff"].abs() <= tol

        # Nice presentation slices per your spec
        req_slice = matched[[req_inv_col, req_item_col] +
                            list(req.columns[list(req.columns).index(req_inv_col)+1 : list(req.columns).index(req_amt_col)+1])].copy()
        calc_slice = matched[[calc_inv_col, calc_item_col] +
                             list(calc.columns[list(calc.columns).index(calc_inv_col)+1 : list(calc.columns).index(calc_amt_col)+1])].copy()

        # Results sections
        st.subheader("✅ Exact/Within Tolerance Matches")
        exact = matched[matched["match_status"]].copy()
        if exact.empty:
            st.info("No amounts matched within tolerance.")
        else:
            show_cols = [
                req_inv_col, req_item_col,
                req_amt_col, calc_amt_col, "diff"
            ]
            nice = exact.rename(columns={
                req_amt_col: "Request_Amount",
                calc_amt_col: "Calculated_Amount"
            })[show_cols].sort_values([req_inv_col, req_item_col])
            st.dataframe(nice, use_container_width=True)
            download_csv(nice, "matched_equal.csv", "⬇️ Download matched (equal)")

        st.subheader("⚠️ Discrepancies (Amounts differ beyond tolerance)")
        bad = matched[~matched["match_status"]].copy()
        if bad.empty:
            st.info("No discrepancies found.")
        else:
            show_cols = [
                req_inv_col, req_item_col,
                req_amt_col, calc_amt_col, "diff"
            ]
            issues = bad.rename(columns={
                req_amt_col: "Request_Amount",
                calc_amt_col: "Calculated_Amount"
            })[show_cols].sort_values([req_inv_col, req_item_col])
            st.dataframe(issues, use_container_width=True)
            download_csv(issues, "discrepancies.csv", "⬇️ Download discrepancies")

    # --- UNMATCHED on either side ---
    req_keys  = req[["_inv","_item"]].drop_duplicates()
    calc_keys = calc[["_inv","_item"]].drop_duplicates()

    only_req_keys  = pd.merge(req_keys,  calc_keys, on=["_inv","_item"], how="left", indicator=True)
    only_req_keys  = only_req_keys[only_req_keys["_merge"]=="left_only"].drop(columns=["_merge"])

    only_calc_keys = pd.merge(calc_keys, req_keys,   on=["_inv","_item"], how="left", indicator=True)
    only_calc_keys = only_calc_keys[only_calc_keys["_merge"]=="left_only"].drop(columns=["_merge"])

    st.subheader("🧩 Unmatched in Requestor (no calculator row)")
    if only_req_keys.empty:
        st.info("None 🎉")
    else:
        unmatched_req = pd.merge(only_req_keys, req, on=["_inv","_item"], how="left")
        show = unmatched_req[[req_inv_col, req_item_col, req_amt_col]].drop_duplicates()
        st.dataframe(show.sort_values([req_inv_col, req_item_col]), use_container_width=True)
        download_csv(show, "unmatched_in_requestor.csv", "⬇️ Download unmatched (requestor)")

    st.subheader("🧩 Unmatched in Calculator (no requestor row)")
    if only_calc_keys.empty:
        st.info("None 🎉")
    else:
        unmatched_calc = pd.merge(only_calc_keys, calc, on=["_inv","_item"], how="left")
        show = unmatched_calc[[calc_inv_col, calc_item_col, calc_amt_col]].drop_duplicates()
        st.dataframe(show.sort_values([calc_inv_col, calc_item_col]), use_container_width=True)
        download_csv(show, "unmatched_in_calculator.csv", "⬇️ Download unmatched (calculator)")

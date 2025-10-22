# app.py
import io, re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Credit Comparison", layout="wide")
st.title("🧮 Credit Comparison — Requestor vs Updated Calculator (Exact Match, Normalized Currency)")

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
    """
    Parse money-like strings:
      $1,357.44 -> 1357.44
      (123.45)  -> -123.45
      '  11 '   -> 11.0
    Anything unparsable -> 0.0
    """
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    s = str(x).strip()
    if s == "": return 0.0
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    # Some spreadsheets export unicode minus
    s = s.replace("−", "-")
    try:
        val = float(s)
    except Exception:
        return 0.0
    return -val if neg else val

def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())

def fuzzy_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    want_set = {norm_name(c) for c in candidates}
    for c in df.columns:
        if norm_name(c) in want_set:
            return c
    for c in df.columns:
        n = norm_name(c)
        if any(w in n for w in want_set):
            return c
    return None

def read_any_excel(uploaded) -> pd.DataFrame | None:
    if uploaded is None:
        return None
    name = getattr(uploaded, "name", "file")
    if name.lower().endswith(".csv"):
        return pd.read_csv(uploaded)
    try:
        xls = pd.ExcelFile(uploaded)
        sheet = st.selectbox(
            f"Select sheet for **{name}**",
            xls.sheet_names,
            index=0,
            key=f"sheet_{name}",
        )
        return pd.read_excel(xls, sheet_name=sheet)
    except Exception as e:
        st.error(f"Could not read {name}: {e}")
        return None

def download_csv(df: pd.DataFrame, filename: str, label: str):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(label, data=buf.getvalue(), file_name=filename, mime="text/csv")

def money(x) -> str:
    """
    Safe currency formatter:
    - accepts float/int/decimal/strings like '$1,234.56' or '1,234.56'
    - handles NaN/None
    - falls back to plain str(x) if it truly can't be parsed
    """
    try:
        # pandas NA-safe check
        if pd.isna(x):
            return "$0.00"
    except Exception:
        pass

    # already numeric?
    if isinstance(x, (int, float)):
        return f"${float(x):,.2f}"

    # try parsing string-y values
    try:
        s = str(x).strip().replace("$", "").replace(",", "").replace("−", "-")
        if s.startswith("(") and s.endswith(")"):
            s = f"-{s[1:-1]}"
        val = float(s)
        return f"${val:,.2f}"
    except Exception:
        # last resort: just return the original value as string
        return str(x)

# ---------------- inputs ----------------
c1, c2 = st.columns(2)
with c1:
    req_file = st.file_uploader("📥 Requestor file (Pricing Credits.xlsx / Template)", type=["xlsx","xls","csv"])
with c2:
    calc_file = st.file_uploader("📥 Updated Credits Calculator file", type=["xlsx","xls","csv"])

with st.expander("⚙️ Column mapping (auto-detected; edit if needed)"):
    st.caption("We try to detect common header variants. Adjust if needed.")
    req_inv_label  = st.text_input("Requestor: Invoice column", value="Invoice Number")
    req_item_label = st.text_input("Requestor: Item column", value="Item Number")
    req_amt_label  = st.text_input("Requestor: Credit amount column", value="Credit Request Total")

    calc_inv_label  = st.text_input("Calculator: Invoice column", value="Invoice_No")
    calc_item_label = st.text_input("Calculator: Item column", value="Item_No")
    calc_amt_label  = st.text_input("Calculator: Credit amount column", value="Credit_AM")

st.markdown("")

# ---------------- run ----------------
if st.button("🔎 Compare"):
    if not req_file or not calc_file:
        st.warning("Upload both files to run the comparison.")
        st.stop()

    req_df  = read_any_excel(req_file)
    calc_df = read_any_excel(calc_file)
    if req_df is None or calc_df is None:
        st.stop()

    # Detect columns
    req_inv_col  = fuzzy_col(req_df,  [req_inv_label, "Invoice Number", "Invoice_Number", "InvoiceNo", "Invoice"])
    req_item_col = fuzzy_col(req_df,  [req_item_label, "Item Number", "Item_Number", "ItemNo", "Item_No", "Item"])
    req_amt_col  = fuzzy_col(req_df,  [req_amt_label, "Credit Request Total", "Credit_Total", "Credit Amount", "Amount", "Total"])

    calc_inv_col  = fuzzy_col(calc_df, [calc_inv_label, "Invoice_No", "Invoice Number", "Invoice_Number", "InvoiceNo", "Invoice"])
    calc_item_col = fuzzy_col(calc_df, [calc_item_label, "Item_No", "Item Number", "Item_Number", "ItemNo", "Item"])
    calc_amt_col  = fuzzy_col(calc_df, [calc_amt_label, "Credit_AM", "Credit AMT", "Credit Amt", "Credit Amount", "CreditAmount", "Credit"])

    missing = [name for name, col in [
        ("Requestor: Invoice",   req_inv_col),
        ("Requestor: Item",      req_item_col),
        ("Requestor: Amount",    req_amt_col),
        ("Calculator: Invoice",  calc_inv_col),
        ("Calculator: Item",     calc_item_col),
        ("Calculator: Amount",   calc_amt_col),
    ] if col is None]

    if missing:
        st.error("Could not find columns: " + ", ".join(missing))
        st.caption("Tip: pick the right sheet above, or edit the mapping names in the expander.")
        st.stop()

    # Normalize & prep keys + round to cents
    req = req_df.copy()
    req["_inv"]      = req[req_inv_col].map(norm_invoice)
    req["_item"]     = req[req_item_col].map(norm_item)
    req["_amt_req"]  = req[req_amt_col].map(to_number).round(2)

    calc = calc_df.copy()
    calc["_inv"]      = calc[calc_inv_col].map(norm_invoice)
    calc["_item"]     = calc[calc_item_col].map(norm_item)
    calc["_amt_calc"] = calc[calc_amt_col].map(to_number).round(2)

    # Totals for KPI
    req_total_amt   = float(req["_amt_req"].sum())
    calc_total_amt  = float(calc["_amt_calc"].sum())

    # Merge and compare (exact equality on 2 decimals)
    matched = pd.merge(
        req, calc,
        on=["_inv","_item"],
        how="inner",
        suffixes=("_req","_calc")
    )
    matched["diff"] = (matched["_amt_req"] - matched["_amt_calc"]).round(2)
    matched["match_status"] = matched["diff"] == 0.00

    exact = matched[matched["match_status"]].copy()
    bad   = matched[~matched["match_status"]].copy()

    # Unmatched on either side
    req_keys  = req[["_inv","_item"]].drop_duplicates()
    calc_keys = calc[["_inv","_item"]].drop_duplicates()
    only_req  = pd.merge(req_keys,  calc_keys, on=["_inv","_item"], how="left", indicator=True)
    only_req  = only_req[only_req["_merge"]=="left_only"].drop(columns=["_merge"])
    only_calc = pd.merge(calc_keys, req_keys,   on=["_inv","_item"], how="left", indicator=True)
    only_calc = only_calc[only_calc["_merge"]=="left_only"].drop(columns=["_merge"])

    unmatched_req_count  = int(len(only_req))
    unmatched_calc_count = int(len(only_calc))
    matched_count        = int(len(matched))
    discrep_count        = int(len(bad))
    matched_amt_sum      = float(exact["_amt_req"].sum())
    discrep_amt_abs      = float(bad["diff"].abs().sum())
    net_diff_matched     = float(matched["_amt_req"].sum() - matched["_amt_calc"].sum())

    # KPIs
    a,b,c,d,e,f = st.columns(6)
    a.metric("✅ Matched pairs", matched_count)
    b.metric("⚠️ Discrepancies", discrep_count)
    c.metric("🧩 Unmatched in Requestor", unmatched_req_count)
    d.metric("🧩 Unmatched in Calculator", unmatched_calc_count)
    e.metric("Σ Request $",  money(req_total_amt))
    f.metric("Σ Calculator $", money(calc_total_amt))
    st.caption(f"Matched $ (exact on 2 decimals): **{money(matched_amt_sum)}** · "
               f"|diff| on matched: **{money(discrep_amt_abs)}** · "
               f"Net diff (Req − Calc): **{money(net_diff_matched)}**")
    st.markdown("---")

    # Resolve post-merge column names (with suffixes)
    req_amt_m   = f"{req_amt_col}_req"   if f"{req_amt_col}_req"   in matched.columns else req_amt_col
    calc_amt_m  = f"{calc_amt_col}_calc" if f"{calc_amt_col}_calc" in matched.columns else calc_amt_col
    inv_req_m   = f"{req_inv_col}_req"
    inv_calc_m  = f"{calc_inv_col}_calc"
    item_req_m  = f"{req_item_col}_req"
    item_calc_m = f"{calc_item_col}_calc"
    inv_show  = inv_req_m  if inv_req_m  in matched.columns else (inv_calc_m  if inv_calc_m  in matched.columns else req_inv_col)
    item_show = item_req_m if item_req_m in matched.columns else (item_calc_m if item_calc_m in matched.columns else req_item_col)

    def pretty_table(df_numeric: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Returns (display_df, csv_df).
        Display is formatted as currency; CSV keeps numbers.
        """
        keep = [c for c in [inv_show, item_show, req_amt_m, calc_amt_m, "diff"] if c in df_numeric.columns]
        csv_df = df_numeric[keep].rename(columns={
            inv_show:  "Invoice",
            item_show: "Item",
            req_amt_m: "Request_Amount",
            calc_amt_m:"Calculated_Amount",
            "diff":    "diff"
        })
        # Display: currency strings
        disp = csv_df.copy()
        if "Request_Amount"   in disp.columns: disp["Request_Amount"]   = disp["Request_Amount"].map(money)
        if "Calculated_Amount" in disp.columns: disp["Calculated_Amount"] = disp["Calculated_Amount"].map(money)
        if "diff" in disp.columns: disp["diff"] = disp["diff"].map(money)
        sort_cols = [c for c in ["Invoice", "Item"] if c in csv_df.columns]
        if sort_cols:
            csv_df = csv_df.sort_values(sort_cols, kind="stable")
            disp   = disp.sort_values(sort_cols, kind="stable")
        return disp, csv_df

    # Exact Matches
    st.subheader("✅ Exact Matches")
    if exact.empty:
        st.info("No exact amount matches.")
    else:
        disp, csv_df = pretty_table(exact)
        st.dataframe(disp, use_container_width=True)
        download_csv(csv_df, "matched_exact.csv", "⬇️ Download matched (exact)")

    # Discrepancies
    st.subheader("⚠️ Discrepancies (Amounts differ)")
    if bad.empty:
        st.info("No discrepancies found.")
    else:
        disp, csv_df = pretty_table(bad)
        st.dataframe(disp, use_container_width=True)
        download_csv(csv_df, "discrepancies.csv", "⬇️ Download discrepancies")

    # Unmatched tables (display currency for amounts, too)
    st.subheader("🧩 Unmatched in Requestor (no calculator row)")
    if only_req.empty:
        st.info("None 🎉")
    else:
        unmatched_req = pd.merge(only_req, req, on=["_inv","_item"], how="left")
        show = unmatched_req[[req_inv_col, req_item_col, req_amt_col]].drop_duplicates()
        show = show.rename(columns={req_inv_col: "Invoice", req_item_col: "Item", req_amt_col: "Request_Amount"})
        show_csv = show.copy()
        show_disp = show.copy()
        show_disp["Request_Amount"] = show_disp["Request_Amount"].map(to_number).round(2).map(money)
        st.dataframe(show_disp.sort_values(["Invoice", "Item"]), use_container_width=True)
        download_csv(show_csv.sort_values(["Invoice", "Item"]), "unmatched_in_requestor.csv", "⬇️ Download unmatched (requestor)")

    st.subheader("🧩 Unmatched in Calculator (no requestor row)")
    if only_calc.empty:
        st.info("None 🎉")
    else:
        unmatched_calc = pd.merge(only_calc, calc, on=["_inv","_item"], how="left")
        show = unmatched_calc[[calc_inv_col, calc_item_col, calc_amt_col]].drop_duplicates()
        show = show.rename(columns={calc_inv_col: "Invoice", calc_item_col: "Item", calc_amt_col: "Calculated_Amount"})
        show_csv = show.copy()
        show_disp = show.copy()
        show_disp["Calculated_Amount"] = show_disp["Calculated_Amount"].map(to_number).round(2).map(money)
        st.dataframe(show_disp.sort_values(["Invoice", "Item"]), use_container_width=True)
        download_csv(show_csv.sort_values(["Invoice", "Item"]), "unmatched_in_calculator.csv", "⬇️ Download unmatched (calculator)")

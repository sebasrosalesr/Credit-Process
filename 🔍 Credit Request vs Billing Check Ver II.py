import streamlit as st
import pandas as pd
import json
import os

# Optional: only import firebase if we'll use it
import firebase_admin
from firebase_admin import credentials, db

# ------------------------------
# Page & Header
# ------------------------------
st.set_page_config(page_title="Credit Request vs Billing Check", layout="wide")
st.title("🔍 Credit Request vs Billing Check")
st.header("Step 1: Upload Files")

# --- Firebase Initialization ---
import firebase_admin
from firebase_admin import credentials, db

# Load Firebase credentials from Streamlit secrets
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

# Firebase reference for credit_requests
ref = db.reference('credit_requests')

# Build lookup of Customer Number → EDI Service Provider
@st.cache_data(show_spinner=False)
def get_edi_lookup() -> dict:
    data = ref.get() or {}
    lookup = {}
    for _, rec in data.items():
        cust = str(rec.get("Customer Number", "")).strip().upper()
        edi = str(rec.get("EDI Service Provider", "")).strip()
        if cust and edi:
            lookup[cust] = edi
    return lookup

edi_lookup = get_edi_lookup()
st.success(f"✅ Firebase connected — {len(edi_lookup)} EDI records loaded.")

# ------------------------------
# Helpers
# ------------------------------
def normalize_id_series(s: pd.Series) -> pd.Series:
    """
    Normalize invoice/item IDs coming from Excel:
    - Cast to string
    - Strip spaces
    - Remove trailing '.0' (common when numbers get parsed as floats)
    """
    return (
        s.astype(str)
         .str.strip()
         .str.replace(r"\.0$", "", regex=True)
    )

def _norm(s: str) -> str:
    return str(s).strip().upper() if pd.notna(s) else ""

def remap_columns(df: pd.DataFrame, candidates: dict) -> pd.DataFrame:
    """
    Remap any present candidate names to a canonical column name.
    """
    rename_map = {}
    cols_lower = {c.lower(): c for c in df.columns}  # original -> preserve case
    for target, options in candidates.items():
        found = None
        for opt in options:
            if opt in df.columns:
                found = opt
                break
            if opt.lower() in cols_lower:
                found = cols_lower[opt.lower()]
                break
        if found:
            rename_map[found] = target
    return df.rename(columns=rename_map)

def require_columns(df: pd.DataFrame, needed: list, context_name: str):
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(
            f"❌ Required columns {missing} were not found in {context_name} (after remapping)."
        )

def init_firebase_and_get_lookup(sa_bytes: bytes | None, sa_path: str | None, database_url: str) -> dict:
    """
    Initialize Firebase, fetch credit_requests, and build a Customer Number -> EDI Service Provider lookup.
    Prefers a non-empty EDI value when multiple records share the same Customer Number.
    """
    # Reset app to allow changing URLs/keys during dev session
    try:
        firebase_admin.delete_app(firebase_admin.get_app())
    except ValueError:
        pass

    # Service account from bytes (uploaded) or from path
    if sa_bytes:
        # Save uploaded JSON to a temp file
        tmp_path = "sa_tmp.json"
        with open(tmp_path, "wb") as f:
            f.write(sa_bytes)
        cred = credentials.Certificate(tmp_path)
    elif sa_path and os.path.exists(sa_path):
        cred = credentials.Certificate(sa_path)
    else:
        raise ValueError("No valid service account provided: upload a JSON or set a valid file path.")

    firebase_admin.initialize_app(cred, {"databaseURL": database_url})
    ref = db.reference("credit_requests")
    data = ref.get() or {}

    # Build lookup dict
    lookup = {}
    for _, rec in (data or {}).items():
        cust = _norm(rec.get("Customer Number", ""))
        edi = str(rec.get("EDI Service Provider", "")).strip()
        if not cust:
            continue
        # Prefer to keep an existing non-empty EDI; fill missing if not present
        if edi:
            if cust not in lookup or not lookup[cust]:
                lookup[cust] = edi
        else:
            lookup.setdefault(cust, "")
    return lookup

# ------------------------------
# Uploaders
# ------------------------------
st.subheader("📤 Upload Credit Request Template")
credit_file = st.file_uploader(
    "Drag and drop the Credit Form Excel here",
    type=["xlsx", "xlsm", "xls"],
    key="credit",
)

st.subheader("📥 Upload Billing Master Excel")
billing_file = st.file_uploader(
    "Drag and drop the Billing Master Excel here",
    type=["xlsx", "xlsm", "xls"],
    key="billing",
)

# ------------------------------
# Processing
# ------------------------------
if credit_file and billing_file:
    try:
        # Load Excels
        df_credit_raw = pd.read_excel(credit_file, engine="openpyxl")
        df_billing_raw = pd.read_excel(billing_file, engine="openpyxl")

        # Column remapping (robust to variants)
        credit_candidates = {
            "Invoice Number": ["Invoice Number", "Doc No", "Document No", "Invoice", "INV No", "INV_NO"],
            "Item Number":    ["Item Number", "Item No.", "Item No", "Item ID", "Item", "ITEM_NO"],
            "Customer Number":["Customer Number", "Customer", "Cust No", "Cust #", "Customer ID", "Customer_ID"],
            # Optional common fields
            "QTY":            ["QTY", "Quantity"],
            "Unit Price":     ["Unit Price", "Price", "UnitPrice"],
            "Extended Price": ["Extended Price", "ExtendedPrice", "Ext Price"],
            "Corrected Unit Price": ["Corrected Unit Price", "Corrected Price", "New Unit Price"],
            "Credit Request Total": ["Credit Request Total", "Credit Total", "Credit Amount"],
            "Requested By":   ["Requested By", "Requester", "User"],
            "Reason for Credit": ["Reason for Credit", "Reason"],
        }
        billing_candidates = {
            "Invoice Number": ["Invoice Number", "Doc No", "Document No", "Invoice", "INV No", "INV_NO"],
            "Item Number":    ["Item Number", "Item No.", "Item No", "Item ID", "Item", "ITEM_NO"],
            "RTN/CR No.":     ["RTN/CR No.", "RTN_CR_No", "RTN CR No", "Return/Credit No", "RTN_CR_No."],
            "Customer Number":["Customer Number", "Customer", "Cust No", "Cust #", "Customer ID", "Customer_ID"],
        }

        df_credit = remap_columns(df_credit_raw.copy(), credit_candidates)
        df_billing = remap_columns(df_billing_raw.copy(), billing_candidates)

        # Validate required join keys
        require_columns(df_credit, ["Invoice Number", "Item Number"], "Credit Request Template")
        require_columns(df_billing, ["Invoice Number", "Item Number"], "Billing Master")

        # Drop NA keys and normalize key values
        df_credit = df_credit.dropna(subset=["Invoice Number", "Item Number"]).copy()
        df_billing = df_billing.dropna(subset=["Invoice Number", "Item Number"]).copy()

        for df_ in (df_credit, df_billing):
            df_["Invoice Number"] = normalize_id_series(df_["Invoice Number"])
            df_["Item Number"] = normalize_id_series(df_["Item Number"])

        # Optional de-dup in billing on (Invoice, Item) keeping first
        df_billing = (
            df_billing
            .sort_index()  # stable
            .drop_duplicates(subset=["Invoice Number", "Item Number"], keep="first")
        )

        # Find matches by (Invoice Number, Item Number)
        left_keys = set(zip(df_credit["Invoice Number"], df_credit["Item Number"]))
        right_keys = set(zip(df_billing["Invoice Number"], df_billing["Item Number"]))
        common_pairs = left_keys & right_keys

        df_matches = (
            df_credit[df_credit[["Invoice Number", "Item Number"]].apply(tuple, axis=1).isin(common_pairs)]
            .copy()
        )

        # Bring in RTN/CR No. from billing (if present)
        has_rtn = "RTN/CR No." in df_billing.columns
        merge_cols = ["Invoice Number", "Item Number"] + (["RTN/CR No."] if has_rtn else [])
        df_matches = df_matches.merge(
            df_billing[merge_cols + (["Customer Number"] if "Customer Number" in df_billing.columns else [])],
            on=["Invoice Number", "Item Number"],
            how="left",
            validate="m:1"
        )

        # If Customer Number exists in credit but not billing, prefer credit
        if "Customer Number" in df_credit.columns:
            df_matches["Customer Number"] = df_matches["Customer Number"].fillna(df_credit["Customer Number"])

        # ------------------------------
        # EDI enrichment from Firebase
        # ------------------------------
        if use_firebase:
            try:
                sa_bytes = uploaded_sa.read() if uploaded_sa else None
                sa_path = SERVICE_ACCOUNT_PATH if SERVICE_ACCOUNT_PATH.strip() else None
                edi_lookup = init_firebase_and_get_lookup(sa_bytes, sa_path, db_url)

                # Use normalized Customer Number for lookup
                if "Customer Number" in df_matches.columns:
                    cust_norm = df_matches["Customer Number"].astype(str).map(_norm)
                    df_matches["EDI Service Provider"] = cust_norm.map(lambda x: edi_lookup.get(x, ""))
                    df_matches["Has EDI?"] = df_matches["EDI Service Provider"].astype(str).str.len().gt(0)
                else:
                    st.warning("⚠️ No 'Customer Number' column found after remapping; cannot enrich EDI.")
            except Exception as e:
                st.warning(f"⚠️ Skipping EDI enrichment due to Firebase error: {e}")

        # Nice column order (show the keys early + RTN + EDI)
        preferred_order = [
            "Customer Number",
            "Invoice Number",
            "Item Number",
            "QTY",
            "Unit Price",
            "Extended Price",
            "Corrected Unit Price",
            "Credit Request Total",
            "Requested By",
            "Reason for Credit",
            "RTN/CR No.",            # from billing (if present)
            "EDI Service Provider",  # from Firebase (if enabled)
            "Has EDI?",
        ]
        ordered_cols = [c for c in preferred_order if c in df_matches.columns]
        remaining_cols = [c for c in df_matches.columns if c not in ordered_cols]
        df_matches = df_matches[ordered_cols + remaining_cols]

        # Display
        st.success(f"✅ Found {len(df_matches)} matching records.")
        st.dataframe(df_matches, use_container_width=True)

        # Download
        csv = df_matches.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Matches as CSV", csv, "matched_records.csv", "text/csv")

        # Small heads-up if RTN missing
        if not has_rtn:
            st.warning("⚠️ Column 'RTN/CR No.' was not found in the Billing Master file. "
                       "If the column uses a different name, add it to the `billing_candidates` list.")

    except Exception as e:
        st.error(f"❌ Error processing files: {e}")

else:
    st.info("⬆️ Please upload both files to begin.")

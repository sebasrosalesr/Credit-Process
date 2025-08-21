from datetime import date
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import requests

# =========================================================
# App
# =========================================================
st.set_page_config(page_title="🚨 Aging Credits Alert (No CR)", layout="wide")
st.title("🚨 Aging Credits Alert (No CR)")
st.caption("Find tickets with empty RTN_CR_No and high aging, then alert Billing.")

EXPECTED_COLUMNS = [
    "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
    "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
    "Reason for Credit", "Record ID", "Requested By", "Sales Rep", "Status",
    "Ticket Number", "Unit Price", "Type", "RTN_CR_No"
]

# ---------------- Firebase init ----------------
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
    })
ref = db.reference("credit_requests")

# ---------------- Helpers ----------------
def to_date(x):
    return pd.to_datetime(str(x), errors="coerce")

@st.cache_data(ttl=180)
def load_df() -> pd.DataFrame:
    data = ref.get() or {}
    rows = []
    for k, item in (data.items() if isinstance(data, dict) else []):
        rec = {c: item.get(c) for c in EXPECTED_COLUMNS}
        rec["Record ID"] = k
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Date_parsed"] = df["Date"].apply(to_date)
    df = df.dropna(subset=["Date_parsed"]).copy()
    today = pd.Timestamp(date.today())
    df["Age (days)"] = (today - df["Date_parsed"]).dt.days
    df["Has CR No"] = df["RTN_CR_No"].fillna("").astype(str).str.strip().ne("")
    return df

def compose_email_html(rows: pd.DataFrame, threshold: int) -> str:
    # Build a compact HTML table for the email
    cols = ["Age (days)", "Date_parsed", "Ticket Number", "Invoice Number", "Item Number", "Requested By", "Sales Rep", "Status"]
    cols = [c for c in cols if c in rows.columns]
    head = f"<h2>Aging Credits Alert (No CR) — Age ≥ {threshold} days</h2>"
    sub = f"<p>Total pending: <b>{len(rows)}</b>. Please review with Billing.</p>"
    table = rows[cols].rename(columns={"Date_parsed": "Date"}).to_html(index=False, border=0)
    return head + sub + table

def send_email_smtp(subject: str, html_body: str, recipients: list[str]) -> str:
    """
    Uses SMTP creds from st.secrets['email']:
    host, port, username, password, from_addr
    """
    cfg = st.secrets.get("email", {})
    host = cfg.get("host"); port = int(cfg.get("port", 587))
    user = cfg.get("username"); pwd = cfg.get("password"); from_addr = cfg.get("from_addr", user)

    if not all([host, port, user, pwd, from_addr, recipients]):
        return "❌ Missing email SMTP settings in st.secrets['email'] or no recipients."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, pwd)
            s.sendmail(from_addr, recipients, msg.as_string())
        return "✅ Email sent."
    except Exception as e:
        return f"❌ Email failed: {e}"

def send_slack(webhook_url: str, text: str) -> str:
    if not webhook_url:
        return "❌ Missing Slack webhook_url."
    try:
        r = requests.post(webhook_url, json={"text": text}, timeout=10)
        r.raise_for_status()
        return "✅ Slack sent."
    except Exception as e:
        return f"❌ Slack failed: {e}"

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Filters & Alert Settings")
    threshold = st.number_input("Alert threshold (Age ≥ days)", min_value=1, value=44, step=1)
    start_date = st.date_input("Start Date (optional)", value=None)
    end_date   = st.date_input("End Date (optional)", value=None)

    st.markdown("---")
    st.subheader("Recipients")
    billing_email = st.text_input("Billing email(s), comma-separated", value=st.secrets.get("defaults", {}).get("billing_email_list", ""))
    slack_webhook = st.text_input("Slack Webhook URL (optional)", value=st.secrets.get("slack", {}).get("webhook_url", ""))

    if st.button("🔄 Refresh data cache"):
        st.cache_data.clear()

# ---------------- Load & filter ----------------
with st.spinner("Loading…"):
    df = load_df()

if df.empty:
    st.info("No data found in Firebase path `credit_requests`.")
    st.stop()

mask = (~df["Has CR No"]) & (df["Age (days)"] >= threshold)
if start_date: mask &= df["Date_parsed"] >= pd.Timestamp(start_date)
if end_date:   mask &= df["Date_parsed"] <= pd.Timestamp(end_date)
pending = df[mask].copy().sort_values(["Age (days)", "Date_parsed"], ascending=[False, True])

# ---------------- Summary ----------------
c1, c2, c3 = st.columns(3)
with c1: st.metric("Total rows (dated)", f"{len(df):,}")
with c2: st.metric("Pending (no CR, ≥ threshold)", f"{len(pending):,}")
with c3: st.metric("Max age (days in pending)", int(pending["Age (days)"].max()) if len(pending) else 0)

st.markdown("---")
st.subheader(f"⏳ Pending (No CR) — Age ≥ {threshold} days  ({len(pending):,})")

if len(pending):
    view_cols = [c for c in [
        "Age (days)", "Date_parsed", "Ticket Number", "Invoice Number", "Item Number",
        "Requested By", "Sales Rep", "Status", "Record ID"
    ] if c in pending.columns]
    st.dataframe(pending[view_cols].rename(columns={"Date_parsed": "Date"}), use_container_width=True)

    # Download CSV
    csv_buf = io.StringIO()
    pending[view_cols].rename(columns={"Date_parsed": "Date"}).to_csv(csv_buf, index=False)
    st.download_button("⬇️ Download Pending (CSV)", data=csv_buf.getvalue(),
                       file_name="pending_no_cr.csv", mime="text/csv")

    # --------- Send Alerts ----------
    st.markdown("### Send Alert")
    subject = f"[Billing] Aging Credits (No CR) — {len(pending)} pending, Age ≥ {threshold} days"
    html_body = compose_email_html(pending, threshold)

    colA, colB = st.columns(2)
    with colA:
        if st.button("📧 Send Email to Billing"):
            recipients = [e.strip() for e in billing_email.split(",") if e.strip()]
            result = send_email_smtp(subject, html_body, recipients)
            st.info(result)

    with colB:
        if st.button("💬 Send Slack Message"):
            # Compact Slack text (first 10 tickets preview)
            preview = pending.head(10)
            lines = [
                f"🚨 *Aging Credits (No CR)* — Age ≥ {threshold} days",
                f"*Total pending:* {len(pending)}",
                "```" +
                preview[["Age (days)", "Ticket Number", "Invoice Number"]].to_string(index=False) +
                ("```" if len(preview) else "```")
            ]
            result = send_slack(slack_webhook, "\n".join(lines))
            st.info(result)

else:
    st.success("No tickets meet the alert condition. 🎉")

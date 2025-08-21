# =========================
# Pending CR vs Has CR views
# =========================

def _has_cr(series):
    return series.fillna("").astype(str).str.strip().ne("")

# Flag rows with/without CR number
df_view["Has CR No"] = _has_cr(df_view.get("RTN_CR_No", pd.Series(index=df_view.index)))

# ---- 1) Pending CR number (needs follow-up)
pending = df_view[~df_view["Has CR No"]].copy()
pending["Action"] = "Pending CR number — please follow up"
pending_cols = [c for c in [
    "Age (days)", "Aging Bucket", "Date_parsed",
    "Ticket Number", "Invoice Number", "Item Number",
    "Requested By", "Sales Rep", "Status", "Record ID", "Action"
] if c in pending.columns]
pending = pending.sort_values(["Age (days)", "Date_parsed"], ascending=[False, True])

# ---- 2) Has CR number (check status / closed?)
with_cr = df_view[df_view["Has CR No"]].copy()
closed_labels = {"closed", "resolved", "completed", "done"}  # customize to your system
with_cr["Is Closed"] = with_cr["Status"].fillna("").str.lower().isin(closed_labels)
with_cr["Action"] = with_cr["Is Closed"].map({True: "Closed ✅", False: "Has CR — check status"})
with_cr_cols = [c for c in [
    "Age (days)", "Aging Bucket", "Date_parsed",
    "Ticket Number", "Invoice Number", "Item Number",
    "RTN_CR_No", "Status", "Requested By", "Sales Rep", "Record ID", "Action"
] if c in with_cr.columns]
with_cr = with_cr.sort_values(["Is Closed", "Age (days)"], ascending=[True, False])

# =========================
# Display sections
# =========================
st.markdown("---")
st.subheader(f"🚩 Pending CR Number — Follow Up ({len(pending):,})")
if len(pending):
    st.dataframe(pending[pending_cols].rename(columns={"Date_parsed": "Date"}), use_container_width=True)
    csv_buf = io.StringIO()
    pending[pending_cols].rename(columns={"Date_parsed": "Date"}).to_csv(csv_buf, index=False)
    st.download_button("⬇️ Download Pending List (CSV)", data=csv_buf.getvalue(),
                       file_name=f"pending_cr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                       mime="text/csv")
else:
    st.info("All dated tickets have a CR number. 🎉")

st.subheader(f"📘 Has CR Number — Status Check ({len(with_cr):,})")
if len(with_cr):
    # Optional: money formatting if present
    if "Credit Request Total" in with_cr.columns:
        with_cr["Credit Request Total"] = format_money_series(with_cr["Credit Request Total"])
        if "Credit Request Total" not in with_cr_cols:
            with_cr_cols.insert(6, "Credit Request Total")

    st.dataframe(with_cr[with_cr_cols].rename(columns={"Date_parsed": "Date"}), use_container_width=True)
    csv_buf2 = io.StringIO()
    with_cr[with_cr_cols].rename(columns={"Date_parsed": "Date"}).to_csv(csv_buf2, index=False)
    st.download_button("⬇️ Download Has-CR List (CSV)", data=csv_buf2.getvalue(),
                       file_name=f"has_cr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                       mime="text/csv")
else:
    st.info("No records with CR number in the current filter.")


import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

# Initialize Firebase (only once)
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_key.json")  # Ensure this file is in the same folder
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

st.title("📄 Credit Request Dashboard")

# --- Submit New Credit Request ---
st.header("➕ Submit a New Credit Request")

with st.form("credit_form"):
    ticket_number = st.text_input("Ticket Number")
    description = st.text_area("Description")
    credit_total = st.number_input("Credit Total ($)", step=0.01)

    submitted = st.form_submit_button("Submit")

    if submitted:
        if ticket_number and description:
            ref.push({
                "ticket_number": ticket_number,
                "description": description,
                "credit_total": float(credit_total)
            })
            st.success("✅ Entry submitted to Firebase!")
        else:
            st.error("⚠️ Please fill out all fields before submitting.")

# --- Display Current Records ---
st.header("📊 Existing Credit Requests")

data = ref.get()
if data:
    df = pd.DataFrame.from_dict(data, orient='index')
    df.index.name = "Firebase ID"
    st.dataframe(df)

    # Download as CSV
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download as CSV", data=csv, file_name='credit_requests.csv', mime='text/csv')
else:
    st.info("No credit requests submitted yet.")

import streamlit as st

# --- Basic password check ---
def check_password():
    """Returns True if the correct password is entered, else stops the app."""
    if "auth_ok" in st.session_state and st.session_state.auth_ok:
        return True

    st.title("🔒 Private Test App")
    password = st.text_input("Enter password:", type="password")

    if st.button("Login"):
        if password == "test123":  # <-- change this to your password
            st.session_state.auth_ok = True
            st.experimental_rerun()
        else:
            st.error("❌ Incorrect password")
            st.stop()

    st.stop()

# Run check
if not check_password():
    st.stop()

# --- Your private app starts here ---
st.success("✅ Welcome to the private area!")
st.write("This is your test app without Firebase.")
st.write("You can add your dashboard, charts, or database logic here.")

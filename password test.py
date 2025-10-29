import streamlit as st

# --- Config: set your password here (or better: use st.secrets) ---
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")  # set in Streamlit Secrets for prod

def check_password():
    """Return True if the correct password is entered; otherwise render login and stop."""
    if st.session_state.get("auth_ok"):
        return True

    st.title("🔒 Private Test App")

    pwd = st.text_input("Enter password:", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.auth_ok = True
            st.rerun()  # <-- updated API
        else:
            st.error("❌ Incorrect password")
            st.stop()

    st.stop()

# Gate the app
if not check_password():
    st.stop()

# ---- Private area below ----
st.success("✅ Welcome to the private area!")
st.write("This is your test app without Firebase.")

# Optional: logout
if st.button("Logout"):
    st.session_state.auth_ok = False
    st.rerun()

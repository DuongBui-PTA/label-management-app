# pages/3_📝_User_Guide.py

import streamlit as st
from utils.auth import AuthManager

# Authentication check
auth_manager = AuthManager()
if not auth_manager.require_auth():
    st.stop()
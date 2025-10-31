import streamlit as st
from utils.auth import AuthManager
from utils.config import config
import logging
from datetime import datetime
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="ProsTech Label Management System",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="expanded"
)

auth = AuthManager()

def show_login_form():
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:

        st.markdown('<h1 class="main-header">🏷️ Label Management System</h1>', unsafe_allow_html=True)

        with st.form("login_form"):
            st.subheader("🔐 Login")
            
            username = st.text_input(
                "Username",
                placeholder="Enter your username",
                help="Use your company username"
            )
            
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                submit = st.form_submit_button(
                    "🔐 Login",
                    type="primary",
                    width='stretch'
                )
            with col2:
                st.form_submit_button(
                    "❓ Forgot Password?",
                    width='stretch',
                    disabled=True,
                    help="Contact IT support for password reset"
                )
            
            if submit:
                if username and password:

                    success, result = auth.authenticate(username, password)
                    
                    if success:
                        auth.login(result)
                        # st.success("✅ Login successful!")
                        st.rerun()
                    else:
                        error_msg = result.get("error", "Authentication failed")
                        st.error(f"❌ {error_msg}")
                else:
                    st.warning("⚠️ Please enter both username and password")

def main_app():
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        st.markdown(f"### 📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
    with col2:
        st.markdown(f"### 👤 Welcome, **{auth.get_user_display_name()}**")
    
    with col3:
        if st.button("🚪 Logout", width='stretch'):
            auth.logout()
            st.rerun()

    st.markdown("---")

    st.markdown('<h1 class="main-header">🏷️ Label Management System</h1>', unsafe_allow_html=True)
    st.markdown("---")

    st.header("🔧 System Modules")

    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container():
            st.markdown("""
            <div style='padding: 1rem; border: 1px solid #ddd; border-radius: 0.5rem; height: 200px;'>
                <h3>🏷️ Label Requirements</h3>
                <p>The module is used to view details, create new label requests and detailed content for customer label requests</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Open Label Requirements →", key="btn_requirements", width='stretch'):
                st.switch_page("pages/1_🏷️_Customer_Label_Requirement.py")
    
    with col2:
        with st.container():
            st.markdown("""
            <div style='padding: 1rem; border: 1px solid #ddd; border-radius: 0.5rem; height: 200px;'>
                <h3>🎫 Label Management</h3>
                <p>The module is used to create, print labels and view label printing history</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Open Label Management →", key="btn_management", width='stretch'):
                st.switch_page("pages/2_🎫_Label_Management.py")

    with col3:
        with st.container():
            st.markdown("""
            <div style='padding: 1rem; border: 1px solid #ddd; border-radius: 0.5rem; height: 200px;'>
                <h3>📝 User Guide</h3>
                <p>The module is used to guide users in detail how to use each function in the software</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Open User Guide →", key="btn_user_guide", width='stretch'):
                st.switch_page("pages/3_📝_User_Guide.py")

    st.markdown("---")
    st.header("📊 Quick Statistics")
    
    try:
        from utils.db import get_db_engine
        from sqlalchemy import text
        
        engine = get_db_engine()
        
        # Get statistics
        stats_query = text("""
        SELECT 
            COUNT(DISTINCT id) as total_requirements,
            COUNT(DISTINCT customer_id) as total_customers,
            SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END) as active_requirements,
            SUM(CASE WHEN created_date >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) as recent_requirements
        FROM customer_label_requirements
        """)
        
        with engine.connect() as conn:
            stats = conn.execute(stats_query).fetchone()
        
        if stats:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Requirements", int(stats[0] or 0))
            
            with col2:
                st.metric("Total Customers", int(stats[1] or 0))
            
            with col3:
                st.metric("Active Requirements", int(stats[2] or 0))
            
            with col4:
                st.metric("Recent (7 days)", int(stats[3] or 0))
        else:
            st.info("No data available yet. Start by creating your first label requirement!")
            
    except Exception as e:
        st.info("📊 Statistics will be available after creating requirements")
    
    # Recent Activity
    st.markdown("---")
    st.header("⏰ Recent Activity")
    
    try:
        recent_query = text("""
        SELECT 
            requirement_name,
            customer_name,
            created_by,
            created_date,
            status
        FROM customer_label_requirements
        ORDER BY created_date DESC
        LIMIT 5
        """)
        
        with engine.connect() as conn:
            recent_df = pd.read_sql(recent_query, conn)
        
        if not recent_df.empty:
            for idx, row in recent_df.iterrows():
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{row['requirement_name']}** - {row['customer_name']}")
                with col2:
                    st.write(f"By {row['created_by']} on {row['created_date'].strftime('%Y-%m-%d')}")
                with col3:
                    status_color = {
                        'ACTIVE': '🟢',
                        'DRAFT': '🟡',
                        'INACTIVE': '🔴',
                        'ARCHIVED': '⚫'
                    }
                    st.write(f"{status_color.get(row['status'], '⚪')} {row['status']}")
        else:
            st.info("No recent activity")
            
    except Exception as e:
        st.info("Recent activity will appear here")
    
    # Footer
    st.markdown("---")
    st.caption("ProsTech Label Management System v1.0 | For support, contact IT team")

def main():

    st.markdown("""
    <style>
    .main-header {
        color: #1f77b4;
        text-align: center;
        padding: 1rem;
    }
    .login-container {
        padding: 2rem;
        border-radius: 0.5rem;
        background-color: #f0f2f6;
    }
    </style>
    """, unsafe_allow_html=True)

    if auth.check_session():
        st.success("✅ Login successful!")
        main_app()
    else:
        show_login_form()

if __name__ == "__main__":
    main()
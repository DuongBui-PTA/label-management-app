# pages/1_🏷️_Customer_Label_Requirement.py

import base64
import streamlit as st
import pandas as pd
from services import labels_v2 as labels_svc
from services import printer as printer_svc
from services import form_builder as form_builder_svc
import qrcode
from io import BytesIO
import html
import textwrap
from datetime import datetime
import time
from utils.auth import AuthManager
from utils.s3_utils import S3Manager
import logging

logger = logging.getLogger(__name__)

# Authentication check
auth_manager = AuthManager()
if not auth_manager.require_auth():
    st.stop()

# Initialize S3
try:
    s3_manager = S3Manager()
except Exception as e:
    st.error("Unable to connect to file storage service. Please contact support.")
    logger.error(f"S3 initialization failed: {e}")
    st.stop()

try:
    import win32print
except ImportError:
    win32print = None

st.set_page_config(layout="wide")
st.title("🏷️ Customer Label Requirement Management")

CURRENT_USER_ID = st.session_state.get("user_id", 1)

# KHỞI TẠO STATE VÀ MODAL

def init_state():
    # State cho tab Label Fields
    st.session_state.setdefault("lf_current_lt_id", None)
    st.session_state.setdefault("lf_current_lt_name", None)
    st.session_state.setdefault("lf_loaded_lt_id", None)
    st.session_state.setdefault("lf_db_fields", [])
    st.session_state.setdefault("lf_new_fields_buffer", [])

    # State cho luồng tạo và xem trước Label
    st.session_state.setdefault("lf_active_tab", "📄 Label Requirement List")
    st.session_state.setdefault("preview_label_data", None) # Lưu dữ liệu label để preview và quay lại edit

    # Lưu Label Type đang được chọn ở tab Create Label
    st.session_state.setdefault("cl_selected_lt_label", "(Choose)")

init_state()

def load_fields_from_db_once(requirement_id: int, force: bool = False):
    """Tải danh sách các field từ DB cho một requirement_id cụ thể."""
    if not force and st.session_state.get("lf_loaded_lt_id") == requirement_id:
        return
    rows = labels_svc.get_label_content_fields(requirement_id)
    st.session_state["lf_db_fields"] = rows # Lưu toàn bộ dict từ DB
    st.session_state["lf_loaded_lt_id"] = requirement_id

# Chọn Customer
customers = labels_svc.get_active_customers()
if not customers:
    st.warning("No active customer yet")
    st.stop()

customer_label = st.selectbox(
    "👥 *Choose Customer",
    ["(Choose)"] + [f"ID: {p['customer_id']} - {p['customer_english_name']} ({p['customer_code']})" for p in customers],
    key="lf_customer_select"
)

if customer_label == "(Choose)":
    customer_id = None
else:
    customer_id = next(p["customer_id"] for p in customers
                       if f"ID: {p['customer_id']} - {p['customer_english_name']} ({p['customer_code']})" == customer_label)

st.divider()

tab_options = [
    "📄 Label Requirement List",
    "➕ Create Label Requirement",
    "➕ Create Label Fields"
]

def switch_tab():
    st.session_state.lf_active_tab = st.session_state.main_navigation

st.radio(
    " ",
    tab_options,
    index=tab_options.index(st.session_state.get("lf_active_tab", "📄 Label Requirement List")),
    horizontal=True,
    key="main_navigation",
    on_change=switch_tab
)

st.divider()

lf_active_tab = st.session_state.lf_active_tab

if lf_active_tab == "📄 Label Requirement List":
    if customer_id is None:
        st.warning("⚠️ Please select a **Customer**")
    else:
        # Lấy tên customer đã chọn để hiển thị tiêu đề
        selected_customer_name = customer_label.split(' - ')[1].split(' (')[0]
        st.subheader(f"List of label requirements of: **{selected_customer_name}**")

        # Gọi service để lấy danh sách các yêu cầu về nhãn
        requirements = labels_svc.get_customer_label_requirements(customer_id)
        
        if not requirements:
            st.info("This customer has not yet requested any labels to be created")
        else:
            # Chuyển đổi dữ liệu sang DataFrame của Pandas để hiển thị bảng
            df = pd.DataFrame(requirements)
            
            # Tùy chỉnh các cột cần hiển thị và đổi tên để thân thiện hơn
            columns_to_display = {
                'customer_code': 'Customer Code',
                'customer_name': 'Customer',
                'requirement_name': 'Requirement Name',
                'requirement_type': 'Requirement Type',
                'label_size': 'Label Size',
                'printer_dpi': 'Printer DPI',
                'printer_type': 'Printer Type',
                'special_notes': 'Special Notes',
                'status': 'Status',
                'effective_from': 'Effective From',
                'created_by': 'Created By'
            }
            
            # Lọc ra những cột có trong dictionary mà cũng tồn tại trong DataFrame
            existing_columns = [col for col in columns_to_display.keys() if col in df.columns]

            # Lọc dataframe để chỉ giữ lại các cột cần thiết và đã tồn tại
            display_df = df[existing_columns]
            
            # Đổi tên cột
            display_df = display_df.rename(columns=columns_to_display)

            # Hiển thị bảng dữ liệu với st.dataframe
            st.dataframe(display_df, width='stretch')


elif lf_active_tab == "➕ Create Label Requirement":
    if customer_id is None:
        st.warning("⚠️ Please select a **Customer**")
        st.stop()
    
    selected_customer_name = customer_label.split(' - ')[1].split(' (')[0]
    st.subheader(f"Create New Label Requirement for: **{selected_customer_name}**")
    
    # --- PHẦN 1: FORM NHẬP LIỆU (Luôn hiển thị) ---
    # Sử dụng clear_on_submit=False để giữ lại dữ liệu khi người dùng quay lại từ màn hình review
    with st.form("form_create_label_requirement", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            req_name = st.text_input("Requirement Name *")
            req_type = st.selectbox(
                "Requirement Type *",
                options=['ITEM_LABEL', 'CARTON_LABEL']
            )
            # label_size = st.text_input("Label Size")
            ls_c1, ls_c2 = st.columns(2)
            with ls_c1:
                label_width = st.number_input("Label Width *", min_value=1, step=1, value=100)
            with ls_c2:
                label_height = st.number_input("Label Height *", min_value=1, step=1, value=80)
            printer_type = st.text_input("Printer Type")
            
        with c2:
            effective_from = st.date_input("Effective From *", value=datetime.today())
            effective_to = st.date_input("Effective To", value=None)
            printer_dpi = st.number_input("Printer DPI", min_value=0, step=10, value=300)
            status = st.selectbox(
                "Status *",
                options=['DRAFT', 'ACTIVE'],
                index=1
            )

        special_notes = st.text_area("Special Notes")
        
        submitted_review_req = st.form_submit_button("➡️ Review Requirement", type="primary")

    if submitted_review_req:
        label_size = f"{label_width}x{label_height}mm"
        # --- Validate dữ liệu ---
        if not req_name.strip():
            st.error("Requirement Name is required")
        elif not effective_from:
            st.error("Effective From is required")
        elif not label_width:
            st.error("Label Width is required")
        elif not label_height:
            st.error("Label Height is required")
        else:
            # --- Lấy thông tin customer để chuẩn bị cho review ---
            selected_customer_info = next((p for p in customers if p['customer_id'] == customer_id), None)
            
            # --- Thay vì lưu vào DB, lưu vào session_state để review ---
            data_for_review = {
                "customer_id": customer_id,
                "requirement_name": req_name,
                "requirement_type": req_type,
                "effective_from": effective_from,
                "created_by": str(CURRENT_USER_ID),
                "status": status,
                "label_size": label_size.strip() or None,
                "printer_type": printer_type.strip() or None,
                "printer_dpi": printer_dpi if printer_dpi > 0 else None,
                "effective_to": effective_to,
                "special_notes": special_notes.strip() or None,
            }
            st.session_state.clr_review_data = data_for_review
            st.rerun()

    # --- PHẦN 2: KHỐI REVIEW (Chỉ hiển thị khi có dữ liệu trong state) ---
    if st.session_state.get("clr_review_data"):
        st.markdown("---")
        st.subheader("Please Review Your Requirement")
        
        review_data = st.session_state.clr_review_data
        
        # Hiển thị dữ liệu dưới dạng bảng cho dễ nhìn
        display_data = {
            "Field": list(review_data.keys()),
            "Value": [str(v) if v is not None else "---" for v in review_data.values()]
        }
        st.table(pd.DataFrame(display_data))

        st.markdown("---")
        
        col1, col2, col3 = st.columns([1, 1, 3])
        
        with col1:
            if st.button("⬅️ Edit"):
                # Xóa state review để ẩn khối này và quay lại chỉnh sửa form
                st.session_state.clr_review_data = None
                st.rerun()
        
        with col2:
            if st.button("✅ Confirm", type="primary"):
                # --- Gọi service để lưu vào DB ---
                ok, msg, new_req_id = labels_svc.create_customer_label_requirement(review_data)
                
                if ok:
                    st.toast(f"Label request created successfully! New ID: {new_req_id}", icon="✅")
                    st.balloons()                  
                    # Xóa state review để ẩn khối này và sẵn sàng cho lần tạo mới
                    st.session_state.clr_review_data = None
                    st.rerun()
                else:
                    st.error(f"Error: {msg}")

    # --- PHẦN 3: DANH SÁCH YÊU CẦU ĐÃ TỒN TẠI (Luôn hiển thị ở cuối) ---
    st.markdown("---")
    st.markdown("#### This customer's existing label requirements")
    try:
        existing_requirements = labels_svc.get_customer_label_requirements(customer_id)
        if existing_requirements:
            df = pd.DataFrame(existing_requirements)
            st.dataframe(df[['customer_code', 'customer_name', 'requirement_name', 'requirement_type', 'label_size', 'special_notes', 'status', 'effective_from']])
        else:
            st.info("This customer has no label requests yet")
    except Exception as e:
        st.warning(f"Could not load list of existing requests. Error: {e}")


elif lf_active_tab == "➕ Create Label Fields":
    if customer_id is None:
        st.warning("⚠️ Please select a **Customer**")
        st.stop()

    st.subheader("Configure Label Content Fields")
    
    # --- 1. Chọn Label Requirement ---
    requirements = labels_svc.get_customer_label_requirements(customer_id)
    if not requirements:
        st.info("This customer has no Label Requirements. Please create one in the '➕ Create Label Requirement' tab first.")
        st.stop()
    
    req_options = {f"ID: {r['id']} - {r['requirement_type']} ({r['requirement_name']})": r['id'] for r in requirements}
    
    selected_req_label = st.selectbox(
        "Choose a Label Requirement to configure",
        options=["(Choose)"] + list(req_options.keys()),
        key="lf_requirement_selector"
    )

    if selected_req_label == "(Choose)":
        st.session_state["lf_current_lt_id"] = None
        st.session_state["lf_current_lt_name"] = None
        st.info("Select a Label Requirement to see and add fields.")
        st.stop()
    
    requirement_id = req_options.get(selected_req_label)
    if st.session_state.get("lf_current_lt_id") != requirement_id:
        st.session_state["lf_current_lt_id"] = requirement_id
        st.session_state["lf_current_lt_name"] = selected_req_label.split(" (ID:")[0]
        st.session_state["lf_loaded_lt_id"] = None # Force reload
        st.session_state.setdefault("lf_review_buffer", [])
        st.session_state["lf_review_buffer"] = [] # Xóa buffer khi đổi requirement
        st.rerun()

    load_fields_from_db_once(requirement_id)
    
    st.markdown("---")
    st.subheader(f"Fields for: **{st.session_state.lf_current_lt_name}**")

    # --- 2. Hiển thị các field đã có ---
    with st.expander("📄 Fields already in the database", expanded=True):
        current_fields_in_db = st.session_state.get("lf_db_fields", [])
        if current_fields_in_db:
            df_db = pd.DataFrame(current_fields_in_db)
            display_cols = ['field_code', 'field_name', 'field_type', 'data_source', 'format_pattern', 'sample_value', 'display_order', 'is_required', 'special_rules']
            existing_display_cols = [col for col in display_cols if col in df_db.columns]
            st.dataframe(df_db[existing_display_cols], hide_index=True, width='stretch')
        else:
            st.info("This Label Requirement has no fields defined yet.")

    # --- 3. Form thêm field mới vào danh sách review ---
    st.markdown("### Add a New Field")
    with st.form("form_add_field_to_review", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1: field_code = st.text_input("Field Code *")
        with c2: field_name = st.text_input("Field Name *")
        with c3:
            VALID_FIELD_TYPES = ['TEXT', 'BARCODE_1D', 'BARCODE_2D', 'QRCODE', 'DATE', 'NUMBER', 'IMAGE']
            field_type = st.selectbox("Field Type *", options=VALID_FIELD_TYPES)

        c4, c5, c6 = st.columns([2, 2, 1])
        with c4: sample_value = st.text_input("Sample Value")
        with c5: format_pattern = st.text_input("Format Pattern")
        with c6: display_order = st.number_input("Display Order", min_value=1, step=1, value=len(current_fields_in_db) + len(st.session_state.get("lf_review_buffer", [])) + 1)
        
        c7, c8 = st.columns([3, 1])
        with c7: data_source = st.text_input("Data Source")
        with c8: is_required = st.checkbox("Is Required?", value=True)

        special_rules = st.text_area("Special Rules")

        submitted_add_to_review = st.form_submit_button("➕ Add to Review List")

    if submitted_add_to_review:
        code = field_code.upper().strip()
        name = field_name.strip()
        
        is_in_db = any(f.get("field_code") == code for f in current_fields_in_db)
        is_in_buffer = any(f.get("field_code") == code for f in st.session_state.get("lf_review_buffer", []))

        if not code or not name:
            st.warning("Field Code and Field Name are required.")
        elif is_in_db:
            st.error(f"Error: Field Code '{code}' already exists in the database.")
        elif is_in_buffer:
            st.error(f"Error: Field Code '{code}' is already in the review list.")
        else:
            new_field_data = {
                "field_code": code, "field_name": name, "field_type": field_type,
                "data_source": data_source.strip() or None,
                "format_pattern": format_pattern.strip() or None,
                "sample_value": sample_value.strip() or None,
                "display_order": display_order, "is_required": is_required,
                "special_rules": special_rules.strip() or None
            }
            st.session_state.setdefault("lf_review_buffer", [])
            st.session_state.lf_review_buffer.append(new_field_data)
            st.success(f"Field '{name}' was added to the review list below.")
            st.rerun()

    # --- 4. Hiển thị danh sách review và nút xác nhận ---
    review_buffer = st.session_state.get("lf_review_buffer", [])
    if review_buffer:
        st.markdown("---")
        st.subheader("👁️ Fields Pending Review")
        st.caption("These fields have NOT been saved yet. Review them and click 'Confirm & Save All'.")

        df_review = pd.DataFrame(review_buffer)
        st.dataframe(df_review, hide_index=True, width='stretch')
        
        col1, col2, col_spacer = st.columns([2, 2, 5])
        with col1:
            if st.button("✅ Confirm & Save All", type="primary"):
                with st.spinner("Saving fields to database..."):
                    success_count = 0
                    error_messages = []
                    for field_data in review_buffer:
                        # Thêm requirement_id vào dữ liệu trước khi lưu
                        field_data_to_save = field_data.copy()
                        field_data_to_save['requirement_id'] = requirement_id

                        success, message, _ = labels_svc.add_label_content_field(field_data_to_save)
                        if success:
                            success_count += 1
                        else:
                            error_messages.append(f"- Field '{field_data['field_code']}': {message}")
                
                if error_messages:
                    st.error("Some fields could not be saved:")
                    st.markdown("\n".join(error_messages))

                if success_count > 0:
                    st.success(f"✅ Successfully saved {success_count} field(s)!")
                    st.balloons()
                
                # Xóa buffer và tải lại trang để cập nhật danh sách
                st.session_state.lf_review_buffer = []
                st.session_state.lf_loaded_lt_id = None
                time.sleep(1)
                st.rerun()

        with col2:
            if st.button("🗑️ Clear Review List"):
                st.session_state.lf_review_buffer = []
                st.toast("Review list cleared.")
                st.rerun()
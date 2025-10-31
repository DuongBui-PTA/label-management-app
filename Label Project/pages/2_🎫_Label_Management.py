# pages/2_🎫_Label_Management.py

import base64
import streamlit as st
import pandas as pd
import math
import qrcode
import barcode
from barcode.writer import ImageWriter
import html
import textwrap
import logging
import json
from services import labels_v2 as labels_svc
from services import printer as printer_svc
from services import form_builder as form_builder_svc
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode
from streamlit_modal import Modal
from datetime import datetime, timedelta, date
from io import BytesIO
from utils.auth import AuthManager
from utils.s3_utils import S3Manager

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

st.set_page_config(layout="wide")
st.title("🏷️ Label Management")

# KHỞI TẠO DEF, STATE VÀ MODAL

# session_state quản lý tab đang hoạt động
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "📦 Select Product"

# xử lý chuyển tab tự động qua button
if 'next_tab' in st.session_state:
    st.session_state.active_tab = st.session_state.next_tab
    del st.session_state.next_tab

# session_state lưu sản phẩm đã chọn
if 'product_for_label' not in st.session_state:
    st.session_state.product_for_label = None

# session_state lưu customer_id
if 'customer_id_for_label' not in st.session_state:
    st.session_state.customer_id_for_label = None

# session_state lưu entity_id
if 'entity_id_for_label' not in st.session_state:
    st.session_state.entity_id_for_label = None

# session_state lưu trữ thông tin cuối cùng để hiển thị trên nhãn
if 'label_preview_data' not in st.session_state:
    st.session_state.label_preview_data = {}

# session_state lưu trữ tạm thông tin form trước khi confirm
if 'temp_label_form_data' not in st.session_state:
    st.session_state.temp_label_form_data = {}
if 'temp_label_settings' not in st.session_state:
    st.session_state.temp_label_settings = {}
if 'temp_content_fields_map' not in st.session_state:
    st.session_state.temp_content_fields_map = {}

# modal review thông tin sản phẩm
confirm_modal = Modal(
    "Review Product Information",
    key="confirm_product_modal",
    max_width=700
)

# modal review nội dung nhãn được nhập từ form
review_label_modal = Modal(
    "Review Label Information",
    key="review_label_modal",
    max_width=700
)

def confirm_label_and_update_preview():
    
    form_data = st.session_state.get('temp_label_form_data', {})
    product_info = st.session_state.get('product_for_label', {})
    settings = st.session_state.get('temp_label_settings', {})
    confirmed_label_type = settings.get("label_type")

    if confirmed_label_type in ["ITEM_LABEL", "CARTON_LABEL"]:
        updated_data = form_data.copy()
    else:
        updated_data = {**product_info, **form_data}

    st.session_state.label_preview_data = updated_data

    if confirmed_label_type != "PACKAGE_LABEL":
        if "is_package_from_history" in st.session_state:
            del st.session_state.is_package_from_history
        if "package_history_data" in st.session_state:
            del st.session_state.package_history_data

    # Xóa dữ liệu tạm
    st.session_state.temp_label_form_data = {}
    st.session_state.temp_label_settings = {}
    st.session_state.temp_content_fields_map = {}

    review_label_modal.close()
    st.toast("Updated preview with new information!", icon="✅")

def confirm_and_switch_tab(product_data, customer_id, entity_id):
    
    st.session_state.product_for_label = product_data
    st.session_state.customer_id_for_label = customer_id
    st.session_state.entity_id_for_label = entity_id
    st.session_state.next_tab = "👁️‍🗨️ Preview and Create Label"
    st.session_state.label_preview_data = product_data.copy()
    confirm_modal.close()
    
    if "is_package_from_history" in st.session_state:
        del st.session_state.is_package_from_history
    if "package_history_data" in st.session_state:
        del st.session_state.package_history_data

def switch_to_select_product_tab():
    
    st.session_state.next_tab = "📦 Select Product"

    # Xóa dữ liệu cũ khi quay lại
    st.session_state.product_for_label = None
    st.session_state.customer_id_for_label = None
    st.session_state.entity_id_for_label = None
    st.session_state.label_preview_data = {}

    if "is_package_from_history" in st.session_state:
        del st.session_state.is_package_from_history
    if "package_history_data" in st.session_state:
        del st.session_state.package_history_data

# --- GIAO DIỆN CHÍNH ---

label_management_tabs = [
    "📦 Select Product",
    "👁️‍🗨️ Preview and Create Label",
    "⌛ History Label Printing"
]

tab_selection = st.radio(" ", label_management_tabs, key="active_tab", horizontal=True, label_visibility="collapsed")

st.divider()

# --- TAB 1: LỰA CHỌN SẢN PHẨM ---
if tab_selection == "📦 Select Product":
    
    @st.cache_data(ttl=600)
    def load_initial_data():
        customers = labels_svc.get_active_customers()
        entities = labels_svc.get_active_entities()
        return customers, entities

    @st.cache_data(ttl=600)
    def load_dns(customer_code: str, entity_code: str):
        if not customer_code or not entity_code: return []
        return labels_svc.get_dns_for_customer_and_entity(customer_code, entity_code)

    @st.cache_data(ttl=600)
    def load_products(dns: tuple[str], group_by_batch: bool):
        if not dns: return []
        return labels_svc.get_products_by_dns(list(dns), group_by_batch_no=group_by_batch)

    customers, entities = load_initial_data()

    selected_customer = None
    selected_entity = None
    selected_dns = []

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("👥 Customer")
        if customers:
            selected_customer = st.selectbox(
                label="*Choose Customer",
                options=customers,
                format_func=lambda customer: f"{customer['customer_english_name']} ({customer['customer_code']})",
                index=None,
                placeholder="Find and select customers...",
                key="customer_selector"
            )
        else:
            st.warning("No customer data to display", icon="🚨")

    with col2:
        st.subheader("👤 Entity")
        if entities:
            selected_entity = st.selectbox(
                label="*Choose Entity",
                options=entities,
                format_func=lambda entity: f"{entity['entity_english_name']} ({entity['entity_code']})",
                index=None,
                placeholder="Find and select entities...",
                key="entity_selector"
            )
        else:
            st.warning("No entity data to display", icon="🚨")

    if selected_customer and selected_entity:

        st.subheader("📃 DN Number")
        customer_code = selected_customer.get('customer_code')
        entity_code = selected_entity.get('entity_code')
        dns_list = load_dns(customer_code, entity_code)
        
        if dns_list:
            if 'dn_df' not in st.session_state or set(st.session_state.dn_df['DN Number']) != set(dns_list):
                st.session_state.dn_df = pd.DataFrame({
                    'Choose': [False] * len(dns_list),
                    'DN Number': dns_list
                })

            def select_all_dns():
                st.session_state.dn_df['Choose'] = True

            def deselect_all_dns():
                st.session_state.dn_df['Choose'] = False

            btn_col1, btn_col2, _ = st.columns([1, 1, 4])

            with btn_col1:
                st.button("Select All", on_click=select_all_dns, width='stretch', type="primary")
            with btn_col2:
                st.button("Deselect all", on_click=deselect_all_dns, width='stretch')

            edited_dn_df = st.data_editor(
                st.session_state.dn_df,
                width='stretch',
                hide_index=True,
                disabled=["DN Number"] 
            )

            selected_dns = edited_dn_df[edited_dn_df['Choose']]['DN Number'].tolist()
        else:
            st.warning("There are no DN Number in 'STOCKED_OUT' state for this selection", icon="🚨")
    else:
        st.info("Select Customer and Entity to continue")

    st.divider()

    selected_product_df = pd.DataFrame()

    if selected_dns:
        st.subheader("📦 Product List")
        grouping_option = st.radio(
            label="Group Products By:",
            options=("Product ID & Batch No", "Product ID"),
            horizontal=True,
        )
        group_by_batch = (grouping_option == "Product ID & Batch No")
        product_list = load_products(tuple(selected_dns), group_by_batch=group_by_batch)
        
        if product_list:
            df_products = pd.DataFrame(product_list)
            st.write(f"Found: **{len(df_products)}** products")
            st.caption("Select a product from the table below to prepare the label for printing")
            
            gb = GridOptionsBuilder.from_dataframe(df_products)
            gb.configure_selection('single', use_checkbox=True, header_checkbox=False)
            gb.configure_pagination(paginationAutoPageSize=True)
            gb.configure_side_bar()
            gridOptions = gb.build()

            grid_response = AgGrid(
                df_products,
                gridOptions=gridOptions,
                data_return_mode=DataReturnMode.AS_INPUT,
                update_on=['selectionChanged'],
                fit_columns_on_grid_load=True,
                height=350,
                width='100%',
                key='product_grid'
            )
            selected_product_df = pd.DataFrame(grid_response['selected_rows'])
        else:
            st.warning("No products found for the selected businesses", icon="🚨")

    elif selected_customer and selected_entity:
        st.info("Select a DN Number to view the product list")

    is_product_selected = not selected_product_df.empty

    open_modal_button = st.button(
        "👁️ Review Selected Product",
        width='stretch',
        type="primary",
        disabled=not is_product_selected
    )

    if open_modal_button:
        confirm_modal.open()

    if confirm_modal.is_open():
        with confirm_modal.container():
            
            display_df = selected_product_df.drop(columns=['_selectedRowNodeInfo'], errors='ignore')
            st.dataframe(display_df, hide_index=True, width='stretch')
            
            st.divider()

            modal_col1, modal_col2 = st.columns(2)
            with modal_col1:
                product_data_to_pass = display_df.to_dict('records')[0]
                customer_id_to_pass = selected_customer.get('customer_id') if selected_customer else None
                entity_id_to_pass = selected_entity.get('entity_id') if selected_entity else None
                
                st.button(
                    "✅ Confirm", 
                    type="primary", 
                    width='stretch',
                    on_click=confirm_and_switch_tab,
                    args=(product_data_to_pass, customer_id_to_pass, entity_id_to_pass)
                )
            with modal_col2:
                if st.button("❌ Cancel", width='stretch'): confirm_modal.close()
    
    if not is_product_selected:
        st.caption("Select a product to continue")

# --- TAB 2: XEM TRƯỚC VÀ TẠO NHÃN ---
elif tab_selection == "👁️‍🗨️ Preview and Create Label":

    @st.cache_data(ttl=300)
    def load_label_requirements(customer_id: int):
        if not customer_id:
            return []
        return labels_svc.get_customer_label_requirements(customer_id)
    
    @st.cache_data(ttl=300)
    def load_label_content_fields(requirement_id: int):
        if not requirement_id:
            return []
        return labels_svc.get_label_content_fields(requirement_id)

    if st.session_state.product_for_label:
        product_info = st.session_state.product_for_label
        customer_id = st.session_state.get('customer_id_for_label')
        entity_id = st.session_state.get('entity_id_for_label')
        label_requirements = load_label_requirements(customer_id)
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📃 Product Information")
            with st.container(border=True):
                c1_info, c2_info = st.columns(2)
                with c1_info:
                    st.text_input("Customer", value=product_info.get('customer', 'N/A'), disabled=True)
                    st.text_input("DN Number", value=product_info.get('dn_number', 'N/A'), disabled=True)
                    st.text_input("Vendor Product Code", value=product_info.get('product_mapped_code', 'N/A'), disabled=True)
                    st.text_input("PT Code", value=product_info.get('pt_code', 'N/A'), disabled=True)
                    st.text_input("Package Size", value=product_info.get('package_size', 'N/A'), disabled=True)
                    st.text_input("Total Standard Qty", value=product_info.get('total_standard_qty', 'N/A'), disabled=True)
                    st.text_input("Brand", value=product_info.get('brand', 'N/A'), disabled=True)
                with c2_info:
                    st.text_input("Entity", value=product_info.get('legal_entity', 'N/A'), disabled=True)
                    st.text_input("Product Code", value=product_info.get('product_pn', 'N/A'), disabled=True)
                    st.text_input("Vendor Product Name", value=product_info.get('product_mapped_name', 'N/A'), disabled=True)
                    st.text_input("Batch No", value=product_info.get('batch_no', 'N/A'), disabled=True)
                    st.text_input("Shelf Life", value=product_info.get('shelf_life', 'N/A'), disabled=True)
                    st.text_input("Total Selling Qty", value=product_info.get('total_selling_qty', 'N/A'), disabled=True)
                    st.text_input("UOM", value=product_info.get('uom', 'N/A'), disabled=True)

        number_of_labels = 0
        qty_per_carton = 1
        form_data = {}
        content_fields = []

        with col2:
            st.subheader("🎫 Customer Label Requirements")

            selected_requirement = None

            if label_requirements:
                if len(label_requirements) > 1:
                    requirement_options = {
                        f"{req['requirement_name']} ({req['requirement_type']})": req
                        for req in label_requirements
                    }
                    selected_option_key = st.selectbox(
                        "Select a label requirement:",
                        options=requirement_options.keys()
                    )
                    selected_requirement = requirement_options[selected_option_key]
                else:
                    selected_requirement = label_requirements[0]

            if selected_requirement:
                with st.container(border=True):
                    req_col1, req_col2 = st.columns(2)
                    with req_col1:
                        st.text_input("Label Name", value=selected_requirement.get('requirement_name', 'N/A'), disabled=True, key="selected_req_name")
                        st.text_input("Label Type", value=selected_requirement.get('requirement_type', 'N/A'), disabled=True, key="selected_req_type")
                        st.text_input("Printer Dpi", value=selected_requirement.get('printer_dpi', 'N/A'), disabled=True, key="selected_req_dpi")
                    with req_col2:
                        st.text_input("Label Size", value=selected_requirement.get('label_size', 'N/A'), disabled=True, key="selected_req_size")
                        st.text_input("Special Notes", value=selected_requirement.get('special_notes', 'N/A'), disabled=True, key="selected_req_notes")
                        st.text_input("Printer Type", value=selected_requirement.get('printer_type', 'N/A'), disabled=True, key="selected_req_printer")
            else:
                st.warning("No existing Customer Label Requirements")

        st.divider()

        st.subheader("⌨️ Enter data for the label")

        # Lấy cờ khóa (lock flag) ra ngoài để cả col1 (form) và col2 (settings) đều dùng được
        is_locked_for_package = st.session_state.get("is_package_from_history", False)

        col1, col2 = st.columns(2)
        with col1:
            if selected_requirement:
                with st.container(border=True):

                    if is_locked_for_package:
                        st.info("ℹ️ Data entry is disabled when creating a Package Label from history. Data will be aggregated from selected items.")

                    requirement_id = selected_requirement.get('id')
                    content_fields = load_label_content_fields(requirement_id)

                    if content_fields:
                        form_col1, form_col2 = st.columns(2)
                        for i, field in enumerate(content_fields):
                            target_col = form_col1 if i % 2 == 0 else form_col2
                            with target_col:
                                field_type = field.get('field_type', 'TEXT').upper()
                                label = field.get('field_name')
                                placeholder = field.get('sample_value')
                                key = f"dynamic_field_{field.get('id')}"
                                field_code = field.get('field_code')

                                default_value = st.session_state.label_preview_data.get(field_code, "")

                                value = None

                                if field_type == 'NUMBER':
                                    value = st.number_input(
                                        label=label,
                                        placeholder=placeholder,
                                        key=key,
                                        step=1,
                                        format="%d",
                                        value=int(default_value) if isinstance(default_value, (int, float)) or (isinstance(default_value, str) and default_value.isdigit()) else 0,
                                        disabled=is_locked_for_package
                                    )
                                elif field_type == 'DATE':
                                    try:
                                        default_date = datetime.strptime(str(default_value) if default_value else placeholder, "%Y-%m-%d").date()
                                    except (ValueError, TypeError):
                                        default_date = datetime.now().date()
                                    value = st.date_input(
                                        label=label, 
                                        key=key, 
                                        value=default_date,
                                        disabled=is_locked_for_package
                                    )
                                else:
                                    value = st.text_input(
                                        label=label,
                                        placeholder=placeholder,
                                        key=key,
                                        value=str(default_value),
                                        disabled=is_locked_for_package
                                    )
                                
                                if value is not None:
                                    form_data[field.get('field_code')] = value
                    else:
                        st.warning("This label request has no content fields", icon='🚨')
        with col2:
            with st.container(border=True):

                label_type_options = ["ITEM_LABEL", "CARTON_LABEL", "PACKAGE_LABEL"]
                default_index = 0
                
                if is_locked_for_package:
                    # 1. Ưu tiên cao nhất: Khóa nếu là package từ history
                    default_index = label_type_options.index("PACKAGE_LABEL")
                    # Xóa cờ "override" dùng một lần nếu có, vì cờ "is_locked" đã thay thế
                    if 'default_label_type_override' in st.session_state:
                        del st.session_state.default_label_type_override
                
                elif 'default_label_type_override' in st.session_state and st.session_state.default_label_type_override in label_type_options:
                    # 2. Ưu tiên nhì: Tín hiệu 1 lần (nếu có, mặc dù Tab 3 set cả 2)
                    default_index = label_type_options.index(st.session_state.default_label_type_override)
                    # Xóa tín hiệu để không bị dính cho lần sau
                    del st.session_state.default_label_type_override
                
                elif selected_requirement: 
                    # 3. Mặc định: Lấy từ requirement
                    default_label_type = selected_requirement.get('requirement_type')
                    if default_label_type in label_type_options:
                        default_index = label_type_options.index(default_label_type)

                label_template = st.selectbox(
                    "Label Type:",
                    options=label_type_options,
                    index=default_index,
                    disabled=is_locked_for_package
                )

                total_selling_qty = int(product_info.get('total_selling_qty', 0))

                if label_template == "ITEM_LABEL" or label_template == "CARTON_LABEL":
                    qty_per_carton_value = int(product_info.get('total_standard_qty', 1))
                    qty_per_carton = st.number_input(
                        "Quantity Per Carton:",
                        min_value=1,
                        max_value=total_selling_qty if total_selling_qty > 0 else 1,
                        value=qty_per_carton_value,
                        help=f"Nhập số lượng sản phẩm trong một thùng / một pcs. Tối đa: {total_selling_qty}"
                    )
                    ceil_value = math.ceil(total_selling_qty / qty_per_carton) if qty_per_carton > 0 else 0
                    floor_value = math.floor(total_selling_qty / qty_per_carton) if qty_per_carton > 0 else 0
                    if ceil_value == floor_value or floor_value == 0:
                        number_of_labels = st.number_input(
                            "Number of Labels:",
                            value=ceil_value,
                            disabled=True,
                            help="Số lượng thùng được tính tự động bằng công thức total_selling_quantity / Quantity Per Carton"
                        )
                    else:
                        st.caption("Due to odd products, please select the number of boxes to print labels")
                        number_of_labels = st.radio(
                            "Select the number of labels:",
                            options=[floor_value, ceil_value],
                            index=1,
                            format_func=lambda x: f"{x} labels (Round down)" if x == floor_value else f"{x} labels (Round up)",
                            horizontal=True
                        )
                else: # PACKAGE_LABEL
                    number_of_labels = st.number_input(
                        "Number of Label:",
                        min_value=1,
                        value=1,
                        disabled=True,
                        help="Với 'PACKAGE_LABEL', số lượng nhãn luôn là 1"
                    )

        if st.button("👁️ Preview Label", type="primary", width='stretch'):

            errors = {}
            
            if label_template != "PACKAGE_LABEL":
                data_for_validation = {
                    field.get('field_name'): form_data.get(field.get('field_code'))
                    for field in content_fields
                }
                
                errors = form_builder_svc.validate_form(data_for_validation, content_fields)
            
            if errors:
                error_messages = []
                for field_name, message in errors.items():
                    error_messages.append(f"- **{field_name}** {message}")
                st.warning("Please check the form again:\n" + "\n".join(error_messages), icon="🚨")
            else:
                st.session_state.temp_label_form_data = form_data
                st.session_state.temp_label_settings = {
                    "label_type": label_template, 
                    "number_of_labels": number_of_labels
                }
                st.session_state.temp_content_fields_map = {
                    f.get('field_code'): f.get('field_name') for f in content_fields
                }
                review_label_modal.open()

        # Hiển thị modal review
        if review_label_modal.is_open():
            with review_label_modal.container():
                
                # Lấy dữ liệu tạm thời
                form_data_review = st.session_state.get('temp_label_form_data', {})
                settings_review = st.session_state.get('temp_label_settings', {})
                field_map_review = st.session_state.get('temp_content_fields_map', {})

                st.subheader("⌨️ Label Data")
                with st.container(border=True):
                    col_set1, col_set2 = st.columns(2)
                    with col_set1:
                        st.text_input("Label Type", value=settings_review.get('label_type', 'N/A'), disabled=True, key="modal_label_type")
                    with col_set2:
                        st.text_input("Number of Labels", value=settings_review.get('number_of_labels', 'N/A'), disabled=True, key="modal_num_labels")
                if form_data_review:
                    display_data = []
                    for field_code, value in form_data_review.items():
                        field_name = field_map_review.get(field_code, field_code) 
                        display_data.append({"Field": field_name, "Data": str(value)})
                    
                    st.dataframe(pd.DataFrame(display_data), hide_index=True, width='stretch')
                else:
                    st.warning("No additional data is entered", icon="🚨")
                
                st.divider()

                modal_col1, modal_col2 = st.columns(2)
                with modal_col1:
                    st.button(
                        "✅ Confirm & Update Preview", 
                        type="primary", 
                        width='stretch',
                        on_click=confirm_label_and_update_preview
                    )
                with modal_col2:
                    if st.button("❌ Cancel", width='stretch'):
                        st.session_state.temp_label_form_data = {}
                        st.session_state.temp_label_settings = {}
                        st.session_state.temp_content_fields_map = {}
                        review_label_modal.close()

        st.divider()
        
        st.header("👁️‍🗨️ Preview & Customize Layout")

        st.divider()

        lt_name = selected_requirement.get('requirement_name', 'Untitled Label') if selected_requirement else 'Untitled Label'
        
        # Dữ liệu cơ sở (thông tin sản phẩm + dữ liệu form mới)
        base_label_info = st.session_state.label_preview_data

        label_info = {}
        
        content_fields_for_preview = []
        if selected_requirement:
            requirement_id = selected_requirement.get('id')
            content_fields_for_preview = load_label_content_fields(requirement_id)

        col_settings, col_space, col_preview = st.columns([2, 1, 4]) 

        with col_settings:
            st.subheader("⚙️ Layout Settings")

            paper_width_default = 100
            paper_height_default = 80

            if selected_requirement and 'label_size' in selected_requirement:
                label_size_str = selected_requirement.get('label_size')
                
                # Phân tích chuỗi có dạng 'Width x Height mm'
                if isinstance(label_size_str, str) and 'x' in label_size_str.lower():
                    try:
                        cleaned_str = label_size_str.lower().replace('mm', '').strip()
                        parts = cleaned_str.split('x')
                        if len(parts) == 2:
                            width = int(parts[0].strip())
                            height = int(parts[1].strip())
                            paper_width_default = width
                            paper_height_default = height
                    except (ValueError, TypeError):
                        pass 
            
            col_w, col_h = st.columns(2)
            with col_w:
                paper_width = st.number_input("Paper Width (mm)", min_value=10, max_value=500, value=paper_width_default, step=1)
            with col_h:
                paper_height = st.number_input("Paper Height (mm)", min_value=10, max_value=500, value=paper_height_default, step=1)
            
            font_size = st.slider("Font Size (pt)", 6, 48, 12)

            text_orientation = st.radio("Rotate data", ["Horizontal", "Vertical"], horizontal=True)
            
            st.markdown("---")

            st.write("**Margins (mm)**")
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                margin_top = st.number_input("Top", min_value=0, max_value=paper_height, value=6, step=1)
                margin_left = st.number_input("Left", min_value=0, max_value=int(paper_width/2), value=6, step=1)
            with m_col2:
                margin_bottom = st.number_input("Bottom", min_value=0, max_value=paper_height, value=6, step=1)
                margin_right = st.number_input("Right", min_value=0, max_value=int(paper_width/2), value=6, step=1)

            qr_codes = []
            qr_field_codes = []
            barcodes_1d = []
            barcode_1d_field_codes = []
            
            for field in content_fields_for_preview:
                field_code = field.get("field_code", "")
                field_type = field.get("field_type", "").upper()
                content = base_label_info.get(field_code)
                
                if not content: continue
                
                if field_type == 'QRCODE' or field_type == 'BARCODE_2D':
                    qr_codes.append(content)
                    qr_field_codes.append(field_code)
                elif field_type == 'BARCODE_1D':
                    barcodes_1d.append(content)
                    barcode_1d_field_codes.append(field_code)

            qr_width_mm = 0 
            qr_height_mm = 0
            barcode_1d_width_mm = 0
            barcode_1d_height_mm = 0

            available_height = paper_height - margin_top - margin_bottom

            if qr_codes:
                st.markdown("---")
                st.write("**QR Code Size (mm)**")
                num_qrs = len(qr_codes)
                default_qr_size = max(25, int(available_height / num_qrs) - (5 * (num_qrs -1))) if num_qrs > 0 else 25
                qr_width_mm = st.number_input("QR Size", min_value=10, value=default_qr_size, step=1)
                qr_height_mm = qr_width_mm 

            if barcodes_1d:
                st.markdown("---")
                st.write("**Barcode Size (mm)**")
                default_bc_width = 60
                default_bc_height = 15
                
                bc_col1, bc_col2 = st.columns(2)
                with bc_col1:
                    barcode_1d_width_mm = st.number_input("Barcode Width (mm)", min_value=10, value=default_bc_width, step=1)
                with bc_col2:
                    barcode_1d_height_mm = st.number_input("Barcode Height (mm)", min_value=5, value=default_bc_height, step=1)

        with col_preview:
            st.subheader("👁️ Label Preview")
            
            px_per_mm = 4 
            preview_width_px = int(paper_width * px_per_mm)
            preview_height_px = int(paper_height * px_per_mm)
            margin_top_px = int(margin_top * px_per_mm)
            margin_bottom_px = int(margin_bottom * px_per_mm)
            margin_left_px = int(margin_left * px_per_mm)
            margin_right_px = int(margin_right * px_per_mm)
            inner_width_px = preview_width_px - margin_left_px - margin_right_px
            inner_height_px = preview_height_px - margin_top_px - margin_bottom_px
            
            text_html_content = ' '
            all_display_fields = []
            display_name_map = {}

            # 1. Luôn tải map trường
            for field in content_fields_for_preview:
                field_code = field.get('field_code')
                field_name = field.get('field_name')
                if field_code:
                    all_display_fields.append(field_code)
                    display_name_map[field_code] = field_name if field_name else field_code
            
            # 2. KIỂM TRA CHẾ ĐỘ TẠO PACKAGE TỪ HISTORY
            if st.session_state.get("is_package_from_history", False):
                
                final_package_data_for_preview = base_label_info.copy()
                aggregated_data_for_print = {} # Đây là dữ liệu SẼ ĐƯỢC IN

                history_items = st.session_state.get("package_history_data", [])


                new_dynamic_fields_html = ""
                for key in all_display_fields:

                    # Bỏ qua các trường QR
                    if key in qr_field_codes: continue
                    
                    value = base_label_info.get(key)
                    display_name = display_name_map.get(key, key)
                    
                    if value and str(value).strip() != '' and str(value) != 'N/A':
                        new_dynamic_fields_html += f'<div style="word-wrap: break-word;"><strong>{html.escape(display_name)}:</strong> {html.escape(str(value))}</div>'

                if new_dynamic_fields_html:
                    text_html_content += '<br>'
                    text_html_content += new_dynamic_fields_html

                # LOGIC GỘP DỮ LIỆU
                aggregated_data_for_preview = {}

                for item in history_items:

                    # Parse JSON data
                    data_str = item.get('printed_data')
                    data_dict = {}
                    if isinstance(data_str, str) and data_str:
                        try:
                            data_dict = json.loads(data_str)
                        except json.JSONDecodeError:
                            data_dict = {}
                    elif isinstance(data_str, dict): 
                        data_dict = data_str

                    # Gộp các giá trị từ printed_data, đảm bảo tính duy nhất
                    for k, v in data_dict.items():
                        field_name_check = display_name_map.get(k, k)

                        # Kiểm tra tên trường để loại bỏ qr code, nhưng gộp text của barcode
                        field_name_check_lower = str(field_name_check).lower()
                        if 'qr code' in field_name_check_lower: continue

                        if k not in aggregated_data_for_print: aggregated_data_for_print[k] = []

                        str_v = str(v)
                        if str_v not in aggregated_data_for_print[k]: # Chỉ thêm giá trị unique
                            aggregated_data_for_print[k].append(str_v)

                        # Gộp cho DỮ LIỆU PREVIEW (để hiển thị)
                        if k not in aggregated_data_for_preview: aggregated_data_for_preview[k] = []
                        if str_v not in aggregated_data_for_preview[k]:
                            aggregated_data_for_preview[k].append(str_v)

                # Hiển thị dữ liệu đã gộp VÀ CẬP NHẬT BIẾN DỮ LIỆU
                text_html_content += '<div style="font-size: 0.9em; margin-top: 5px; padding-top: 3px;">'

                # Hiển thị các trường data đã gộp (cho preview)
                if aggregated_data_for_preview:
                    data_html = ""
                    for k in sorted(aggregated_data_for_preview.keys()): # Sắp xếp key
                        v_list = aggregated_data_for_preview[k]
                        v_list.sort() # Sắp xếp value

                        field_name = display_name_map.get(k, k) 
                        values_str = ", ".join(v_list)
                        data_html += f"<div><strong>{html.escape(field_name)}: {html.escape(values_str)}</strong></div>"
                        
                        # Cập nhật dữ liệu gộp vào dict preview
                        final_package_data_for_preview[k] = values_str 
                
                    text_html_content += data_html

                text_html_content += "</div>"

                # === THIẾT LẬP DỮ LIỆU IN CUỐI CÙNG CHO PACKAGE LABEL ===
                
                # 1. Chuyển đổi dữ liệu in (list) thành string
                final_aggregated_data_for_print = {}
                for k, v_list in aggregated_data_for_print.items():
                    v_list.sort()
                    final_aggregated_data_for_print[k] = ", ".join(v_list)

                # 2. Gán CHỈ dữ liệu đã gộp cho label_info
                label_info = final_aggregated_data_for_print
                
                # 3. Xóa tất cả QR Code và Barcode (vì không lấy từ form mới)
                qr_codes = []
                qr_field_codes = []
                barcodes_1d = []
                barcode_1d_field_codes = []

            else:
                # LOGIC HIỂN THỊ PREVIEW TIÊU CHUẨN (CHO ITEM/CARTON LABEL)
                # Gán dict cơ sở cho label_info
                label_info = base_label_info 
                
                for key in all_display_fields:

                    if key in qr_field_codes: continue

                    value = label_info.get(key) # Dùng label_info đã được gán
                    display_name = display_name_map.get(key, key)

                    if value and str(value).strip() != '':
                        text_html_content += f'<div style="word-wrap: break-word;"><strong>{html.escape(display_name)}: {html.escape(str(value))}</strong></div>'
            
            # Đổi tên biến để bao gồm cả QR và Barcode
            image_html_block = ""
            if qr_codes or barcodes_1d:
                all_images_html_list = []
                
                if qr_codes:
                    qr_width_px = int(qr_width_mm * px_per_mm)
                    
                    for qr_content_item in qr_codes:
                        qr = qrcode.QRCode(version=1, box_size=10, border=2)
                        qr.add_data(str(qr_content_item))
                        qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white")
                        
                        buffered = BytesIO()
                        img.save(buffered, format="PNG")
                        qr_image_b64 = base64.b64encode(buffered.getvalue()).decode()
                        
                        all_images_html_list.append(
                            f'<img src="data:image/png;base64,{qr_image_b64}" style="width: {qr_width_px}px; height: auto;">'
                        )
                
                if barcodes_1d: # Thêm logic tạo 1D barcode
                    bc_width_px = int(barcode_1d_width_mm * px_per_mm)
                    bc_height_px = int(barcode_1d_height_mm * px_per_mm)
                    
                    for bc_content_item in barcodes_1d:
                        try:
                            # Sử dụng Code 128 làm mặc định vì nó mạnh mẽ
                            BARCODE_CLASS = barcode.get_barcode_class('code128')
                            
                            options = {
                                'module_height': barcode_1d_height_mm, # Chiều cao tính bằng mm
                                'font_size': 6, # Cỡ chữ cho văn bản bên dưới
                                'text_distance': 1.5, # Khoảng cách từ vạch đến văn bản
                                'quiet_zone': 0, # Lề
                                'write_text': False # Ẩn văn bản
                            }
                            
                            bc = BARCODE_CLASS(str(bc_content_item), writer=ImageWriter())
                            
                            buffered = BytesIO()
                            bc.write(buffered, options) # Ghi vào buffer
                            
                            buffered.seek(0)
                            bc_image_b64 = base64.b64encode(buffered.getvalue()).decode()
                            
                            all_images_html_list.append(
                                f'<img src="data:image/png;base64,{bc_image_b64}" style="width: {bc_width_px}px; height: {bc_height_px}px;">'
                            )
                        except Exception as e:
                            # Hiển thị lỗi nếu không tạo được barcode
                            logger.error(f"Failed to generate 1D barcode for '{bc_content_item}': {e}")
                            all_images_html_list.append(
                                f'<div style="width: {bc_width_px}px; height: {bc_height_px}px; border: 1px dashed red; color: red; font-size: 9pt; word-wrap: break-word; overflow: hidden; margin-bottom: {int(2*px_per_mm)}px;">'
                                f'Error: Could not generate barcode for:<br>{html.escape(str(bc_content_item))}'
                                f'</div>'
                            )
                
                all_images_html_str = "".join(all_images_html_list)
                image_html_block = f"""
                <div style="flex-shrink: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;">
                    {all_images_html_str}
                </div>
                """
            
            text_orientation_style = ""
            if text_orientation == "Vertical":
                text_orientation_style = "writing-mode: vertical-rl; transform: rotate(180deg);"
            
            text_div_html = ""
            if text_html_content and text_html_content.strip() != "":
                text_div_html = f"""
                <div style="flex-grow: 1; padding-right: {int(5*px_per_mm)}px; min-width: 0; {text_orientation_style}">
                    {text_html_content}
                </div>
                """
            
            label_html = textwrap.dedent(f"""
                <div style="
                    width: {preview_width_px}px; height: {preview_height_px}px;
                    padding: {margin_top_px}px {margin_right_px}px {margin_bottom_px}px {margin_left_px}px;
                    border: 2px solid #ccc; background-color: white; color: black;
                    font-family: Arial, sans-serif; font-size: {font_size*0.9}pt; 
                    overflow: hidden; box-sizing: border-box; display: flex;
                    justify-content: space-between; align-items: center;
                ">
                    <div style="max-height: {preview_height_px - margin_top_px - margin_bottom_px}px; 
                        max-width: {preview_width_px - margin_left_px - margin_right_px}px; overflow: hidden">{text_div_html}</div>
                    {image_html_block} 
                </div>
            """)
            
            st.markdown(label_html, unsafe_allow_html=True)

        st.markdown("---")

        col_printer, col_copies = st.columns([3, 1])

        with col_printer:
            printers = printer_svc.get_printers()
            godex_printer_index = None
            if printers:
                for i, p in enumerate(printers):
                    if "Godex G500" in p:
                        godex_printer_index = i
                        break
            
            selected_printer = st.selectbox(
                "🖨️ Select printer:",
                printers,
                index=godex_printer_index if godex_printer_index is not None else 0,
                help="Danh sách máy in đã được cài đặt trên máy tính Windows của bạn"
            )
            if not printers:
                st.warning("Printer not found. Please install printer driver", icon="🚨")
        
        with col_copies:
            num_copies = st.number_input("Copies", min_value=1, value=max(1, int(number_of_labels)), step=1, disabled=True)
        
        st.write("") 

        # === KHỞI TẠO BẢN ĐỒ TÊN (NAME MAP) TỔNG HỢP ===

        field_code_to_name = labels_svc.get_system_field_map()

        # Tải và cập nhật các trường ĐỘNG (từ get_label_content_fields)
        # Các trường này sẽ GHI ĐÈ tên mặc định nếu 'field_code' bị trùng.
        db_fields = {
            f.get('field_code'): f.get('field_name') 
            for f in content_fields_for_preview 
            if f.get('field_code') and f.get('field_name')
        }
        field_code_to_name.update(db_fields)
        
        col1_btn, col2_btn, col3_btn = st.columns([2, 2, 2]) 
        with col1_btn:
            st.button("⬅️ Back to Select Product", on_click=switch_to_select_product_tab, width='stretch')
        
        with col2_btn:
            st.button(
                "🖨️ Print Godex G500",
                type="primary",
                disabled=not selected_printer if printers else True,
                key="print_button",
                width='stretch'
            )
        
        with col3_btn:
            qr_field_names = [field_code_to_name.get(code, code) for code in qr_field_codes]
            ezpx_data = printer_svc.generate_ezpx_xml(
                label_type_name=lt_name, label_data=label_info,
                qr_codes=qr_codes, qr_field_names=qr_field_names,
                paper_width_mm=paper_width, paper_height_mm=paper_height,
                font_size_pt=font_size,
                margins_mm=(margin_top, margin_bottom, margin_left, margin_right),
                qr_size_mm=(qr_width_mm, qr_height_mm), num_copies=num_copies
            )
            
            st.download_button(
                label="💾 Save Label (EZPX)", data=ezpx_data,
                file_name=f"{lt_name.replace(' ', '_')}.ezpx", mime="application/xml",
                width='stretch'
            )

        if st.session_state.get("print_button"):

            # Kiểm tra xem đây có phải là trường hợp in PACKAGE_LABEL từ History không
            is_package_print_from_history = (
                label_template == "PACKAGE_LABEL" and 
                st.session_state.get("is_package_from_history", False)
            )

            if is_package_print_from_history:
                all_display_fields = list(label_info.keys())
            
            else:
                all_display_fields = []
                for field in content_fields_for_preview:
                    if field.get('field_code'):
                        all_display_fields.append(field.get('field_code'))

            zpl_commands = printer_svc.generate_zpl_commands( 
                label_data=label_info,
                qr_codes=qr_codes, 
                qr_field_codes=qr_field_codes,
                paper_width_mm=paper_width, 
                paper_height_mm=paper_height,
                font_size_pt=font_size,
                margins_mm=(margin_top, margin_bottom, margin_left, margin_right),
                qr_size_mm=(qr_width_mm, qr_height_mm),
                barcodes_1d=barcodes_1d,
                barcode_1d_field_codes=barcode_1d_field_codes,
                barcode_1d_size_mm=(barcode_1d_width_mm, barcode_1d_height_mm),
                num_copies=num_copies,
                field_order=all_display_fields,
                text_orientation=text_orientation,
                display_name_map=field_code_to_name
            )

            success, message = printer_svc.send_raw_data_to_printer(selected_printer, zpl_commands)

            print_status = "SUCCESS" if success else "FAILED"
            error_msg = message if not success else None

            printed_by_user = st.session_state.get("username", "system_user")

            # Lọc dữ liệu dựa trên all_display_fields đã được mở rộng
            # filtered_printed_data = {key: label_info.get(key) for key in all_display_fields if key in label_info}
            filtered_printed_data = {}
            for key in all_display_fields:
                if key in label_info:
                    value = label_info.get(key)
                    # Chuyển đổi date/datetime thành chuỗi ISO 8601 (ví dụ: '2025-10-27')
                    if isinstance(value, (datetime, date)):
                        filtered_printed_data[key] = value.isoformat()
                    else:
                        filtered_printed_data[key] = value

            history_data = {
                # Các trường bắt buộc
                "requirement_id": selected_requirement.get('id') if selected_requirement else None,
                "customer_id": customer_id,
                'entity_id': entity_id,
                "label_type": label_template,
                "printed_by": printed_by_user,

                # Các trường theo yêu cầu
                "customer_name": product_info.get('customer'),
                "legal_entity": product_info.get('legal_entity'),
                # Lấy dữ liệu đã gộp từ label_info nếu là package, nếu không thì lấy từ product_info
                "dn_number": product_info.get('dn_number'), 
                "product_pn": product_info.get('product_pn'),
                "pt_code": product_info.get('pt_code'),
                "selling_quantity": product_info.get('total_selling_qty'),
                "standard_quantity": qty_per_carton if label_template in ["CARTON_LABEL", "ITEM_LABEL"] else 1,
                "label_size": f"{paper_width}x{paper_height}mm",
                "printed_data": filtered_printed_data, # Dict chứa TẤT CẢ dữ liệu đã in
                "print_status": print_status,
                
                # Các trường hữu ích khác
                "printer_name": selected_printer,
                "print_quantity": num_copies,
                "error_message": error_msg
            }

            hist_success, hist_msg, new_hist_id = labels_svc.add_label_print_history(history_data)

            if not hist_success:
                st.error(f"LỖI LƯU LỊCH SỬ: {hist_msg}")
            
            if success:
                st.success(message)
            else:
                st.error(message)

    else:
        st.warning("No products selected yet. Please return to tab '📦 Select Product' to get started", icon="🚨") 
        st.button("⬅️ Back to Select Product", on_click=switch_to_select_product_tab)

# --- TAB 3: LỊCH SỬ IN TEM ---
elif tab_selection == "⌛ History Label Printing":
    
    st.subheader("⌛ History of label printing")

    # Tải dữ liệu
    @st.cache_data(ttl=600)
    def load_customers_for_history():
        all_customers = [{"customer_id": None, "customer_english_name": "All customers", "customer_code": ""}]
        all_customers.extend(labels_svc.get_active_customers())
        return all_customers

    customers_list = load_customers_for_history()

    @st.cache_data(ttl=600)
    def load_entity_for_history():
        all_entities = [{"entity_id": None, "entity_english_name": "All entities", "entity_code": ""}]
        all_entities.extend(labels_svc.get_active_entities())
        return all_entities

    entities_list = load_entity_for_history()

    with st.expander("🔍 Search and Filter", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            today = datetime.now().date()
            seven_days_ago = today - timedelta(days=7)
            date_range = st.date_input(
                "Printed Date",
                value=(seven_days_ago, today),
                key="history_date_range",
                help="Chọn khoảng thời gian tìm kiếm"
            )
            start_date = date_range[0] if date_range and len(date_range) > 0 else seven_days_ago
            end_date = date_range[1] if date_range and len(date_range) > 1 else today

            selected_customer_hist = st.selectbox(
                "*Customer",
                options=customers_list,
                format_func=lambda c: f"{c['customer_english_name']}" + (f" ({c['customer_code']})" if c['customer_code'] else ""),
                key="history_customer"
            )

            selected_entity_hist = st.selectbox(
                "*Entity",
                options=entities_list,
                format_func=lambda c: f"{c['entity_english_name']}" + (f" ({c['entity_code']})" if c['entity_code'] else ""),
                key="history_entity"
            )
    
        with col2:
            dn_filter = st.text_input("DN Number", placeholder="Enter DN Number...")

            label_type_options = ["All", "ITEM_LABEL", "CARTON_LABEL", "PACKAGE_LABEL"]

            label_type_filter = st.selectbox("*Label Type", label_type_options, key="history_label_type")

        with col3:
            pt_code_filter = st.text_input("PT Code", placeholder="Enter PT Code...")

            status_options = ["All", "SUCCESS", "FAILED", "CANCELLED"]
            status_filter = st.selectbox("Print Status", status_options, key="history_status")

    # Hiển thị dữ liệu

    # Tải dữ liệu
    @st.cache_data(ttl=60)
    def fetch_history_data(start_date, end_date, customer_id, entity_id, dn_number, pt_code, print_status, label_type):
        try:
            return labels_svc.get_label_print_history(
                start_date=start_date,
                end_date=end_date,
                customer_id=customer_id,
                entity_id=entity_id,
                dn_number=dn_number,
                pt_code=pt_code,
                print_status=print_status,
                label_type=label_type
            )
        except Exception as e:
            st.error(f"An error occurred while loading data: {e}")
            return []

    customer_id_filter_val = selected_customer_hist.get('customer_id')
    entity_id_filter_val = selected_entity_hist.get('entity_id')
    dn_filter_val = dn_filter if dn_filter else None
    pt_code_filter_val = pt_code_filter if pt_code_filter else None
    status_filter_val = status_filter if status_filter != "All" else None
    label_type_filter_val = label_type_filter if label_type_filter != "All" else None

    history_data = fetch_history_data(
        start_date=start_date,
        end_date=end_date,
        customer_id=customer_id_filter_val,
        entity_id=entity_id_filter_val,
        dn_number=dn_filter_val,
        pt_code=pt_code_filter_val,
        print_status=status_filter_val,
        label_type=label_type_filter_val
    )

    if history_data:
        df_history = pd.DataFrame(history_data)

        display_columns = [
            'printed_date', 
            'customer_name', 
            'legal_entity',
            'dn_number', 
            'product_pn', 
            'pt_code', 
            'selling_quantity',
            'standard_quantity',
            'print_quantity', 
            'label_type', 
            'label_size', 
            'print_status', 
            'printed_by', 
            'printed_data'
        ]

        final_columns = [col for col in display_columns if col in df_history.columns]
        df_display = df_history[final_columns].copy()

        st.success(f"Found {len(df_display)} results")

        gb = GridOptionsBuilder.from_dataframe(df_display)

        is_customer_selected = customer_id_filter_val is not None

        is_entity_selected = entity_id_filter_val is not None

        if is_customer_selected and is_entity_selected and label_type_filter_val == 'CARTON_LABEL':
            gb.configure_selection(
                'multiple',
                use_checkbox=True,
                header_checkbox=True,
                groupSelectsChildren=True
            )
        else:
            gb.configure_selection(
                'multiple',
                use_checkbox=False,
                header_checkbox=False,
                groupSelectsChildren=False
            )

        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_side_bar(filters_panel=True, columns_panel=True)
        gb.configure_default_column(
            resizable=True, filterable=True, sortable=True, 
            wrapText=True, autoHeight=True
        )

        # Định dạng cột ngày
        gb.configure_column(
            "printed_date", 
            headerName="Printed Date",
            type=["dateColumn", "nonEditableColumn"], 
            custom_format_string='yyyy-MM-dd HH:mm:ss', 
            width=200,
            sort='desc'
        )

        # Định dạng cột JSON
        gb.configure_column("printed_data", headerName="Printed Data", width=300)

        gridOptions = gb.build()

        if not is_customer_selected or not is_entity_selected or not label_type_filter_val == 'CARTON_LABEL':
            st.info("ℹ️ Please select a customer, entity and label type CARTON_LABEL to be able to select labels")

        grid_response_history = AgGrid(
            df_display,
            gridOptions=gridOptions,
            data_return_mode=DataReturnMode.AS_INPUT,
            update_on=['selectionChanged'], 
            fit_columns_on_grid_load=False,
            height=500,
            width='100%',
            key='history_grid',
            allow_unsafe_jscode=True,
        )
        selected_rows_data = grid_response_history.get('selected_rows')
        
        if isinstance(selected_rows_data, pd.DataFrame):
            is_row_selected = not selected_rows_data.empty
        elif isinstance(selected_rows_data, list):
            is_row_selected = len(selected_rows_data) > 0
        else:
            is_row_selected = False

        button_disabled = not (is_customer_selected and is_row_selected)

        st.button(
            "📦 Create Package Label",
            disabled=button_disabled,
            type="primary",
            key="create_package_label_hist",
            width='stretch'
        )

        # XỬ LÝ SỰ KIỆN CLICK NÚT "CREATE PACKAGE LABEL"
        if st.session_state.get("create_package_label_hist"):
            # 1. Lấy dữ liệu đã chọn
            if isinstance(selected_rows_data, pd.DataFrame):
                selected_df = selected_rows_data
            elif isinstance(selected_rows_data, list):
                selected_df = pd.DataFrame(selected_rows_data)
            else:
                selected_df = pd.DataFrame()

            if not selected_df.empty:
                # 2. Lấy Customer ID (đã được chọn trong bộ lọc)
                customer_id_for_pkg = customer_id_filter_val # Đây là ID
                customer_name_for_pkg = selected_customer_hist.get('customer_english_name', 'N/A')

                entity_id_for_pkg = entity_id_filter_val
                entity_name_for_pkg = selected_entity_hist.get('entity_english_name', 'N/A')

                try:
                    total_std_qty_sum = selected_df['standard_quantity'].sum()
                    total_sel_qty_sum = selected_df['selling_quantity'].sum()
                except Exception as e:
                    st.error(f"Lỗi khi tính tổng số lượng: {e}. Đặt tạm bằng 0.")
                    total_std_qty_sum = 1
                    total_sel_qty_sum = 1

                # 3. Tổng hợp dữ liệu để "giả lập" một product_info cho Tab 2
                package_product_info = {
                    'customer': customer_name_for_pkg,
                    'legal_entity': ', '.join(selected_df['legal_entity'].astype(str).unique()),
                    'dn_number': ', '.join(selected_df['dn_number'].astype(str).unique()),
                    'product_pn': ', '.join(selected_df['product_pn'].astype(str).unique()),
                    'product_mapped_code': 'N/A',
                    'product_mapped_name': 'N/A',
                    'pt_code': ', '.join(selected_df['pt_code'].astype(str).unique()),
                    'batch_no': 'N/A',
                    'package_size': 'N/A',
                    'shelf_life': 'N/A',
                    'total_standard_qty': total_std_qty_sum, 
                    'total_selling_qty': total_sel_qty_sum, 
                    'brand': 'N/A'
                }
                
                # 4. Cập nhật session_state để Tab 2 sử dụng
                st.session_state.product_for_label = package_product_info
                st.session_state.customer_id_for_label = customer_id_for_pkg
                st.session_state.entity_id_for_label = entity_id_for_pkg

                # Đặt lại label_preview_data với thông tin cơ bản này
                st.session_state.label_preview_data = package_product_info.copy()

                # Lấy danh sách các hàng đã chọn
                selected_rows_list = selected_df.to_dict('records')

                # Đặt cờ và dữ liệu cho chế độ preview đặc biệt
                st.session_state.is_package_from_history = True
                st.session_state.package_history_data = selected_rows_list

                # GỬI TÍN HIỆU qua Tab 2 để tự động chọn "PACKAGE_LABEL"
                st.session_state.default_label_type_override = "PACKAGE_LABEL"

                # 5. Chuyển tab
                st.session_state.next_tab = "👁️‍🗨️ Preview and Create Label"

                # 6. Rerun để thay đổi có hiệu lực
                st.rerun()
        
        if button_disabled:
            if not is_customer_selected:
                pass
            elif not is_row_selected:
                st.caption("ℹ️ *Please select at least one row in the grid to create a Package Label.*")

    else:
        st.info("No records were found matching the search criteria")
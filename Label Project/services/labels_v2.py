#services/labels_v2.py

from utils.db import get_db_engine
from sqlalchemy import text, exc
import logging
import streamlit as st
from datetime import date
from typing import Dict, Any, List, Optional
import json
from utils.s3_utils import S3Manager

logger = logging.getLogger(__name__)

# Initialize S3
try:
    s3_manager = S3Manager()
except Exception as e:
    st.error("Unable to connect to file storage service. Please contact support.")
    logger.error(f"S3 initialization failed: {e}")
    st.stop()

def get_active_customers() -> List[Dict[str, Any]]:
    """Lấy danh sách tất cả các khách hàng đang hoạt động."""
    try:
        engine = get_db_engine()
        
        summary_query = text("""
        SELECT
            c.id as customer_id,
            c.local_name as customer_local_name,
            c.english_name as customer_english_name,
            c.company_code as customer_code,
            ct.name as company_type
        FROM companies AS c
        JOIN companies_company_types AS cct ON c.id = cct.companies_id
        JOIN company_types AS ct ON ct.id = cct.company_type_id
        WHERE ct.name = "customer"
        ORDER BY c.english_name
        """)
        
        with engine.connect() as conn:
            results = conn.execute(summary_query).fetchall()
        
        if results:
            customers_list = [
                {
                    'customer_id': int(row.customer_id or 0),
                    'customer_local_name': str(row.customer_local_name or "N/A"),
                    'customer_english_name': str(row.customer_english_name or "N/A"),
                    'customer_code': str(row.customer_code or "N/A"),
                    'company_type': str(row.company_type or "N/A")
                }
                for row in results
            ]
            return customers_list
            
    except Exception as e:
        logger.error(f"Failed to get customer list: {e}")
        st.error("Không thể tải dữ liệu khách hàng. Vui lòng thử lại.")
    
    return []


def get_active_entities() -> List[Dict[str, Any]]:
    """Lấy danh sách tất cả các khách hàng đang hoạt động."""
    try:
        engine = get_db_engine()
        
        summary_query = text("""
        SELECT 
            c.id as entity_id, 
            c.local_name as entity_local_name, 
            c.english_name as entity_english_name, 
            c.company_code as entity_code, 
            ct.name as company_type
        FROM companies AS c
        JOIN companies_company_types AS cct ON c.id = cct.companies_id
        JOIN company_types AS ct ON ct.id = cct.company_type_id
        WHERE ct.name = "internal"
        ORDER BY c.english_name
        """)
        
        with engine.connect() as conn:
            results = conn.execute(summary_query).fetchall()
        
        if results:
            entity_list = [
                {
                    'entity_id': int(row.entity_id or 0),
                    'entity_local_name': str(row.entity_local_name or "N/A"),
                    'entity_english_name': str(row.entity_english_name or "N/A"),
                    'entity_code': str(row.entity_code or "N/A"),
                    'company_type': str(row.company_type or "N/A")
                }
                for row in results
            ]
            return entity_list
            
    except Exception as e:
        logger.error(f"Failed to get entity list: {e}")
        st.error("Không thể tải dữ liệu khách hàng. Vui lòng thử lại.")
    
    return []


def get_dns_for_customer_and_entity(customer_code: str, entity_code: str) -> List[Dict[str, Any]]:

    if not customer_code or not entity_code:
        logger.warning("Customer Code or entity Code is not provided.")
        return []
        
    try:
        engine = get_db_engine()
        
        query = text("""
            SELECT DISTINCT dfv.dn_number
            FROM delivery_full_view AS dfv
            WHERE 
                dfv.shipment_status = 'STOCKED_OUT'
                AND dfv.customer_code = :customer_code
                AND dfv.legal_entity_code = :entity_code
            ORDER BY dfv.dn_number
        """)
        
        with engine.connect() as conn:
            # Truyền tham số là các code
            params = {"customer_code": customer_code, "entity_code": entity_code}
            results = conn.execute(query, params).fetchall()
        
        if results:
            dn_list = [row.dn_number for row in results]
            return dn_list
            
    except Exception as e:
        logger.error(f"Failed to get DN list for customer code {customer_code} and entity code {entity_code}: {e}")
        st.error("Không thể tải danh sách DN. Vui lòng thử lại.")
    
    return []


def get_products_by_dns(dn_numbers: list[str], group_by_batch_no: bool = True) -> List[Dict[str, Any]]:
    if not dn_numbers:
        logger.warning("No DN numbers provided to get_products_by_dns.")
        return []

    try:
        engine = get_db_engine()
        
        # Cấu hình câu truy vấn dựa trên lựa chọn grouping
        if group_by_batch_no:
            batch_no_select = "ih.batch_no"
            group_by_clause = "GROUP BY dfv.product_id, TRIM(ih.batch_no), dfv.dn_number"
        else:
            # GROUP_CONCAT gộp nhiều batch_no thành một chuỗi, phân tách bởi dấu phẩy
            batch_no_select = "GROUP_CONCAT(DISTINCT TRIM(ih.batch_no) SEPARATOR ', ') AS batch_no"
            group_by_clause = "GROUP BY dfv.product_id, dfv.dn_number"

        # Sử dụng f-string để chèn các phần đã cấu hình vào câu query chính
        query_string = f"""
            SELECT
                dfv.dn_number, dfv.customer, dfv.legal_entity, dfv.pt_code, dfv.product_pn, {batch_no_select},
                dfv.package_size, dfv.brand, p.shelf_life, p.uom,
                SUM(DISTINCT dfv.standard_quantity) as total_standard_qty, 
                SUM(DISTINCT dfv.selling_quantity) as total_selling_qty,
                pcm.code AS product_mapped_code, pcm.mapped_name AS product_mapped_name
            FROM
                delivery_full_view AS dfv
            JOIN 
				order_comfirmation_details AS ocd ON dfv.oc_line_id = ocd.id
			JOIN
				quotation_details AS qd ON ocd.quotation_detail_id = qd.id
			JOIN
				product_code_mappings AS pcm ON qd.product_code_mapping_id = pcm.id
            JOIN
                products AS p ON dfv.product_id = p.id
            JOIN
                stock_out_delivery_request_details AS sodrd ON dfv.delivery_id = sodrd.delivery_id
            JOIN
                inventory_histories AS ih ON sodrd.id = ih.action_detail_id
            WHERE
                ih.type = 'stockOutDelivery' 
                AND dfv.shipment_status = 'STOCKED_OUT'
                AND dfv.dn_number IN :selected_dns
            {group_by_clause}
            ORDER BY
                dfv.product_pn
        """
        
        query = text(query_string)

        with engine.connect() as conn:
            params = {"selected_dns": tuple(dn_numbers)}
            results = conn.execute(query, params).fetchall()
        
        if results:
            products_list = [
                {
                    'dn_number': str(row.dn_number or "N/A"),
                    'customer': str(row.customer or "N/A"),
                    'legal_entity': str(row.legal_entity or "N/A"),
                    'pt_code': str(row.pt_code or "N/A"),
                    'product_pn': str(row.product_pn or "N/A"),
                    'batch_no': str(row.batch_no or "N/A"),
                    'package_size': str(row.package_size or "N/A"),
                    'brand': str(row.brand or "N/A"),
                    'shelf_life': int(row.shelf_life or 0),
                    'uom': str(row.uom or "N/A"),
                    'total_standard_qty': float(row.total_standard_qty or 0.0),
                    'total_selling_qty': float(row.total_selling_qty or 0.0),
                    'product_mapped_code': str(row.product_mapped_code or "N/A"),
                    'product_mapped_name': str(row.product_mapped_name or "N/A"),
                }
                for row in results
            ]
            return products_list
            
    except Exception as e:
        logger.error(f"Failed to get products for DNs {dn_numbers} with grouping option: {e}")
        st.error("Không thể tải dữ liệu sản phẩm. Vui lòng thử lại.")
    
    return []


def get_customer_label_requirements(customer_id: int) -> List[Dict[str, Any]]:

    if not customer_id:
        logger.warning("Customer ID is not provided to get label requirements.")
        return []

    try:
        engine = get_db_engine()
        
        # Câu query để lấy các yêu cầu đang hoạt động và còn hiệu lực
        query = text("""
            SELECT
                id,
                customer_id,
                customer_code,
                customer_name,
                requirement_name,
                requirement_type,
                label_size,
                printer_dpi,
                printer_type,
                requirement_file_s3_key,
                sample_file_s3_key,
                special_notes,
                status,
                effective_from,
                effective_to,
                version
            FROM
                customer_label_requirements
            WHERE
                customer_id = :customer_id
                AND status = 'ACTIVE'
            ORDER BY
                requirement_type, requirement_name;
        """)

        with engine.connect() as conn:
            params = {"customer_id": customer_id, "current_date": date.today()}
            results = conn.execute(query, params).fetchall()

        if results:
            requirements_list = [
                {
                    'id': row.id,
                    'customer_id': row.customer_id,
                    'customer_code': str(row.customer_code or ''),
                    'customer_name': str(row.customer_name or ''),
                    'requirement_name': str(row.requirement_name or ''),
                    'requirement_type': str(row.requirement_type or ''),
                    'label_size': str(row.label_size or ''),
                    'printer_dpi': int(row.printer_dpi or 0),
                    'printer_type': str(row.printer_type or ''),
                    'requirement_file_s3_key': str(row.requirement_file_s3_key or ''),
                    'sample_file_s3_key': str(row.sample_file_s3_key or ''),
                    'special_notes': str(row.special_notes or ''),
                    'status': str(row.status or ''),
                    'effective_from': row.effective_from,
                    'effective_to': row.effective_to,
                    'version': int(row.version or 1)
                }
                for row in results
            ]
            return requirements_list

    except Exception as e:
        logger.error(f"Failed to get label requirements for customer ID {customer_id}: {e}")
        st.error("Không thể tải dữ liệu yêu cầu nhãn. Vui lòng thử lại.")

    return []


def create_customer_label_requirement(requirement_data: Dict[str, Any]) -> tuple[bool, str, int | None]:

    try:
        engine = get_db_engine()
        
        insert_query = text("""
            INSERT INTO customer_label_requirements (
                customer_id, customer_code, customer_name, requirement_name, 
                requirement_type, label_size, printer_dpi, printer_type, 
                special_notes, status, effective_from, effective_to, created_by
            ) VALUES (
                :customer_id, :customer_code, :customer_name, :requirement_name, 
                :requirement_type, :label_size, :printer_dpi, :printer_type, 
                :special_notes, :status, :effective_from, :effective_to, :created_by
            )
        """)
        
        # Lấy thông tin customer từ DB để đảm bảo dữ liệu nhất quán
        customer_info = next((c for c in get_active_customers() if c['customer_id'] == requirement_data.get("customer_id")), {})
        
        params = {
            "customer_id": requirement_data.get("customer_id"),
            "customer_code": customer_info.get("customer_code"),
            "customer_name": customer_info.get("customer_english_name"),
            "requirement_name": requirement_data.get("requirement_name"),
            "requirement_type": requirement_data.get("requirement_type"),
            "label_size": requirement_data.get("label_size"),
            "printer_dpi": requirement_data.get("printer_dpi"),
            "printer_type": requirement_data.get("printer_type"),
            "special_notes": requirement_data.get("special_notes"),
            "status": requirement_data.get("status", "DRAFT"),
            "effective_from": requirement_data.get("effective_from"),
            "effective_to": requirement_data.get("effective_to"),
            "created_by": requirement_data.get("created_by")
        }

        with engine.connect() as conn:
            with conn.begin() as transaction:
                result = conn.execute(insert_query, params)
                new_id = result.lastrowid
                transaction.commit()
                msg = f"Successfully created new label requirement with ID: {new_id}"
                logger.info(msg)
                return True, msg, new_id

    except exc.SQLAlchemyError as e:
        logger.error(f"Database error during insert: {e}")
        msg = f"Database Error: Could not create the requirement. Details: {e}"
        return False, msg, None
    except Exception as e:
        logger.error(f"An unexpected error occurred in create_customer_label_requirement: {e}")
        msg = f"An unexpected error occurred: {e}"
        return False, msg, None


def get_label_content_fields(requirement_id: int) -> List[Dict[str, Any]]:

    if not requirement_id:
        logger.warning("Requirement ID is not provided to get label content fields.")
        return []

    try:
        engine = get_db_engine()
        
        query = text("""
            SELECT
                id,
                requirement_id,
                field_code,
                field_name,
                field_type,
                data_source,
                format_pattern,
                sample_value,
                display_order,
                is_required,
                special_rules
            FROM
                label_content_fields
            WHERE
                requirement_id = :requirement_id
            ORDER BY
                display_order, field_name;
        """)

        with engine.connect() as conn:
            params = {"requirement_id": requirement_id}
            results = conn.execute(query, params).fetchall()

        if results:
            fields_list = [
                {
                    'id': row.id,
                    'requirement_id': row.requirement_id,
                    'field_code': str(row.field_code or ''),
                    'field_name': str(row.field_name or ''),
                    'field_type': str(row.field_type or ''),
                    'data_source': str(row.data_source or ''),
                    'format_pattern': str(row.format_pattern or ''),
                    'sample_value': str(row.sample_value or ''),
                    'display_order': int(row.display_order or 999),
                    'is_required': bool(row.is_required),
                    'special_rules': str(row.special_rules or '')
                }
                for row in results
            ]
            return fields_list

    except Exception as e:
        logger.error(f"Failed to get label content fields for requirement ID {requirement_id}: {e}")
        st.error("Không thể tải dữ liệu chi tiết nội dung nhãn. Vui lòng thử lại.")

    return []


def add_label_content_field(field_data: Dict[str, Any]) -> tuple[bool, str, int | None]:

    try:
        engine = get_db_engine()
        
        insert_query = text("""
            INSERT INTO label_content_fields (
                requirement_id, field_code, field_name, field_type, data_source,
                format_pattern, sample_value, display_order, is_required, special_rules
            ) VALUES (
                :requirement_id, :field_code, :field_name, :field_type, :data_source,
                :format_pattern, :sample_value, :display_order, :is_required, :special_rules
            )
        """)
        
        required_keys = ["requirement_id", "field_code", "field_name", "field_type"]
        if not all(key in field_data and field_data[key] is not None for key in required_keys):
            missing = [key for key in required_keys if key not in field_data or field_data[key] is None]
            error_msg = f"Missing required fields: {', '.join(missing)}"
            logger.error(error_msg)
            return False, error_msg, None
            
        with engine.connect() as conn:
            with conn.begin() as transaction:
                result = conn.execute(insert_query, field_data)
                new_id = result.lastrowid
                transaction.commit()
                msg = f"Successfully added a new label content field with ID: {new_id}"
                logger.info(msg)
                return True, msg, new_id

    except exc.IntegrityError as e:
        logger.error(f"Integrity error adding label field: {e}")
        transaction.rollback()
        msg = "Error: Field Code already exists for this requirement. Please choose a different code."
        return False, msg, None
    except exc.SQLAlchemyError as e:
        logger.error(f"Database error adding label field: {e}")
        transaction.rollback()
        msg = f"Database Error: Could not add the content field. Details: {e}"
        return False, msg, None
    except Exception as e:
        logger.error(f"An unexpected error occurred in add_label_content_field: {e}")
        msg = f"An unexpected error occurred: {e}"
        return False, msg, None


def get_system_field_map() -> Dict[str, str]:
    """
    Trả về một bản đồ (dictionary) các mã trường hệ thống/cố định 
    và tên hiển thị mặc định của chúng.
    
    Đây là các trường đến từ 'product_info' hoặc 'history_data', 
    không phải các trường động do người dùng định nghĩa.
    """
    return {
        # Các trường từ get_products_by_dns (dùng cho product_info)
        'customer': 'Customer',
        'dn_number': 'DN',
        'legal_entity': 'Entity',
        'product_pn': 'Product Code',
        'pt_code': 'PT Code',
        'batch_no': 'Batch No',
        'package_size': 'Package Size',
        'brand': 'Brand',
        'shelf_life': 'Shelf Life',
        'total_standard_qty': 'Total Standard Qty',
        'total_selling_qty': 'Total Selling Qty',
        'product_mapped_code': 'Vendor Product Code',
        'product_mapped_name': 'Vendor Product Name',
        
        # Các trường bổ sung từ get_label_print_history (phòng trường hợp gộp)
        'customer_name': 'Customer', # (customer_name là alias của customer)
        'selling_quantity': 'Selling Qty',
        'standard_quantity': 'Standard Qty',
        'print_quantity': 'Print Qty',
        'label_size': 'Label Size',
        'printed_by': 'Printed By',
        'printed_date': 'Printed Date'
    }


def get_label_print_history(       
    start_date: date, 
    end_date: date, 
    customer_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    dn_number: Optional[str] = None,
    pt_code: Optional[str] = None,
    print_status: Optional[str] = None,
    label_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    
    try:
        engine = get_db_engine()
        
        # Lấy tất cả các cột từ bảng
        base_query = """
            SELECT
                id, requirement_id, delivery_id, delivery_detail_id, 
                customer_id, customer_name, dn_number, 
                product_id, product_pn, pt_code, selling_quantity, 
                standard_quantity, label_type, 
                print_quantity, printed_data, printer_name, 
                print_status, error_message, 
                printed_by, printed_date,
                parent_print_id, label_size, legal_entity, entity_id
            FROM label_print_history
        """
        
        where_clauses = []
        params = {}
        
        # Lọc theo ngày (bắt buộc)
        # Sử dụng DATE() để so sánh phần ngày, bỏ qua phần thời gian
        where_clauses.append("DATE(printed_date) BETWEEN :start_date AND :end_date")
        params["start_date"] = start_date
        params["end_date"] = end_date

        # Thêm các bộ lọc tùy chọn
        if customer_id is not None:
            where_clauses.append("customer_id = :customer_id")
            params["customer_id"] = customer_id

        if entity_id is not None:
            where_clauses.append("entity_id = :entity_id")
            params["entity_id"] = entity_id
            
        if dn_number:
            where_clauses.append("dn_number = :dn_number")
            params["dn_number"] = dn_number

        if pt_code:
            where_clauses.append("pt_code = :pt_code")
            params["pt_code"] = pt_code
            
        if print_status:
            where_clauses.append("print_status = :print_status")
            params["print_status"] = print_status
            
        if label_type:
            where_clauses.append("label_type = :label_type")
            params["label_type"] = label_type

        # Ghép các điều kiện lọc
        query_string = f"{base_query} WHERE {' AND '.join(where_clauses)} ORDER BY printed_date DESC"
        
        query = text(query_string)
        
        with engine.connect() as conn:
            results = conn.execute(query, params).fetchall()
        
        if results:
            history_list = [
                {
                    'id': row.id,
                    'requirement_id': row.requirement_id,
                    'delivery_id': row.delivery_id,
                    'delivery_detail_id': row.delivery_detail_id,
                    'customer_id': row.customer_id,
                    'customer_name': str(row.customer_name or ''),
                    'dn_number': str(row.dn_number or ''),
                    'product_id': row.product_id,
                    'product_pn': str(row.product_pn or ''),
                    'pt_code': str(row.pt_code or ''),
                    'selling_quantity': row.selling_quantity,
                    'standard_quantity': row.standard_quantity,
                    'label_type': str(row.label_type or ''),
                    'print_quantity': int(row.print_quantity or 0),
                    'printed_data': row.printed_data, # Dữ liệu JSON
                    'printer_name': str(row.printer_name or ''),
                    'print_status': str(row.print_status or ''),
                    'error_message': str(row.error_message or ''),
                    'printed_by': str(row.printed_by or ''),
                    'printed_date': row.printed_date, # Giữ nguyên kiểu timestamp
                    'parent_print_id': row.parent_print_id,
                    'label_size': str(row.label_size or ''),
                    'entity_id': row.entity_id,
                    'legal_entity': str(row.legal_entity or ''),
                }
                for row in results
            ]
            return history_list
            
    except Exception as e:
        logger.error(f"Failed to get label print history: {e}")
        st.error("Không thể tải lịch sử in tem. Vui lòng thử lại.")
    
    return []


def add_label_print_history(print_data: Dict[str, Any]) -> tuple[bool, str, int | None]:
    
    required_keys = ["requirement_id", "customer_id", "entity_id", "label_type", "printed_by"]
    if not all(key in print_data and print_data[key] is not None for key in required_keys):
        missing = [key for key in required_keys if key not in print_data or print_data[key] is None]
        error_msg = f"Missing required fields: {', '.join(missing)}"
        logger.error(error_msg)
        return False, error_msg, None

    try:
        engine = get_db_engine()
        
        all_table_columns = [
            "requirement_id", "delivery_id", "delivery_detail_id", "customer_id", "customer_name",
            "dn_number", "product_id", "product_pn", "pt_code",
            "selling_quantity", "standard_quantity", "label_type",
            "print_quantity", "printed_data", "printer_name",
            "print_status", "error_message", "printed_by",
            "parent_print_id", "label_size", "legal_entity", "entity_id"
        ]
        
        insert_cols = [col for col in all_table_columns if col in print_data]
        
        # Xử lý đặc biệt cho 'printed_data' nếu nó là dict hoặc list
        # Chuyển đổi thành chuỗi JSON
        params = print_data.copy()
        if 'printed_data' in params and isinstance(params['printed_data'], (dict, list)):
            params['printed_data'] = json.dumps(params['printed_data'])

        # Chỉ giữ lại các tham số hợp lệ
        valid_params = {col: params[col] for col in insert_cols}

        # 3. Xây dựng câu query
        cols_str = ", ".join(insert_cols)
        params_str = ", ".join(f":{col}" for col in insert_cols)

        insert_query = text(f"""
            INSERT INTO label_print_history ({cols_str}) 
            VALUES ({params_str})
        """)

        # 4. Thực thi
        with engine.connect() as conn:
            with conn.begin() as transaction:
                result = conn.execute(insert_query, valid_params)
                new_id = result.lastrowid
                transaction.commit()
                msg = f"Successfully added label print history with ID: {new_id}"
                logger.info(msg)
                return True, msg, new_id

    except exc.IntegrityError as e:
        logger.error(f"Integrity error adding print history: {e}")
        msg = f"Database Error: Could not add history. Check Foreign Keys (e.g., requirement_id, customer_id). Details: {e}"
        return False, msg, None
    except exc.SQLAlchemyError as e:
        logger.error(f"Database error adding print history: {e}")
        msg = f"Database Error: Could not add history. Details: {e}"
        return False, msg, None
    except Exception as e:
        logger.error(f"An unexpected error occurred in add_label_print_history: {e}")
        msg = f"An unexpected error occurred: {e}"
        return False, msg, None
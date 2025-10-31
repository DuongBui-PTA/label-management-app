# services/form_builder.py
import streamlit as st
from typing import Dict, Any, List
import re # Thêm thư viện re để kiểm tra email

def render_dynamic_form(fields: List[Dict[str,Any]], initial:Dict[str,Any]|None=None) -> Dict[str,Any]:
    initial = initial or {}
    form_data: Dict[str,Any] = {}
    for f in fields:
        fname = f["field_name"]
        ftype = f.get("field_type","text")
        required = bool(f.get("is_required", False))
        maxlen = f.get("max_length")
        default = initial.get(fname) or f.get("default_value")

        label = f"{fname}" + (" *" if required else "")
        if ftype in ("text","email","phone","barcode","qr_code"):
            v = st.text_input(label, value=default or "", max_chars=maxlen if maxlen else None)
        elif ftype == "number":
            v = st.number_input(label, value=float(default) if (default not in (None,"")) else 0.0)
        elif ftype == "date":
            v = st.date_input(label, value=None)
        elif ftype == "textarea":
            v = st.text_area(label, value=default or "", max_chars=maxlen if maxlen else None, height=100)
        elif ftype == "checkbox":
            v = st.checkbox(label, value=bool(default) if default not in (None,"") else False)
        elif ftype == "select":
            opts = (default or "").split("|") if default else []
            v = st.selectbox(label, options=opts, index=0 if opts else None)
        else:
            v = st.text_input(label, value=default or "")

        # BỎ PHẦN VALIDATE TẠI ĐÂY ĐỂ TẬP TRUNG LOGIC VÀO HÀM VALIDATE_FORM
        # if required and (v is None or v == ""):
        #     st.caption(":red[Trường này bắt buộc.]")
            
        form_data[fname] = v
    return form_data


# MỚI: HÀM VALIDATE TẬP TRUNG
def validate_form(form_data: Dict[str, Any], fields_definition: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Xác thực dữ liệu form dựa trên định nghĩa các trường.

    Args:
        form_data (Dict[str, Any]): Dữ liệu người dùng đã nhập.
        fields_definition (List[Dict[str, Any]]): Danh sách các dictionary định nghĩa trường
                                                   (giống biến 'defined_fields' trong Label_Fields.py).

    Returns:
        Dict[str, str]: Một dictionary chứa các lỗi. Key là tên trường, value là thông báo lỗi.
                        Trả về dictionary rỗng nếu không có lỗi.
    """
    errors: Dict[str, str] = {}

    for field in fields_definition:
        field_name = field.get("field_name")
        is_required = bool(field.get("is_required"))
        field_type = field.get("field_type", "text")
        
        value = form_data.get(field_name)

        # 1. Kiểm tra trường bắt buộc
        # Chuyển value về string để .strip(), áp dụng cho text_input, number_input...
        if is_required and (value is None or str(value).strip() == ""):
            errors[field_name] = "is a required field, cannot be left blank"
            continue # Nếu đã lỗi required thì không cần kiểm tra các lỗi khác

        # 2. (Mở rộng) Kiểm tra các loại dữ liệu khác nếu cần
        if value and str(value).strip() != "":
            if field_type == "email":
                # Biểu thức chính quy đơn giản để kiểm tra email
                if not re.match(r"[^@]+@[^@]+\.[^@]+", str(value)):
                    errors[field_name] = "has invalid email format"

                elif field_type == "phone":
                # Loại bỏ các ký tự phổ biến như спейс, (), -, +
                    cleaned_phone = re.sub(r'[\s\+\-\(\)]', '', str(value))
                    if not cleaned_phone.isdigit() or not (9 <= len(cleaned_phone) <= 15):
                        errors[field_name] = "has invalid phone number format"
            
            # Thêm các quy tắc khác ở đây nếu muốn, ví dụ: phone, number format...

    return errors
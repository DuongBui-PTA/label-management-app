# services/printer.py
import streamlit as st
import html
from utils.s3_utils import S3Manager
import logging

logger = logging.getLogger(__name__)

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

@st.cache_data
def get_printers():
    """Lấy danh sách các máy in có sẵn trên hệ thống Windows."""
    if win32print is None:
        return []
    try:
        printers = [printer[2] for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
        return printers
    except Exception as e:
        st.error(f"Unable to get printer list: {e}")
        return []
    
def send_raw_data_to_printer(printer_name, raw_data):
    if win32print is None:
        return False, "❌ Printing is only supported on Windows."
    try:
        h_printer = win32print.OpenPrinter(printer_name)
        try:
            h_job = win32print.StartDocPrinter(h_printer, 1, ("Streamlit Label Job", None, "RAW"))
            try:
                win32print.StartPagePrinter(h_printer)
                win32print.WritePrinter(h_printer, raw_data.encode('utf-8'))
                win32print.EndPagePrinter(h_printer)
            finally:
                win32print.EndDocPrinter(h_printer)
        finally:
            win32print.ClosePrinter(h_printer)
        return True, "✅ Printed successfully"
    except Exception as e:
        return False, f"❌ Printing error: {e}"

def generate_zpl_commands(
    label_data, 
    qr_codes, 
    qr_field_codes, 
    paper_width_mm, 
    paper_height_mm, 
    font_size_pt, 
    margins_mm, 
    qr_size_mm, 
    barcodes_1d=None,
    barcode_1d_field_codes=None,
    barcode_1d_size_mm=(60, 15),
    num_copies=1,
    field_order=None,
    text_orientation="Horizontal",
    display_name_map=None
):
    
    # --- 1. KHỞI TẠO VÀ CHUYỂN ĐỔI ĐƠN VỊ ---
    DPI = 203
    IMAGE_SPACING_MM = 2  # Khoảng cách giữa các hình ảnh (QR/Barcode)
    LINE_SPACING_DOTS = 5 # Khoảng cách giữa các dòng văn bản

    if barcodes_1d is None: barcodes_1d = []
    if barcode_1d_field_codes is None: barcode_1d_field_codes = []
    if field_order is None: field_order = []
    
    active_display_map = display_name_map if display_name_map is not None else {}

    def mm_to_dots(mm):
        return int(mm * DPI / 25.4)

    def pt_to_dots(pt):
        return int(pt * DPI / 72)

    # Chuyển đổi tất cả kích thước sang "dots"
    paper_width_dots = mm_to_dots(paper_width_mm)
    paper_height_dots = mm_to_dots(paper_height_mm)
    margin_top_dots, margin_bottom_dots, margin_left_dots, margin_right_dots = [mm_to_dots(m) for m in margins_mm]
    qr_width_mm, _ = qr_size_mm
    qr_width_dots = mm_to_dots(qr_width_mm)
    barcode_1d_width_mm, barcode_1d_height_mm = barcode_1d_size_mm
    barcode_1d_width_dots = mm_to_dots(barcode_1d_width_mm)
    barcode_1d_height_dots = mm_to_dots(barcode_1d_height_mm)
    image_spacing_dots = mm_to_dots(IMAGE_SPACING_MM)
    font_size_dots = pt_to_dots(font_size_pt * 0.9)
    
    zpl_orientation = 'R' if text_orientation == "Vertical" else 'N'

    # --- 2. XỬ LÝ NỘI DUNG VĂN BẢN ---
    text_lines = []
    for key in field_order:
        value = label_data.get(key)
        
        if key in qr_field_codes or not value or str(value).strip() == '': 
            continue

        display_key = active_display_map.get(key, key) # Lấy tên hiển thị, nếu không có thì dùng key
        text_lines.append(f'{display_key}: {value}')
    
    num_lines = len(text_lines)
    # Số dòng tối đa cho ^FB, thêm 2 dòng đệm cho an toàn
    fb_max_lines = num_lines + 2 

    # --- 3. TÍNH TOÁN BỐ CỤC (LAYOUT) ---

    # Tính toán chiều rộng khối hình ảnh dựa trên MÃ RỘNG NHẤT
    image_block_width_dots = 0
    if qr_codes:
        image_block_width_dots = max(image_block_width_dots, qr_width_dots)
    if barcodes_1d:
        image_block_width_dots = max(image_block_width_dots, barcode_1d_width_dots)

    # Chiều rộng có sẵn cho nội dung (trong lề)
    available_content_width_dots = paper_width_dots - margin_left_dots - margin_right_dots
    
    # Khai báo các biến tọa độ và kích thước
    text_x_coord = 0
    text_block_height_for_centering = 0
    fb_width_param = 0 # Tham số chiều rộng cho lệnh ^FB
    image_x_coord = 0 # Tọa độ X bắt đầu của khối hình ảnh


    if zpl_orientation == 'N':
        
        if image_block_width_dots > 0:
            # Có hình ảnh: Văn bản bên trái, Hình ảnh bên phải
            fb_width_param = available_content_width_dots - image_block_width_dots - image_spacing_dots
            text_x_coord = margin_left_dots
            image_x_coord = paper_width_dots - margin_right_dots - image_block_width_dots
        else:
            # Chỉ có văn bản
            fb_width_param = available_content_width_dots
            text_x_coord = margin_left_dots
            image_x_coord = 0 # Không dùng
            
        fb_width_param = max(1, fb_width_param) # Đảm bảo không âm
        
        # *** [FIX 1] TÍNH CHIỀU CAO KHỐI VĂN BẢN CHÍNH XÁC ***
        if num_lines > 0:
            # Tính chiều cao thực tế dựa trên num_lines, không phải fb_max_lines
            text_block_height_for_centering = (font_size_dots * num_lines) + (LINE_SPACING_DOTS * (num_lines - 1))
        else:
            text_block_height_for_centering = 0
    
    else: # zpl_orientation == 'R'

        # Chiều rộng (trên tem) của khối văn bản xoay
        text_block_width_on_page = 0
        if num_lines > 0:
             # (Cỡ chữ + cách dòng) * số dòng (dùng fb_max_lines ở đây là đúng vì nó kiểm soát độ rộng)
            text_block_width_on_page = (font_size_dots + LINE_SPACING_DOTS) * fb_max_lines - LINE_SPACING_DOTS
        
        if image_block_width_dots > 0:
            # Có hình ảnh: Văn bản (xoay) bên trái, Hình ảnh bên phải
            
            # Tham số 'width' của ^FB (trở thành chiều cao)
            fb_width_param = available_content_width_dots - image_block_width_dots - image_spacing_dots
            
            # Tọa độ X là GÓC PHẢI của khối văn bản
            text_x_coord = margin_left_dots + text_block_width_on_page
            
            image_x_coord = paper_width_dots - margin_right_dots - image_block_width_dots
        else:
            # Chỉ có văn bản (xoay)
            fb_width_param = available_content_width_dots
            text_x_coord = margin_left_dots + text_block_width_on_page
            image_x_coord = 0 # Không dùng

        fb_width_param = max(1, fb_width_param)
        
        # Chiều cao khối văn bản (dùng để căn giữa) là tham số 'width' của ^FB
        # Logic này ĐÚNG cho văn bản xoay
        text_block_height_for_centering = fb_width_param

    # --- 4. TÍNH TOÁN CĂN GIỮA DỌC (TRỤC Y) ---
    
    # Tính tổng chiều cao khối HÌNH ẢNH
    total_image_height_dots = 0
    num_qrs = len(qr_codes)
    num_bcs = len(barcodes_1d)
    num_images = num_qrs + num_bcs

    if num_qrs > 0:
        total_image_height_dots += (qr_width_dots * num_qrs)
    if num_bcs > 0:
        total_image_height_dots += (barcode_1d_height_dots * num_bcs)
    if num_images > 1:
        total_image_height_dots += (image_spacing_dots * (num_images - 1))
    
    # *** [FIX 2] LOGIC CĂN GIỮA MỚI (Mô phỏng align-items: center) ***

    # Vùng nội dung có thể in (giữa lề trên và dưới)
    content_height_dots = paper_height_dots - margin_top_dots - margin_bottom_dots
    content_height_dots = max(1, content_height_dots) # Đảm bảo không âm

    # Lấy chiều cao thực tế của hai khối
    text_block_height = text_block_height_for_centering
    image_block_height = total_image_height_dots
    
    # Xác định khối cao nhất
    max_content_height = max(text_block_height, image_block_height)
    
    # Tính toán điểm Y bắt đầu chung để căn giữa KHỐI CAO NHẤT
    group_start_y = margin_top_dots
    if max_content_height > 0 and max_content_height < content_height_dots:
        group_start_y = margin_top_dots + (content_height_dots - max_content_height) / 2
    
    # Căn giữa từng khối BÊN TRONG nhóm đó (để khớp với 'align-items: center')
    text_start_y = group_start_y + (max_content_height - text_block_height) / 2
    image_y_start = group_start_y + (max_content_height - image_block_height) / 2

    text_start_y = int(text_start_y)
    image_y_start = int(image_y_start)

    # --- 5. TẠO LỆNH ZPL ---
    
    commands = []
    commands.append('^XA')
    commands.append('^CI28') # Hỗ trợ UTF-8
    commands.append(f'^PW{paper_width_dots}')
    commands.append(f'^LL{paper_height_dots}')
    # ^MMT = Chế độ Tear-off (xé giấy)
    # ^JMA = Tăng cường độ đen (nếu cần)
    # commands.append('^MMT') 
    # commands.append('^JMA')

    # 1. Vẽ khối văn bản
    if text_lines:
        full_text_content = "\\&\n".join(text_lines)
        justification = 'L' 
        
        commands.append(f'^FO{text_x_coord},{text_start_y}') 
        commands.append(f'^A0{zpl_orientation},{font_size_dots},{font_size_dots}')
        commands.append(f'^FB{fb_width_param},{fb_max_lines},{LINE_SPACING_DOTS},{justification},0')
        commands.append(f'^FD{full_text_content}')
        commands.append('^FS')

    # 2. Vẽ khối hình ảnh
    current_y = image_y_start # Biến theo dõi chiều cao Y hiện tại

    # 2a. Vẽ QR Codes
    if qr_codes:
        # Căn giữa QR trong khối hình ảnh
        qr_x = image_x_coord
        if image_block_width_dots > qr_width_dots:
            qr_x = image_x_coord + (image_block_width_dots - qr_width_dots) // 2
        
        # Logic tính độ phóng đại (magnification)
        # Model 2 (M2) QR Code có 29 "modules" (đơn vị) ở Version 1
        # Độ rộng (dots) / 29 = số dots / module. Đây là 'magnification'
        magnification = max(1, min(10, qr_width_dots // 29)) 
        
        for qr_content in qr_codes:
            commands.append(f'^FO{qr_x},{current_y}')
            commands.append(f'^BQN,2,{magnification}') # N=Normal, 2=Model 2, mag=...
            commands.append(f'^FDQM,A{qr_content}^FS') # QM=Chế độ cao, A=Tự động
            current_y += qr_width_dots + image_spacing_dots

    # 2b. Vẽ Barcodes 1D
    if barcodes_1d:
        # *** [FIX 3] THÊM LỆNH ^BY ĐỂ CHUẨN HÓA ĐỘ RỘNG MODULE ***
        # Đặt độ rộng module hẹp nhất là 2 dots. 
        # Điều này giúp barcode nhất quán, dù không đảm bảo khớp 100%
        # với barcode_1d_width_mm (vì preview đã "kéo dãn" ảnh)
        commands.append('^BY2') 

        # Căn giữa Barcode trong khối hình ảnh
        bc_x = image_x_coord
        if image_block_width_dots > barcode_1d_width_dots:
             bc_x = image_x_coord + (image_block_width_dots - barcode_1d_width_dots) // 2

        for bc_content in barcodes_1d:
            commands.append(f'^FO{bc_x},{current_y}')
            # ^BCN = Code 128, Normal, (height), No text, No text above
            commands.append(f'^BCN,{barcode_1d_height_dots},N,N,N') 
            commands.append(f'^FD{bc_content}^FS')
            current_y += barcode_1d_height_dots + image_spacing_dots

    commands.append(f'^PQ{num_copies}') # Số lượng bản in
    commands.append('^XZ')
    return "\n".join(commands)

def generate_ezpx_xml(label_type_name, label_data, qr_codes, qr_field_names, paper_width_mm, paper_height_mm, font_size_pt, margins_mm, qr_size_mm, num_copies=1):
    margin_top, margin_bottom, margin_left, margin_right = margins_mm
    QR_SPACING_MM = 2

    text_x = margin_left
    text_y = margin_top
    text_height = paper_height_mm - margin_top - margin_bottom
    
    qr_xml_elements = []
    if qr_codes:
        qr_w, qr_h = qr_size_mm
        qr_x = paper_width_mm - qr_w - margin_right
        text_width = paper_width_mm - margin_left - margin_right - qr_w - 2

        current_qr_y = margin_top
        for qr_content in qr_codes:
            safe_qr_content = html.escape(qr_content)
            qr_xml_elements.append(f"""
    <GraphicShape xsi:type="QRCode" X="{qr_x}" Y="{current_qr_y}" BoundRectWidth="{qr_w}" BoundRectHeight="{qr_h}">
        <DispData>{safe_qr_content}</DispData>
        <Data>{safe_qr_content}</Data>
    </GraphicShape>""")
            current_qr_y += qr_h + QR_SPACING_MM
    else:
        text_width = paper_width_mm - margin_left - margin_right

    qr_xml_block = "".join(qr_xml_elements)

    text_lines = []
    for key, value in label_data.items():
        if key in qr_field_names:
            continue
        text_lines.append(f"{key}: {value}")
    
    full_text_content = "\r\n".join(text_lines)
    safe_text_content = html.escape(full_text_content)

    xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<PrintJob xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <FormatVersion>1</FormatVersion>
  <QLabelSDKVersion>1.5.8411.32259</QLabelSDKVersion>
  <GoLabelZoomFactor>0.5</GoLabelZoomFactor>
  <Label>
    <qlabel>
      {qr_xml_block}
      <GraphicShape xsi:type="Text" X="{text_x}" Y="{text_y}" BoundRectWidth="{text_width}" BoundRectHeight="{text_height}" FontCmd="Arial,{font_size_pt}" FontType="TrueType_Font" Encoding="A" FontId="A" FontHeight="{font_size_pt}" FontWidth="{font_size_pt}">
        <DispData>{safe_text_content}</DispData>
        <Data>{safe_text_content}</Data>
      </GraphicShape>
    </qlabel>
    <DateFormat>y2-me-dd</DateFormat>
    <TimeFormat>h:m:s</TimeFormat>
  </Label>
  <Setup LabelLength="{paper_height_mm}" LabelWidth="{paper_width_mm}" GapLength="3" Speed="4" Darkness="8" Copy="{num_copies}" PageDirection="Portrait" PrintMode="1">
    <Layout Shape="0" PageDirection="Portrait"/>
    <UnitType>Mm</UnitType>
    <Dpi>203</Dpi>
  </Setup>
  <PrinterModel>G500</PrinterModel>
  <PrinterLanguage>EZPL</PrinterLanguage>
</PrintJob>
"""
    return xml_content.encode('utf-8')

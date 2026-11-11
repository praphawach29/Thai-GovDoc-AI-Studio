"""
word_exporter.py — ตัวสร้างไฟล์ Microsoft Word (.docx) ตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
ประยุกต์ใช้เทคนิคจาก thaigqsoft/thai-doc-skills (ZWSP Line-breaking, OpenXML thaiDistribute)
"""

import os
import re
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Cm, Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel
from core.thai_segmenter import insert_zwsp, to_thai_numerals


FONT_NAME = "TH Sarabun New"
DEFAULT_FONT_SIZE = 16


def _apply_thai_distributed(paragraph):
    """กำหนดการจัดแนวเป็น Thai Distributed (กระจายแบบไทย) ในระดับ OpenXML"""
    pPr = paragraph._p.get_or_add_pPr()
    # ตรวจสอบว่ามี jc เดิมอยู่หรือไม่ ถ้ามีให้ลบออกก่อน
    for child in list(pPr):
        if child.tag.endswith('jc'):
            pPr.remove(child)
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'thaiDistribute')
    pPr.append(jc)


def _set_run_thai_font(run, font_name=FONT_NAME, size_pt=DEFAULT_FONT_SIZE, bold=False, color=None):
    """
    ตั้งค่าฟอนต์ในระดับ Run ให้ครอบคลุมทั้ง ASCII, High-ANSI และ Complex Script (cs)
    ป้องกันปัญหาฟอนต์เด้งเป็น Angsana หรือ Calibri
    """
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.bold = bold
    if color:
        run.font.color.rgb = color

    rPr = run._r.get_or_add_rPr()
    # ลบ rFonts เดิมถ้ามี
    for child in list(rPr):
        if child.tag.endswith('rFonts'):
            rPr.remove(child)

    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)
    rFonts.set(qn('w:cs'), font_name)
    rFonts.set(qn('w:eastAsia'), font_name)
    rPr.append(rFonts)


def _setup_page_margins(doc: Document, doc_type: DocType):
    """
    กำหนดขนาดขอบกระดาษตามระเบียบงานสารบรรณ:
    - หนังสือภายนอก: ซ้าย 3.0 ซม., ขวา 2.0 ซม., บน 2.5 ซม., ล่าง 2.0 ซม.
    - หนังสือภายใน: ซ้าย 3.0 ซม., ขวา 2.0 ซม., บน 2.0 ซม., ล่าง 2.0 ซม.
    """
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        if doc_type == DocType.INTERNAL:
            section.top_margin = Cm(2.0)
        else:
            section.top_margin = Cm(2.5)


def _add_paragraph_with_zwsp(doc: Document, text: str, indent_cm: float = 0.0, 
                             space_after_pt: float = 6.0, justify: bool = True) -> any:
    """สร้างย่อหน้าพร้อมตัดคำและแทรก Zero-Width Space"""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after_pt)
    p.paragraph_format.line_spacing = 1.0
    if indent_cm > 0:
        p.paragraph_format.first_line_indent = Cm(indent_cm)

    if justify:
        _apply_thai_distributed(p)

    zwsp_text = insert_zwsp(text)
    run = p.add_run(zwsp_text)
    _set_run_thai_font(run, size_pt=DEFAULT_FONT_SIZE)
    return p


def export_govdoc_to_docx(data: GovDocumentSchema, output_path: str, garuda_path: Optional[str] = None) -> str:
    """
    สร้างและส่งออกหนังสือราชการเป็นไฟล์ .docx ตามมาตรฐานงานสารบรรณ
    """
    doc = Document()
    _setup_page_margins(doc, data.doc_type)

    # ตรวจสอบตำแหน่งตราครุฑ
    if not garuda_path:
        default_garuda = Path(__file__).resolve().parent.parent / "assets" / "garuda.png"
        if default_garuda.exists():
            garuda_path = str(default_garuda)

    # จัดการแปลงตัวเลขไทย ถ้าเปิดตัวเลือก use_thai_numerals
    fmt_date = to_thai_numerals(data.doc_date) if data.use_thai_numerals else data.doc_date
    fmt_number = to_thai_numerals(data.doc_number) if data.use_thai_numerals else data.doc_number
    fmt_reason = to_thai_numerals(data.paragraph_reason) if data.use_thai_numerals else data.paragraph_reason
    fmt_details = to_thai_numerals(data.paragraph_details) if (data.paragraph_details and data.use_thai_numerals) else data.paragraph_details
    fmt_purpose = to_thai_numerals(data.paragraph_purpose) if data.use_thai_numerals else data.paragraph_purpose

    if data.doc_type == DocType.EXTERNAL:
        _build_external_doc(doc, data, fmt_date, fmt_number, fmt_reason, fmt_details, fmt_purpose, garuda_path)
    else:
        _build_internal_doc(doc, data, fmt_date, fmt_number, fmt_reason, fmt_details, fmt_purpose, garuda_path)

    # บันทึกไฟล์
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_file))
    return str(out_file)


def _build_external_doc(doc: Document, data: GovDocumentSchema, 
                        fmt_date: str, fmt_number: str, 
                        fmt_reason: str, fmt_details: Optional[str], fmt_purpose: str, 
                        garuda_path: Optional[str]):
    """สร้างโครงสร้างหนังสือภายนอก (ครุฑ 3 ซม. กึ่งกลาง)"""
    
    # 1. ชั้นความลับ / ชั้นความเร็ว (ถ้ามี)
    if data.secret != SecretLevel.NORMAL:
        p_sec = doc.add_paragraph()
        p_sec.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_sec.paragraph_format.space_after = Pt(2)
        r = p_sec.add_run(data.secret.to_thai())
        _set_run_thai_font(r, size_pt=20, bold=True, color=RGBColor(200, 0, 0))

    if data.urgency != UrgencyLevel.NORMAL:
        p_urg = doc.add_paragraph()
        p_urg.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_urg.paragraph_format.space_after = Pt(2)
        r = p_urg.add_run(data.urgency.to_thai())
        _set_run_thai_font(r, size_pt=20, bold=True, color=RGBColor(200, 0, 0))

    # 2. ตราครุฑ 3.0 ซม. กึ่งกลางหน้า
    if garuda_path and os.path.exists(garuda_path):
        p_garuda = doc.add_paragraph()
        p_garuda.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_garuda.paragraph_format.space_after = Pt(12)
        r_garuda = p_garuda.add_run()
        r_garuda.add_picture(garuda_path, height=Cm(3.0))

    # 3. ส่วนหัว: ที่ (ซ้าย) และ ส่วนราชการ (ขวา)
    # ใช้ตาราง 1 แถว 2 คอลัมน์ ไร้เส้นขอบ เพื่อการจัดวางที่แม่นยำ
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    
    # กำหนดความกว้างคอลัมน์: ด้านซ้าย 8 ซม., ด้านขวา 8 ซม.
    col_widths = [Cm(7.5), Cm(8.5)]
    for cell, width in zip(tbl.rows[0].cells, col_widths):
        cell.width = width
        # ปลด padding และ border
        tcPr = cell._tc.get_or_add_tcPr()
        borders = parse_xml(r'<w:tcBorders %s><w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>' % nsdecls('w'))
        tcPr.append(borders)

    cell_left = tbl.cell(0, 0)
    p_num = cell_left.paragraphs[0]
    p_num.paragraph_format.space_after = Pt(4)
    r_num = p_num.add_run(f"ที่  {fmt_number}")
    _set_run_thai_font(r_num, size_pt=DEFAULT_FONT_SIZE)

    cell_right = tbl.cell(0, 1)
    p_dept = cell_right.paragraphs[0]
    p_dept.paragraph_format.space_after = Pt(4)
    r_dept = p_dept.add_run(insert_zwsp(data.dept_name))
    _set_run_thai_font(r_dept, size_pt=DEFAULT_FONT_SIZE)

    # 4. วันที่ (วางตำแหน่งตรงกลางเยื้องขวา ประมาณ 8 ซม. จากขอบซ้าย)
    p_date = doc.add_paragraph()
    p_date.paragraph_format.left_indent = Cm(8.0)
    p_date.paragraph_format.space_after = Pt(8)
    r_date = p_date.add_run(fmt_date)
    _set_run_thai_font(r_date, size_pt=DEFAULT_FONT_SIZE)

    # 5. เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย
    # เรื่อง
    clean_sub = re.sub(r'^เรื่อง\s*', '', data.subject.strip())
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(4)
    r_sub_h = p_sub.add_run("เรื่อง  ")
    _set_run_thai_font(r_sub_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_sub_v = p_sub.add_run(insert_zwsp(clean_sub))
    _set_run_thai_font(r_sub_v, size_pt=DEFAULT_FONT_SIZE)

    # เรียน
    sal_text = data.salutation.strip()
    if sal_text.startswith("กราบเรียน"):
        sal_header = "กราบเรียน  "
        clean_sal = re.sub(r'^กราบเรียน\s*', '', sal_text)
    else:
        sal_header = "เรียน  "
        clean_sal = re.sub(r'^เรียน\s*', '', sal_text)

    p_sal = doc.add_paragraph()
    p_sal.paragraph_format.space_after = Pt(4)
    r_sal_h = p_sal.add_run(sal_header)
    _set_run_thai_font(r_sal_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_sal_v = p_sal.add_run(insert_zwsp(clean_sal))
    _set_run_thai_font(r_sal_v, size_pt=DEFAULT_FONT_SIZE)

    # อ้างถึง (ถ้ามี)
    if data.references:
        for idx, ref in enumerate(data.references):
            p_ref = doc.add_paragraph()
            p_ref.paragraph_format.space_after = Pt(4)
            if idx == 0:
                r_ref_h = p_ref.add_run("อ้างถึง  ")
                _set_run_thai_font(r_ref_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
            else:
                p_ref.paragraph_format.left_indent = Cm(1.5)
            r_ref_v = p_ref.add_run(insert_zwsp(ref))
            _set_run_thai_font(r_ref_v, size_pt=DEFAULT_FONT_SIZE)

    # สิ่งที่ส่งมาด้วย (ถ้ามี)
    if data.attachments:
        for idx, att in enumerate(data.attachments):
            p_att = doc.add_paragraph()
            p_att.paragraph_format.space_after = Pt(4)
            if idx == 0:
                r_att_h = p_att.add_run("สิ่งที่ส่งมาด้วย  ")
                _set_run_thai_font(r_att_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
            else:
                p_att.paragraph_format.left_indent = Cm(2.5)
            r_att_v = p_att.add_run(insert_zwsp(att))
            _set_run_thai_font(r_att_v, size_pt=DEFAULT_FONT_SIZE)

    # 6. เนื้อหา 3 ย่อหน้า (ย่อหน้า 2.5 ซม. + Thai Distributed)
    _add_paragraph_with_zwsp(doc, fmt_reason, indent_cm=2.5, space_after_pt=6)

    if fmt_details:
        _add_paragraph_with_zwsp(doc, fmt_details, indent_cm=2.5, space_after_pt=6)

    _add_paragraph_with_zwsp(doc, fmt_purpose, indent_cm=2.5, space_after_pt=18)

    # 7. คำลงท้าย และผู้ลงนาม (วางเยื้องขวา 8 ซม.)
    p_close = doc.add_paragraph()
    p_close.paragraph_format.left_indent = Cm(8.0)
    p_close.paragraph_format.space_after = Pt(48)  # เว้นที่ว่างสำหรับลายเซ็น
    r_close = p_close.add_run(data.closing)
    _set_run_thai_font(r_close, size_pt=DEFAULT_FONT_SIZE)

    p_sig = doc.add_paragraph()
    p_sig.paragraph_format.left_indent = Cm(8.0)
    p_sig.paragraph_format.space_after = Pt(2)
    r_sig = p_sig.add_run(data.signatory_name)
    _set_run_thai_font(r_sig, size_pt=DEFAULT_FONT_SIZE)

    p_pos = doc.add_paragraph()
    p_pos.paragraph_format.left_indent = Cm(8.0)
    p_pos.paragraph_format.space_after = Pt(24)
    r_pos = p_pos.add_run(data.signatory_position)
    _set_run_thai_font(r_pos, size_pt=DEFAULT_FONT_SIZE)

    # 8. ส่วนราชการเจ้าของเรื่อง (ชิดขอบล่างซ้าย)
    p_contact = doc.add_paragraph()
    p_contact.paragraph_format.space_after = Pt(2)
    r_cdept = p_contact.add_run(insert_zwsp(data.contact_dept))
    _set_run_thai_font(r_cdept, size_pt=14)

    contact_details = []
    if data.contact_tel:
        contact_details.append(f"โทรศัพท์  {data.contact_tel}")
    if data.contact_fax:
        contact_details.append(f"โทรสาร  {data.contact_fax}")
    if data.contact_email:
        contact_details.append(f"ไปรษณีย์อิเล็กทรอนิกส์  {data.contact_email}")

    if contact_details:
        p_cinfo = doc.add_paragraph()
        p_cinfo.paragraph_format.space_after = Pt(2)
        r_cinfo = p_cinfo.add_run(" \n".join(contact_details))
        _set_run_thai_font(r_cinfo, size_pt=14)


def _build_internal_doc(doc: Document, data: GovDocumentSchema, 
                        fmt_date: str, fmt_number: str, 
                        fmt_reason: str, fmt_details: Optional[str], fmt_purpose: str, 
                        garuda_path: Optional[str]):
    """สร้างโครงสร้างหนังสือภายใน / บันทึกข้อความ (ครุฑ 1.5 ซม. ด้านซ้าย)"""

    # 1. แถวหัวกระดาษ: ครุฑ 1.5 ซม. ชิดซ้าย + ข้อความ "บันทึกข้อความ" 29 pt หนา กึ่งกลาง
    tbl_top = doc.add_table(rows=1, cols=2)
    tbl_top.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_top.autofit = False
    for cell, width in zip(tbl_top.rows[0].cells, [Cm(2.5), Cm(13.5)]):
        cell.width = width
        tcPr = cell._tc.get_or_add_tcPr()
        borders = parse_xml(r'<w:tcBorders %s><w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>' % nsdecls('w'))
        tcPr.append(borders)

    # เซลล์ซ้าย: ครุฑ 1.5 ซม.
    if garuda_path and os.path.exists(garuda_path):
        c_left = tbl_top.cell(0, 0)
        p_g = c_left.paragraphs[0]
        r_g = p_g.add_run()
        r_g.add_picture(garuda_path, height=Cm(1.5))

    # เซลล์ขวา: คำว่า "บันทึกข้อความ" 29 pt ตัวหนา
    c_right = tbl_top.cell(0, 1)
    p_title = c_right.paragraphs[0]
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_title = p_title.add_run("บันทึกข้อความ")
    _set_run_thai_font(r_title, size_pt=29, bold=True)

    # 2. รายละเอียดหัวเรื่อง (ส่วนราชการ, ที่, วันที่, เรื่อง, เรียน)
    # ส่วนราชการ
    p_dept = doc.add_paragraph()
    p_dept.paragraph_format.space_after = Pt(4)
    r_dh = p_dept.add_run("ส่วนราชการ  ")
    _set_run_thai_font(r_dh, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_dv = p_dept.add_run(insert_zwsp(data.dept_name))
    _set_run_thai_font(r_dv, size_pt=DEFAULT_FONT_SIZE)

    # ที่ และ วันที่ (ตาราง 2 คอลัมน์)
    tbl_meta = doc.add_table(rows=1, cols=2)
    tbl_meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, width in zip(tbl_meta.rows[0].cells, [Cm(8.0), Cm(8.0)]):
        cell.width = width
        tcPr = cell._tc.get_or_add_tcPr()
        borders = parse_xml(r'<w:tcBorders %s><w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>' % nsdecls('w'))
        tcPr.append(borders)

    c_num = tbl_meta.cell(0, 0)
    p_num = c_num.paragraphs[0]
    p_num.paragraph_format.space_after = Pt(4)
    r_nh = p_num.add_run("ที่  ")
    _set_run_thai_font(r_nh, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_nv = p_num.add_run(fmt_number)
    _set_run_thai_font(r_nv, size_pt=DEFAULT_FONT_SIZE)

    c_dt = tbl_meta.cell(0, 1)
    p_dt = c_dt.paragraphs[0]
    p_dt.paragraph_format.space_after = Pt(4)
    r_dth = p_dt.add_run("วันที่  ")
    _set_run_thai_font(r_dth, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_dtv = p_dt.add_run(fmt_date)
    _set_run_thai_font(r_dtv, size_pt=DEFAULT_FONT_SIZE)

    # เรื่อง
    clean_sub = re.sub(r'^เรื่อง\s*', '', data.subject.strip())
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(4)
    r_sh = p_sub.add_run("เรื่อง  ")
    _set_run_thai_font(r_sh, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_sv = p_sub.add_run(insert_zwsp(clean_sub))
    _set_run_thai_font(r_sv, size_pt=DEFAULT_FONT_SIZE)

    # เรียน
    sal_text = data.salutation.strip()
    if sal_text.startswith("กราบเรียน"):
        sal_header = "กราบเรียน  "
        clean_sal = re.sub(r'^กราบเรียน\s*', '', sal_text)
    else:
        sal_header = "เรียน  "
        clean_sal = re.sub(r'^เรียน\s*', '', sal_text)

    p_sal = doc.add_paragraph()
    p_sal.paragraph_format.space_after = Pt(8)
    r_salh = p_sal.add_run(sal_header)
    _set_run_thai_font(r_salh, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_salv = p_sal.add_run(insert_zwsp(clean_sal))
    _set_run_thai_font(r_salv, size_pt=DEFAULT_FONT_SIZE)

    # 3. เนื้อหา 3 ภาค
    _add_paragraph_with_zwsp(doc, fmt_reason, indent_cm=2.5, space_after_pt=6)

    if fmt_details:
        _add_paragraph_with_zwsp(doc, fmt_details, indent_cm=2.5, space_after_pt=6)

    _add_paragraph_with_zwsp(doc, fmt_purpose, indent_cm=2.5, space_after_pt=24)

    # 4. ผู้ลงนาม (บันทึกข้อความไม่มีคำลงท้าย เช่น ขอแสดงความนับถือ)
    p_sig = doc.add_paragraph()
    p_sig.paragraph_format.left_indent = Cm(8.0)
    p_sig.paragraph_format.space_after = Pt(2)
    r_sig = p_sig.add_run(data.signatory_name)
    _set_run_thai_font(r_sig, size_pt=DEFAULT_FONT_SIZE)

    p_pos = doc.add_paragraph()
    p_pos.paragraph_format.left_indent = Cm(8.0)
    p_pos.paragraph_format.space_after = Pt(4)
    r_pos = p_pos.add_run(data.signatory_position)
    _set_run_thai_font(r_pos, size_pt=DEFAULT_FONT_SIZE)

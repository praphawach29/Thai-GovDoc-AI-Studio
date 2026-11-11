"""
typst_exporter.py — ตัวสร้างไฟล์ Typst (.typ) และคอมไพล์เป็น PDF เวกเตอร์
อ้างอิงแนวทางจาก whs/typst-govdoc
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from core.models import GovDocumentSchema, DocType
from core.thai_segmenter import to_thai_numerals


def _escape_typst_string(s: Optional[str]) -> str:
    """Escape string เพื่อความปลอดภัยใน Typst code"""
    if s is None:
        return '""'
    # Escape backslashes and double quotes
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_typst_list(items: Optional[list]) -> str:
    """แปลง list ของข้อความเป็น Typst array"""
    if not items:
        return "()"
    escaped_items = [_escape_typst_string(item) for item in items]
    return f"({', '.join(escaped_items)})"


def generate_typst_content(data: GovDocumentSchema, garuda_rel_path: str = "assets/garuda.svg") -> str:
    """สร้างเนื้อหาโค้ด Typst จาก GovDocumentSchema"""
    fmt_date = to_thai_numerals(data.doc_date) if data.use_thai_numerals else data.doc_date
    fmt_number = to_thai_numerals(data.doc_number) if data.use_thai_numerals else data.doc_number
    fmt_reason = to_thai_numerals(data.paragraph_reason) if data.use_thai_numerals else data.paragraph_reason
    fmt_details = to_thai_numerals(data.paragraph_details) if (data.paragraph_details and data.use_thai_numerals) else data.paragraph_details
    fmt_purpose = to_thai_numerals(data.paragraph_purpose) if data.use_thai_numerals else data.paragraph_purpose

    if data.doc_type == DocType.EXTERNAL:
        details_val = _escape_typst_string(fmt_details) if fmt_details else "none"
        typst_code = f"""// สร้างอัตโนมัติโดย Thai GovDoc AI Studio
#import "templates/typst/external.typ": govdoc_external

#govdoc_external(
  doc_number: {_escape_typst_string(fmt_number)},
  dept_name: {_escape_typst_string(data.dept_name)},
  doc_date: {_escape_typst_string(fmt_date)},
  subject: {_escape_typst_string(data.subject)},
  salutation: {_escape_typst_string(data.salutation)},
  references: {_format_typst_list(data.references)},
  attachments: {_format_typst_list(data.attachments)},
  paragraph_reason: {_escape_typst_string(fmt_reason)},
  paragraph_details: {details_val},
  paragraph_purpose: {_escape_typst_string(fmt_purpose)},
  closing: {_escape_typst_string(data.closing)},
  signatory_name: {_escape_typst_string(data.signatory_name)},
  signatory_position: {_escape_typst_string(data.signatory_position)},
  contact_dept: {_escape_typst_string(data.contact_dept)},
  contact_tel: {_escape_typst_string(data.contact_tel)},
  contact_fax: {_escape_typst_string(data.contact_fax)},
  contact_email: {_escape_typst_string(data.contact_email)},
  urgency: "{data.urgency.value}",
  secret: "{data.secret.value}",
  garuda_path: "{garuda_rel_path}",
)
"""
    else:
        details_val = _escape_typst_string(fmt_details) if fmt_details else "none"
        typst_code = f"""// สร้างอัตโนมัติโดย Thai GovDoc AI Studio
#import "templates/typst/internal.typ": govdoc_internal

#govdoc_internal(
  doc_number: {_escape_typst_string(fmt_number)},
  dept_name: {_escape_typst_string(data.dept_name)},
  doc_date: {_escape_typst_string(fmt_date)},
  subject: {_escape_typst_string(data.subject)},
  salutation: {_escape_typst_string(data.salutation)},
  references: {_format_typst_list(data.references)},
  attachments: {_format_typst_list(data.attachments)},
  paragraph_reason: {_escape_typst_string(fmt_reason)},
  paragraph_details: {details_val},
  paragraph_purpose: {_escape_typst_string(fmt_purpose)},
  signatory_name: {_escape_typst_string(data.signatory_name)},
  signatory_position: {_escape_typst_string(data.signatory_position)},
  urgency: "{data.urgency.value}",
  secret: "{data.secret.value}",
  garuda_path: "{garuda_rel_path}",
)
"""
    return typst_code


def export_govdoc_to_typst(data: GovDocumentSchema, output_typ_path: str) -> str:
    """บันทึกไฟล์ Typst (.typ)"""
    out_file = Path(output_typ_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    
    # คำนวณ Relative path ไปยัง assets/garuda.svg
    root_dir = Path(__file__).resolve().parent.parent
    garuda_abs = root_dir / "assets" / "garuda.svg"
    try:
        garuda_rel = str(garuda_abs.relative_to(out_file.parent)).replace("\\", "/")
    except ValueError:
        garuda_rel = str(garuda_abs).replace("\\", "/")

    content = generate_typst_content(data, garuda_rel_path=garuda_rel)
    out_file.write_text(content, encoding="utf-8")
    return str(out_file)


def compile_typst_to_pdf(typ_path: str, output_pdf_path: str) -> Tuple[bool, str]:
    """
    คอมไพล์ไฟล์ .typ เป็น .pdf ผ่าน Typst CLI
    คืนค่า (ความสำเร็จ True/False, ข้อความ Error หรือ Success)
    """
    typst_bin = shutil.which("typst")
    if not typst_bin:
        return False, "Typst CLI is not installed on this system."

    cmd = [typst_bin, "compile", typ_path, output_pdf_path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, f"Successfully compiled {output_pdf_path}"
    except subprocess.CalledProcessError as e:
        return False, f"Typst compilation failed: {e.stderr}"
    except Exception as e:
        return False, f"Execution error: {str(e)}"


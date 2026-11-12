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
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
    return f'"{escaped}"'


def _format_typst_list(items: Optional[list]) -> str:
    """แปลง list ของข้อความเป็น Typst array"""
    if not items:
        return "()"
    escaped_items = [_escape_typst_string(item) for item in items]
    # comma ท้ายเสมอ: ("x") ใน Typst คือ string ไม่ใช่ array
    return f"({', '.join(escaped_items)},)"


def _format_memo_blocks(data: GovDocumentSchema) -> str:
    """แปลง MemoBlock (core.memo_layout) เป็น Typst array ของ dictionary"""
    num = to_thai_numerals if data.use_thai_numerals else (lambda t: t)
    items = []
    for b in data.get_memo_blocks():
        items.append(
            "(lead: {lead}, lead_style: {style}, text: {text}, indent: {indent:.2f}cm, "
            "space_before: {sb:.0f}pt, kind: {kind})".format(
                lead=_escape_typst_string(num(b.lead)),
                style=_escape_typst_string(b.lead_style),
                text=_escape_typst_string(num(b.text)),
                indent=b.indent_cm,
                sb=b.space_before_pt,
                kind=_escape_typst_string(b.kind),
            )
        )
    if not items:
        return "()"
    # Typst ต้องมี comma ท้ายเมื่อ array มีสมาชิกเดียว
    return "(\n    " + ",\n    ".join(items) + ",\n  )"


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
  garuda: read("{garuda_rel_path}", encoding: none),
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
  memo_blocks: {_format_memo_blocks(data)},
  signatory_name: {_escape_typst_string(data.signatory_name)},
  signatory_position: {_escape_typst_string(data.signatory_position)},
  urgency: "{data.urgency.value}",
  secret: "{data.secret.value}",
  thai_page_numbers: {"true" if data.use_thai_numerals else "false"},
  garuda_path: "{garuda_rel_path}",
  garuda: read("{garuda_rel_path}", encoding: none),
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


def find_typst_binary() -> Optional[str]:
    """
    ค้นหา Typst CLI: ใช้ตัวที่อยู่ใน PATH ก่อน หากไม่มีให้ใช้ binary ที่มากับโปรเจกต์
    (tools/typst/typst.exe) เพื่อให้เครื่องที่ติดตั้งแบบ portable ใช้งานได้โดยไม่ต้องแก้ PATH
    """
    found = shutil.which("typst")
    if found:
        return found

    root_dir = Path(__file__).resolve().parent.parent
    candidates = [
        root_dir / "tools" / "typst" / "typst.exe",
        root_dir / "tools" / "typst.exe",
        root_dir / "tools" / "typst" / "typst",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def compile_typst_to_pdf(typ_path: str, output_pdf_path: str) -> Tuple[bool, str]:
    """
    คอมไพล์ไฟล์ .typ เป็น .pdf
    ลำดับ: Typst CLI (ถ้ามี) -> Python binding `typst` (pip install typst)
    คืนค่า (ความสำเร็จ True/False, ข้อความ Error หรือ Success)
    """
    typst_bin = find_typst_binary()
    if typst_bin:
        cmd = [typst_bin, "compile"]
        font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
        if font_dir.exists():
            cmd += ["--font-path", str(font_dir)]
        cmd += [typ_path, output_pdf_path]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, f"Successfully compiled {output_pdf_path}"
        except subprocess.CalledProcessError as e:
            return False, f"Typst compilation failed: {e.stderr}"
        except Exception as e:
            return False, f"Execution error: {str(e)}"

    # ไม่มี CLI: ใช้ Python binding (pip install typst) ซึ่งฝัง compiler มาในตัว
    try:
        import typst as typst_py
    except ImportError:
        return False, "Typst CLI/Python package is not installed on this system."

    root_dir = Path(typ_path).resolve().parent
    font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    font_paths = [str(font_dir)] if font_dir.exists() else []
    try:
        typst_py.compile(
            input=str(typ_path),
            output=str(output_pdf_path),
            root=str(root_dir),
            font_paths=font_paths,
        )
        return True, f"Successfully compiled {output_pdf_path} (Python binding)"
    except Exception as e:
        return False, f"Typst compilation failed: {e}"


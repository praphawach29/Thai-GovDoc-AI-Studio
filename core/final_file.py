"""final_file.py — ตรวจไฟล์ฉบับจริงที่ผู้ใช้แก้ใน Word เสร็จแล้วอัปโหลดกลับเข้าระบบ

เก็บไฟล์ตามที่ได้รับทุกไบต์ (ไม่แปลงกลับเป็นข้อมูลบนเว็บ จึงไม่มีอะไรเพี้ยน)
ฟังก์ชันนี้แค่ตรวจว่าเป็นไฟล์จริง, คำนวณ SHA-256 และอ่าน "ที่ / วันที่ / เรื่อง" ไว้แสดงและค้นหา
"""

import hashlib
import io
import re
import zipfile
from typing import List, Optional

from pydantic import BaseModel

FINAL_SUFFIXES = (".docx", ".pdf")
_MAX_TEXT = 200_000

_ZWSP = re.compile("[​‌‍﻿]")
# บรรทัดหัวบันทึกข้อความ: "ที่ กท 1205/123   วันที่ 15 พฤศจิกายน 2569"
_NUMBER_RE = re.compile(r"^\s*ที่\s+(.+?)(?:\s{2,}|\t|\s+วันที่|$)")
_DATE_RE = re.compile(r"วันที่\s+(.+?)\s*$")
_SUBJECT_RE = re.compile(r"^\s*เรื่อง\s+(.+?)\s*$", re.S)   # เรื่องยาวอาจขึ้นบรรทัดใหม่ในย่อหน้าเดียว


class FinalFileError(ValueError):
    """ไฟล์ไม่ใช่ Word/PDF ที่เปิดได้"""


class FinalFileInfo(BaseModel):
    suffix: str
    sha256: str
    size_bytes: int
    text: str = ""
    doc_number: Optional[str] = None
    doc_date: Optional[str] = None
    subject: Optional[str] = None


def _clean(line: str) -> str:
    return re.sub(r"[ \t\n\u00a0]+", " ", _ZWSP.sub("", line)).strip(" .")


def _docx_lines(data: bytes) -> List[str]:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # ไฟล์เสีย / ไม่ใช่ Word
        raise FinalFileError("เปิดไฟล์ Word ไม่ได้ (ไฟล์อาจเสียหรือไม่ใช่ .docx)") from exc
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append("  ".join(cell.text for cell in row.cells))
    return lines


def _pdf_lines(data: bytes) -> List[str]:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [ln for page in pdf.pages[:20] for ln in (page.extract_text() or "").splitlines()]
    except Exception as exc:
        raise FinalFileError("เปิดไฟล์ PDF ไม่ได้") from exc


def _header_fields(lines: List[str]) -> dict:
    """อ่าน ที่ / วันที่ / เรื่อง จากส่วนหัว (30 บรรทัดแรกที่มีข้อความ)"""
    out = {}
    head = [ln for ln in (_ZWSP.sub("", x) for x in lines) if ln.strip()][:30]
    for raw in head:
        if "doc_number" not in out:
            m = _NUMBER_RE.match(raw)
            if m and _clean(m.group(1)):
                out["doc_number"] = _clean(m.group(1))
                d = _DATE_RE.search(raw)
                if d and _clean(d.group(1)):
                    out["doc_date"] = _clean(d.group(1))
                continue
        if "subject" not in out:
            m = _SUBJECT_RE.match(raw)
            if m and _clean(m.group(1)):
                out["subject"] = _clean(m.group(1))
    return out


def inspect_final_file(data: bytes, filename: str) -> FinalFileInfo:
    """ตรวจไฟล์ฉบับจริง (.docx หรือ .pdf) — ไม่แก้ไฟล์"""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in FINAL_SUFFIXES:
        raise FinalFileError("รับเฉพาะไฟล์ Word (.docx) หรือ PDF")
    if not data:
        raise FinalFileError("ไฟล์ว่าง")
    if suffix == ".docx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise FinalFileError("ไฟล์นี้ไม่ใช่ Word (.docx) — ถ้าเป็น .doc รุ่นเก่า ให้บันทึกเป็น .docx ก่อน")
        lines = _docx_lines(data)
    else:
        if not data.startswith(b"%PDF-"):
            raise FinalFileError("ไฟล์นี้ไม่ใช่ PDF")
        lines = _pdf_lines(data)
    fields = _header_fields(lines)
    text = "\n".join(_ZWSP.sub("", ln) for ln in lines).strip()[:_MAX_TEXT]
    return FinalFileInfo(
        suffix=suffix, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), text=text, **fields,
    )

"""
doc_forms.py — หนังสือราชการชนิดอื่นนอกจากหนังสือภายนอก/บันทึกข้อความ (ระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖)

- หนังสือประทับตรา (แบบที่ ๓): ที่ · ถึง · ข้อความ · ส่วนราชการที่ส่งหนังสือออก · ตราชื่อส่วนราชการ
  (หมึกแดง + ลงชื่อย่อกำกับตรา) · วัน เดือน ปี · ส่วนราชการเจ้าของเรื่อง · โทร. โทรสาร ไปรษณีย์อิเล็กทรอนิกส์
  ไม่มี "เรื่อง" บนหนังสือ (เก็บ subject ไว้ลงทะเบียน), ไม่มีคำขึ้นต้น/คำลงท้าย/ผู้ลงนาม

ใช้ร่วมกันทั้งหน้าเว็บ Word และ PDF: เนื้อความทุกบรรทัดคือย่อหน้า (body_lines)
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from core.models import DocType, DocumentKind, GovDocumentSchema

# ระยะย่อหน้า: ทุกบรรทัด 2.5 ซม., ๑.๑ = 3.5 ซม., ๑.๑.๑ = 4.5 ซม.; แท็บนำหน้า N ตัว = ระดับ N (ผู้ใช้กำหนดเอง)
# ต่างจากบันทึกข้อความตรงที่ "ข้อ ๑" อยู่ระดับ ๑ (ข้อของคำสั่ง/ระเบียบเริ่มที่ย่อหน้าปกติ)
BODY_INDENT_CM = 2.5
LEVEL_STEP_CM = 1.0
_MAX_LEVEL = 6
_RE_L3 = re.compile(r"^[0-9๐-๙]+\.[0-9๐-๙]+\.[0-9๐-๙]+")
_RE_L2 = re.compile(r"^[0-9๐-๙]+\.[0-9๐-๙]+")

STAMP_GAP_CM = 2.2          # ที่ว่างสำหรับประทับตราชื่อส่วนราชการ + ลงชื่อย่อกำกับตรา (ระหว่างชื่อส่วนราชการกับวันที่)
SENDER_INDENT_CM = 8.0      # ส่วนราชการที่ส่ง/วันที่ ของหนังสือประทับตรา เริ่มที่แนวกึ่งกลางพื้นที่พิมพ์


def line_level(line: str) -> int:
    tabs = len(line) - len(line.lstrip("\t"))
    if tabs:
        return min(tabs, _MAX_LEVEL)
    s = line.strip()
    if _RE_L3.match(s):
        return 3
    if _RE_L2.match(s):
        return 2
    return 1


def body_lines(*texts: Optional[str]) -> List[Tuple[float, str]]:
    """ย่อหน้าเนื้อความ [(ระยะย่อหน้า ซม., ข้อความ)] จากหลายช่องต่อกัน — บรรทัดว่างถูกข้าม"""
    out: List[Tuple[float, str]] = []
    for text in texts:
        for raw in (text or "").splitlines():
            if not raw.strip():
                continue
            indent = BODY_INDENT_CM + (line_level(raw) - 1) * LEVEL_STEP_CM
            out.append((indent, raw.lstrip("\t").strip()))
    return out


_SAL_RE = re.compile(r"^(กราบเรียน|เรียน|ถึง)\s*")


def recipient_of(salutation: str) -> str:
    return _SAL_RE.sub("", (salutation or "").strip()).strip()


def sender_name(dept: str) -> str:
    """ชื่อส่วนราชการอย่างเดียว: บรรทัดแรก ตัดวงเล็บท้ายที่มีโทรศัพท์ (แบบช่องส่วนราชการของบันทึกข้อความ)"""
    first = (dept or "").split("\n")[0].strip()
    return re.sub(r"\s*\([^()]*โทร[^()]*\)\s*$", "", first).strip()


def to_stamp_letter(doc: GovDocumentSchema, sender: Optional[str] = None) -> GovDocumentSchema:
    """แปลงร่างหนังสือภายนอก (ร่างตามกฎ) เป็นหนังสือประทับตรา: "ถึง" แทน "เรียน", ไม่มีคำลงท้าย/อ้างถึง/สิ่งที่ส่งมาด้วย
    ส่วนราชการที่ส่ง = ชื่อส่วนราชการบรรทัดแรก (ไม่มีที่อยู่)"""
    d = doc.model_copy(deep=True)
    d.kind = DocumentKind.STAMP_LETTER
    d.doc_type = DocType.EXTERNAL
    d.salutation = f"ถึง  {recipient_of(d.salutation) or '[✏️ ระบุผู้รับ]'}"
    d.closing = ""
    d.references = None
    d.attachments = None
    d.signatory_stamp = False
    d.co_signers = None
    d.dept_name = sender_name(sender or d.dept_name) or "[✏️ ระบุส่วนราชการที่ส่งหนังสือออก]"
    return d


def apply_form(doc: GovDocumentSchema, kind: DocumentKind, issuer: Optional[str] = None) -> GovDocumentSchema:
    """แปลงร่างตามกฎ (หนังสือภายนอก) เป็นชนิดที่เลือก — ชนิดเดิม (ภายนอก/บันทึก) คืนค่าเดิม
    issuer = ชื่อส่วนราชการ (ไม่มีที่อยู่/โทรศัพท์) จากโปรไฟล์หน่วยงาน"""
    if kind == DocumentKind.STAMP_LETTER:
        return to_stamp_letter(doc, sender=issuer)
    return doc


def blank_body(kind: DocumentKind) -> Tuple[str, str, str]:
    """(ภาคเหตุ, ภาคข้อเท็จจริง, ภาคความประสงค์) ของเอกสารเปล่า"""
    if kind == DocumentKind.STAMP_LETTER:
        return ("[✏️ ระบุที่มาของเรื่อง เช่น ตามที่... นั้น]", "[✏️ ระบุสิ่งที่ขอ/แจ้ง]", "จึงเรียนมาเพื่อโปรดทราบ")
    return ("[✏️ ระบุภาคเหตุ]", "[✏️ ระบุภาคข้อเท็จจริง]", "[✏️ ระบุภาคความประสงค์]")

"""issuing_units.py — ใช้หน่วยออกหนังสือกับเอกสาร และสร้างสายการเสนอ (กลุ่มงาน -> กอง -> สำนัก)

หนึ่งหน่วย = หนึ่งขั้นในสายการเสนอ: ส่วนราชการ, เลขที่เว้นเขียนมือ, วันที่เว้นเลขวัน,
ผู้รับ (เรียน), ผู้ลงนาม, ชื่อผู้พิจารณาใน "ข้อพิจารณาและเสนอแนะ" และภาคความประสงค์มาตรฐาน
"""

import re
from datetime import date
from typing import Iterable, List, Optional

from core.models import HANDWRITE_GAP, GovDocumentSchema, IssuingUnit, Signer
from core.thai_date import THAI_MONTHS, today_bangkok

SIGNER_NAME_PLACEHOLDER = "([✏️ ระบุชื่อผู้ลงนาม])"


def format_doc_number(fmt: str, day: Optional[date] = None) -> str:
    """แทน {gap} และ {year} ในรูปแบบเลขที่ (ตัวเลขเป็นอารบิก แปลงเลขไทยตอนส่งออก)"""
    d = day or today_bangkok()
    return (fmt or "{gap}/{year}").replace("{gap}", HANDWRITE_GAP).replace("{year}", str(d.year + 543))


def blank_day_date(day: Optional[date] = None) -> str:
    """วันที่แบบเว้นเลขวันไว้ลงตอนลงนาม เช่น '          สิงหาคม 2569' (ไม่มีคำว่า 'วันที่')"""
    d = day or today_bangkok()
    return f"{HANDWRITE_GAP}{THAI_MONTHS[d.month - 1]} {d.year + 543}"


def pick_unit(units: Iterable[IssuingUnit], key: Optional[str] = None) -> Optional[IssuingUnit]:
    """หน่วยตาม key; ไม่ระบุหรือไม่พบ = หน่วยตั้งต้น (หรือหน่วยแรก)"""
    units = list(units)
    if key:
        for unit in units:
            if unit.key == key:
                return unit
    return next((u for u in units if u.is_default), units[0] if units else None)


def next_unit(units: Iterable[IssuingUnit], key: str) -> Optional[IssuingUnit]:
    """หน่วยขั้นถัดไปในสายการเสนอ (หน่วยถัดไปในรายการ) หรือ None ถ้าเป็นขั้นสุดท้าย"""
    units = list(units)
    for i, unit in enumerate(units):
        if unit.key == key:
            return units[i + 1] if i + 1 < len(units) else None
    return None


def _resolve_signer(signer: Signer, author: Optional[Signer]) -> Signer:
    if signer.is_author and author is not None and (author.name or author.position):
        return Signer(name=author.name or SIGNER_NAME_PLACEHOLDER,
                      position=author.position or signer.position, is_author=True)
    return Signer(name=signer.name or SIGNER_NAME_PLACEHOLDER, position=signer.position,
                  is_author=signer.is_author)


def _swap_review_party(text: Optional[str], unit: IssuingUnit, others: Iterable[IssuingUnit]) -> Optional[str]:
    """เปลี่ยน 'กลุ่มงาน...พิจารณาแล้ว' เป็นชื่อผู้พิจารณาของหน่วยนี้ (เฉพาะชื่อหน่วยที่รู้จัก)"""
    if not text or not unit.review_party:
        return text
    names = sorted({u.review_party for u in others if u.review_party and u.review_party != unit.review_party},
                   key=len, reverse=True)
    if not names:
        return text
    pattern = re.compile("(" + "|".join(re.escape(n) for n in names) + r")(\s*)(?=พิจารณาแล้ว)")
    return pattern.sub(lambda m: unit.review_party + m.group(2), text)


def apply_issuing_unit(
    doc: GovDocumentSchema,
    unit: IssuingUnit,
    day: Optional[date] = None,
    author: Optional[Signer] = None,
    units: Iterable[IssuingUnit] = (),
    replace_request: bool = False,
) -> GovDocumentSchema:
    """คืนสำเนาเอกสารที่ใช้ค่าของหน่วยออกหนังสือ

    replace_request: ใช้ภาคความประสงค์มาตรฐานของหน่วยแทนข้อความเดิมเสมอ (ร่างใหม่)

    author: ชื่อ/ตำแหน่งของผู้ใช้ (แทนผู้ลงนามที่เป็น 'ผู้เสนอเรื่อง')
    units: หน่วยทั้งหมดในสาย — ใช้เปลี่ยนชื่อผู้พิจารณาและภาคความประสงค์มาตรฐานของหน่วยอื่นให้เป็นของหน่วยนี้
    """
    units = list(units)
    updated = doc.model_copy(deep=True)
    updated.dept_name = unit.dept_name
    updated.doc_number = format_doc_number(unit.doc_number_format, day)
    if unit.blank_day:
        updated.doc_date = blank_day_date(day)
    if unit.contact_dept:
        updated.contact_dept = unit.contact_dept
    if unit.contact_tel:
        updated.contact_tel = unit.contact_tel
    if unit.contact_fax:
        updated.contact_fax = unit.contact_fax
    if unit.recipient:
        updated.salutation = f"เรียน {unit.recipient}"
    if unit.signers:
        signers = [_resolve_signer(s, author) for s in unit.signers]
        updated.signatory_name, updated.signatory_position = signers[0].name, signers[0].position
        updated.co_signers = signers[1:] or None
    updated.memo_consideration = _swap_review_party(updated.memo_consideration, unit, units)
    if unit.request_text:
        # แทนเฉพาะภาคความประสงค์ที่ว่างหรือเป็นข้อความมาตรฐานของหน่วยอื่น (ไม่ทับข้อความที่ผู้ใช้เขียนเอง)
        standard = {u.request_text.strip() for u in units if u.request_text}
        current = (updated.memo_request or "").strip()
        if replace_request or not current or current in standard:
            updated.memo_request = unit.request_text
    return updated


def build_unit_chain(
    doc: GovDocumentSchema,
    units: Iterable[IssuingUnit],
    start_key: Optional[str] = None,
    day: Optional[date] = None,
    author: Optional[Signer] = None,
) -> List[tuple]:
    """ชุดบันทึกตั้งแต่หน่วยเริ่มต้นขึ้นไปจนสุดสาย: [(หน่วย, เอกสาร), ...] เรียงจากขั้นแรกไปขั้นสุดท้าย"""
    units = list(units)
    start = pick_unit(units, start_key)
    if start is None:
        return []
    chain = []
    for unit in units[units.index(start):]:
        chain.append((unit, apply_issuing_unit(doc, unit, day, author, units)))
    return chain


def units_as_dicts(units: Iterable[IssuingUnit]) -> List[dict]:
    return [u.model_dump() for u in units]

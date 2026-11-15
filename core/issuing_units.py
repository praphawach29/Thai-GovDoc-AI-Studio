"""issuing_units.py — ใช้หน่วยออกหนังสือกับเอกสาร (ส่วนราชการ, เลขที่เว้นเขียนมือ, วันที่เว้นเลขวัน)"""

from datetime import date
from typing import Iterable, List, Optional

from core.models import HANDWRITE_GAP, GovDocumentSchema, IssuingUnit
from core.thai_date import THAI_MONTHS, today_bangkok


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


def apply_issuing_unit(doc: GovDocumentSchema, unit: IssuingUnit, day: Optional[date] = None) -> GovDocumentSchema:
    """คืนสำเนาเอกสารที่ใช้ส่วนราชการ/เลขที่/วันที่/ผู้ประสาน ตามหน่วยออกหนังสือ"""
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
    return updated


def units_as_dicts(units: Iterable[IssuingUnit]) -> List[dict]:
    return [u.model_dump() for u in units]

"""thai_date.py — จัดรูปแบบวันที่ภาษาไทย (พ.ศ.) สำหรับเอกสารราชการ"""

from datetime import date
from typing import Optional

THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def format_thai_date(day: Optional[date] = None, use_thai_numerals: bool = False) -> str:
    """คืนวันที่รูปแบบ '๑๒ พฤศจิกายน ๒๕๖๙' หรือ '12 พฤศจิกายน 2569' (ไม่มีคำว่าวันที่)"""
    d = day or date.today()
    text = f"{d.day} {THAI_MONTHS[d.month - 1]} {d.year + 543}"
    if use_thai_numerals:
        from core.thai_segmenter import to_thai_numerals
        return to_thai_numerals(text)
    return text


def blank_doc_number(use_thai_numerals: bool = False, day: Optional[date] = None) -> str:
    """เลขที่หนังสือแบบเว้นช่องให้เขียนด้วยมือ เช่น '......../2569'"""
    d = day or date.today()
    year = str(d.year + 543)
    if use_thai_numerals:
        from core.thai_segmenter import to_thai_numerals
        year = to_thai_numerals(year)
    return f"......../{year}"

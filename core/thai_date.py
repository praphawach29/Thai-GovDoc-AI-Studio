"""thai_date.py — จัดรูปแบบวันที่ภาษาไทย (พ.ศ.) สำหรับเอกสารราชการ"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

# เวลาประเทศไทย (UTC+7 ไม่มี daylight saving) — ใช้ค่าคงที่แทน zoneinfo
# เพราะ Windows ไม่มีฐานข้อมูลเขตเวลาในตัว และเซิร์ฟเวอร์คลาวด์มักตั้งเป็น UTC
BANGKOK_TZ = timezone(timedelta(hours=7), name="Asia/Bangkok")


def now_bangkok() -> datetime:
    """เวลาปัจจุบันตามเวลาประเทศไทย ไม่ขึ้นกับเขตเวลาของเครื่องเซิร์ฟเวอร์"""
    return datetime.now(BANGKOK_TZ)


def today_bangkok() -> date:
    """วันที่ปัจจุบันตามเวลาประเทศไทย"""
    return now_bangkok().date()


def current_be_year() -> int:
    """ปี พ.ศ. ปัจจุบันตามเวลาประเทศไทย"""
    return today_bangkok().year + 543

THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def format_thai_date(day: Optional[date] = None, use_thai_numerals: bool = False) -> str:
    """คืนวันที่รูปแบบ '๑๒ พฤศจิกายน ๒๕๖๙' หรือ '12 พฤศจิกายน 2569' (ไม่มีคำว่าวันที่)"""
    d = day or today_bangkok()
    text = f"{d.day} {THAI_MONTHS[d.month - 1]} {d.year + 543}"
    if use_thai_numerals:
        from core.thai_segmenter import to_thai_numerals
        return to_thai_numerals(text)
    return text


def blank_doc_number(use_thai_numerals: bool = False, day: Optional[date] = None) -> str:
    """เลขที่หนังสือแบบเว้นช่องให้เขียนด้วยมือ เช่น '......../2569'"""
    d = day or today_bangkok()
    year = str(d.year + 543)
    if use_thai_numerals:
        from core.thai_segmenter import to_thai_numerals
        year = to_thai_numerals(year)
    return f"......../{year}"

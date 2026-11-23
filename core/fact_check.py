"""fact_check.py — ตรวจข้อเท็จจริงในร่างเทียบกับต้นเรื่อง

AI อ่านไฟล์สแกนแล้วอาจอ่านตัวเลขคลาด (วันที่ เวลา จำนวนเงิน จำนวนคน) — ตัวที่อยู่ในร่างแต่หาในต้นเรื่องไม่เจอ
จะถูกส่งกลับเป็นจุด "ต้องตรวจกับต้นเรื่อง" ให้ผู้ใช้เทียบกับไฟล์จริงก่อนเสนอ

ตรวจเฉพาะเนื้อความที่มาจากต้นเรื่อง (เรื่อง อ้างถึง สิ่งที่ส่งมาด้วย และย่อหน้าเนื้อหา)
ไม่ตรวจส่วนหัวของหน่วยงานเอง (ที่ วันที่ ส่วนราชการ) และภาคความประสงค์ที่ระบบเติม
ไม่ใช้ AI — เทียบตัวเลขตรง ๆ จึงเร็วและผลเหมือนเดิมทุกครั้ง
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from pydantic import BaseModel

from core.models import DocType, GovDocumentSchema

MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
          "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
MONTHS_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
_MONTH_INDEX = {m: i + 1 for i, m in enumerate(MONTHS)} | {m: i + 1 for i, m in enumerate(MONTHS_ABBR)}
_MONTH_RE = "|".join(re.escape(m) for m in sorted(_MONTH_INDEX, key=len, reverse=True))
_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_PLACEHOLDER = re.compile(r"\[(?:✏️\s*)?ระบุ[^\]]*\]|\{\{[^}]+\}\}")

# วันที่: "14 กันยายน 2568", "14 – 16 ก.ย. 68", "วันที่ 14 กันยายน พ.ศ. 2568"
_DATE = re.compile(
    rf"(\d{{1,2}})(?:\s*[-–]\s*(\d{{1,2}}))?\s*({_MONTH_RE})\s*(?:พ\.ศ\.\s*)?(\d{{4}}|\d{{2}}(?!\d))?"
)
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2,4})(?!\d)")
# เวลาในร่าง: ต้องมี "น." / "นาฬิกา" หรือคำว่า "เวลา" นำ (กันตัวเลขทศนิยมทั่วไป)
_TIME_STRICT = re.compile(r"(?:เวลา\s*)?(?<![\d.])(\d{1,2})[.:](\d{2})(?:\s*(?:น\.|นาฬิกา)|(?=\s*[-–]\s*\d{1,2}[.:]\d{2}\s*(?:น\.|นาฬิกา)))|เวลา\s*(\d{1,2})[.:](\d{2})")
_TIME_LOOSE = re.compile(r"(?<![\d.])(\d{1,2})[.:](\d{2})(?![\d])")
_NUMBER = re.compile(r"(?<![\d.,/])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.,/])\d+(?:\.\d+)?")
# เลขข้อ (๑. / ๑.๑ / ๑.๑.๑) ต้นบรรทัด — โครงร่างที่ AI จัดเอง ไม่ใช่ข้อเท็จจริง
_LIST_MARKER = re.compile(r"(?m)^\s*\d+(?:\.\d+)*\.?(?=\s)")


class FactIssue(BaseModel):
    """ข้อเท็จจริงในร่างที่หาในต้นเรื่องไม่เจอ"""
    field: str                 # ช่องในเอกสาร (ชื่อเดียวกับช่องบนหน้าแก้ไข)
    kind: str                  # date | time | number
    text: str                  # ข้อความตามที่เขียนในร่าง
    message: str


def normalize(text: str) -> str:
    return (text or "").translate(_DIGITS).replace("​", "")


def _year(y: Optional[str]) -> Optional[int]:
    if not y:
        return None
    n = int(y)
    if n < 100:
        return 2500 + n            # ๖๘ → ๒๕๖๘
    if n < 2400:
        return n + 543             # ค.ศ. → พ.ศ.
    return n


def _number_value(raw: str) -> str:
    v = raw.replace(",", "")
    if "." in v:
        v = v.rstrip("0").rstrip(".")
    return v.lstrip("0") or "0"


@dataclass
class _SourceFacts:
    dates: Set[Tuple[int, int, Optional[int]]] = field(default_factory=set)
    times: Set[Tuple[int, int]] = field(default_factory=set)
    numbers: Set[str] = field(default_factory=set)

    def has_date(self, d: int, m: int, y: Optional[int]) -> bool:
        for sd, sm, sy in self.dates:
            if sd == d and sm == m and (y is None or sy is None or sy == y):
                return True
        return False


def _source_facts(text: str) -> _SourceFacts:
    t = normalize(text)
    f = _SourceFacts()
    for m in _DATE.finditer(t):
        month, year = _MONTH_INDEX[m.group(3)], _year(m.group(4))
        first = int(m.group(1))
        last = int(m.group(2)) if m.group(2) else first
        for d in range(first, max(first, min(last, 31)) + 1):
            f.dates.add((d, month, year))
    for m in _NUMERIC_DATE.finditer(t):
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            f.dates.add((d, mo, _year(m.group(3))))
    for m in _TIME_LOOSE.finditer(t):
        h, mm = int(m.group(1)), int(m.group(2))
        if h <= 24 and mm < 60:
            f.times.add((h, mm))
    f.numbers = {_number_value(m.group(0)) for m in _NUMBER.finditer(t)}
    return f


def _fields(doc: GovDocumentSchema) -> List[Tuple[str, str]]:
    """ช่องที่มาจากต้นเรื่อง (ชื่อช่องตรงกับ data-field บนหน้าแก้ไข)"""
    out = [("subject", doc.subject), ("references", "\n".join(doc.references or [])),
           ("attachments", "\n".join(doc.attachments or []))]
    if doc.doc_type == DocType.INTERNAL:
        out += [("memo_intro", doc.memo_intro or ""), ("memo_facts", doc.memo_facts or ""),
                ("memo_consideration", doc.memo_consideration or "")]
    else:
        out += [("paragraph_reason", doc.paragraph_reason or ""), ("paragraph_details", doc.paragraph_details or ""),
                ("paragraph_purpose", doc.paragraph_purpose or "")]
    return [(k, v) for k, v in out if v and v.strip()]


def _blank(text: str, span: Tuple[int, int]) -> str:
    """ลบส่วนที่ตรวจแล้วออก (คงความยาวเดิม) กันตัวเลขในวันที่/เวลาถูกนับซ้ำเป็นจำนวน"""
    a, b = span
    return text[:a] + " " * (b - a) + text[b:]


def check_facts(doc: GovDocumentSchema, source_text: str, *, min_source_chars: int = 40) -> List[FactIssue]:
    """ข้อเท็จจริงในร่างที่หาในต้นเรื่องไม่เจอ (ไม่มีต้นเรื่อง = ไม่ตรวจ)"""
    return check_fields(_fields(doc), source_text, min_source_chars=min_source_chars)


def check_fields(fields: List[Tuple[str, str]], source_text: str, *, min_source_chars: int = 40) -> List[FactIssue]:
    """เหมือน check_facts แต่รับ [(ชื่อช่อง, ข้อความ)] ตรง ๆ — ใช้ตรวจคำตอบของ AI ก่อนใส่ลงเอกสาร (core/draft_review)"""
    if len(normalize(source_text).strip()) < min_source_chars:
        return []
    src = _source_facts(source_text)
    issues: List[FactIssue] = []
    seen: Set[Tuple[str, str, str]] = set()

    def add(field_name: str, kind: str, shown: str, key: str, message: str) -> None:
        if (field_name, kind, key) in seen:
            return
        seen.add((field_name, kind, key))
        issues.append(FactIssue(field=field_name, kind=kind, text=shown.strip(), message=message))

    for name, raw in fields:
        if not (raw or "").strip():
            continue
        shown_text = _PLACEHOLDER.sub(lambda m: " " * len(m.group(0)), raw.replace("​", ""))
        t = normalize(shown_text)
        for m in _DATE.finditer(t):
            month, year = _MONTH_INDEX[m.group(3)], _year(m.group(4))
            first = int(m.group(1))
            last = int(m.group(2)) if m.group(2) else first
            missing = [d for d in range(first, max(first, min(last, 31)) + 1) if not src.has_date(d, month, year)]
            if missing:
                add(name, "date", shown_text[m.start():m.end()], f"{first}-{last}/{month}/{year}",
                    "ไม่พบวันที่นี้ในต้นเรื่อง — AI อาจอ่านผิด ตรวจกับไฟล์จริง")
            t = _blank(t, m.span())
        for m in _NUMERIC_DATE.finditer(t):
            d, mo = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12 and not src.has_date(d, mo, _year(m.group(3))):
                add(name, "date", shown_text[m.start():m.end()], m.group(0), "ไม่พบวันที่นี้ในต้นเรื่อง — AI อาจอ่านผิด ตรวจกับไฟล์จริง")
            t = _blank(t, m.span())
        for m in _TIME_STRICT.finditer(t):
            h, mm = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            if int(h) <= 24 and int(mm) < 60 and (int(h), int(mm)) not in src.times:
                add(name, "time", shown_text[m.start():m.end()], f"{int(h)}:{mm}", "ไม่พบเวลานี้ในต้นเรื่อง — ตรวจกับไฟล์จริง")
            t = _blank(t, m.span())
        for m in _LIST_MARKER.finditer(t):
            t = _blank(t, m.span())
        for m in _NUMBER.finditer(t):
            value = _number_value(m.group(0))
            # ตัวเลขหลักเดียวไม่มีหน่วย (เช่น "ทั้ง ๒ ฝ่าย") ส่วนใหญ่เป็นภาษาเขียน ไม่ใช่ข้อเท็จจริงที่อ่านจากไฟล์
            if len(value.replace(".", "")) < 2 or value in src.numbers:
                continue
            add(name, "number", shown_text[m.start():m.end()], value, "ไม่พบตัวเลขนี้ในต้นเรื่อง — AI อาจอ่านผิด ตรวจกับไฟล์จริง")
    return issues


def source_text_of(raw_text: Optional[str], prompt: Optional[str]) -> str:
    """ต้นเรื่อง = ข้อความที่อ่านจากไฟล์ + คำสั่งที่ผู้ใช้พิมพ์ (ผู้ใช้ให้ข้อมูลเพิ่มเองได้)"""
    return "\n".join(p for p in (raw_text, prompt) if p)

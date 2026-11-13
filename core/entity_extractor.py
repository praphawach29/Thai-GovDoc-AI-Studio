"""
entity_extractor.py — สกัดข้อมูลสำคัญจากข้อความต้นเรื่อง (ชื่อ, หน่วยงาน, วันที่, เลขที่,
จำนวนเงิน, ตัวเลข, กำหนดการ, สิ่งที่ส่งมาด้วย) พร้อมหลักฐานและความมั่นใจตามวิธีที่ตรวจสอบได้

ใช้กฎ/Regex แบบ deterministic เท่านั้น — ไม่เรียก LLM เพื่อให้ตรวจสอบผลได้
"""

import re
from typing import List, Optional

from core.models import EvidenceRef, ExtractedEntity, UnclearSpan
from core.thai_date import THAI_MONTHS
from core.thai_segmenter import to_arabic_numerals


_MONTHS_REGEX = "|".join(THAI_MONTHS)
_THAI_DIGITS = "๐๑๒๓๔๕๖๗๘๙"


def normalize_thai_number(text: str) -> str:
    """แปลงเลขไทยเป็นอารบิกเพื่อใช้เปรียบเทียบ"""
    return to_arabic_numerals(text) if text else text


def normalize_thai_date_text(text: str) -> str:
    """แปลงตัวเลขในวันที่ให้เป็นอารบิก (คงชื่อเดือนไทย)"""
    return to_arabic_numerals(text) if text else text


def _evidence(text: str, match: "re.Match", field: str, method: str, confidence: float) -> EvidenceRef:
    return EvidenceRef(
        field=field,
        value=match.group(0).strip(),
        source_quote=match.group(0).strip(),
        start=match.start(),
        end=match.end(),
        confidence=confidence,
        method=method,
        needs_review=confidence < 0.75,
    )


def _collect(pattern, text: str, kind: str, field: str, method: str, confidence: float) -> List[ExtractedEntity]:
    out: List[ExtractedEntity] = []
    for m in re.finditer(pattern, text):
        value = m.group(0).strip()
        if not value:
            continue
        out.append(ExtractedEntity(
            kind=kind,
            value=value,
            normalized=normalize_thai_number(value),
            evidence=_evidence(text, m, field, method, confidence),
        ))
    return out


def extract_entities(text: str, method: str = "regex", page: Optional[int] = None) -> List[ExtractedEntity]:
    """สกัด entity จากข้อความต้นเรื่อง พร้อมหลักฐาน/ความมั่นใจตาม method"""
    if not text:
        return []
    method = method if method in {"regex", "ocr", "vlm", "manual", "profile"} else "regex"
    confidence = {"regex": 0.9, "manual": 1.0, "profile": 1.0, "ocr": 0.6, "vlm": 0.7}.get(method, 0.8)

    entities: List[ExtractedEntity] = []

    # ชื่อบุคคล
    entities += _collect(
        r"(?:นาย|นางสาว|นาง|ดร\.?|ผศ\.?|รศ\.?|ศ\.)\s*[\u0e00-\u0e5b\s]{2,60}",
        text, "person", "person", method, confidence,
    )

    # วันที่
    entities += _collect(
        rf"[๐-๙0-9]{{1,2}}\s*(?:{_MONTHS_REGEX})\s*(?:พ\.ศ\.\s*)?[๐-๙0-9]{{2,4}}",
        text, "date", "date", method, confidence,
    )

    # เลขที่หนังสือ
    entities += _collect(
        r"(?:ที่|เลขที่)\s*[^\s]+",
        text, "doc_no", "doc_no", method, confidence,
    )

    # จำนวนเงิน
    entities += _collect(
        r"[๐-๙0-9][๐-๙0-9,\.]*\s*(?:บาท|ล้านบาท|ลบ\.|ดอลลาร์|USD|THB)",
        text, "amount", "amount", method, confidence,
    )

    # ตัวเลขพร้อมหน่วยนับ
    entities += _collect(
        r"[๐-๙0-9][๐-๙0-9,\.]*\s*(?:คน|ฉบับ|ชุด|ครั้ง|วัน|ปี|ชั่วโมง|%|เปอร์เซ็นต์)",
        text, "number", "number", method, confidence,
    )

    # กำหนดการ / ครบกำหนด
    entities += _collect(
        r"(?:ภายในวันที่|ภายใน|ครบกำหนด|กำหนดภายใน|กำหนดส่ง)[^\n]{0,60}",
        text, "deadline", "deadline", method, confidence,
    )

    # สิ่งที่ส่งมาด้วย
    entities += _collect(
        r"สิ่งที่ส่งมาด้วย\s*[^\n]+",
        text, "attachment", "attachment", method, confidence,
    )

    # หน่วยงาน
    dept_kw = "กระทรวง|กรม|สำนัก|มหาวิทยาลัย|จังหวัด|เทศบาล|องค์การ|ฝ่าย|กอง|คณะ|สมาคม|มูลนิธิ|สโมสร|ชมรม|บริษัท"
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 160:
            continue
        if re.search(dept_kw, line) and not line.startswith(("ที่", "เรื่อง", "เรียน", "อ้างถึง", "สิ่งที่ส่งมาด้วย", "ตามที่")):
            entities.append(ExtractedEntity(
                kind="agency",
                value=line,
                normalized=line,
                evidence=EvidenceRef(
                    field="agency", value=line, source_quote=line,
                    start=text.find(line), end=text.find(line) + len(line),
                    confidence=confidence, method=method,
                    needs_review=confidence < 0.75,
                ),
            ))

    return entities


def find_unclear_spans(text: str, page: Optional[int] = None) -> List[UnclearSpan]:
    """หาช่วงข้อความที่สกัดไม่ชัดเจน (อักขระเสีย/แทนที่จากการ OCR)"""
    spans: List[UnclearSpan] = []
    if not text:
        return spans
    patterns = [
        (r"�+", "พบอักขระที่ไม่รู้จัก (encoding error)"),
        (r"[#]{2,}", "พบเครื่องหมายแทนอักขระที่อ่านไม่ออก"),
        (r"(?:[|Il1]){3,}", "พบลำดับอักขระกำกวม (I/l/1)"),
    ]
    for pattern, reason in patterns:
        for m in re.finditer(pattern, text):
            spans.append(UnclearSpan(
                text=m.group(0),
                start=m.start(),
                end=m.end(),
                page=page,
                reason=reason,
            ))
    return spans

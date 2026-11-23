"""handwriting.py — ตัวเลขลายมือ/ตรายางในต้นเรื่อง → จุดตรวจในร่าง

AI อ่านตัวเลขที่เขียนด้วยลายมือ (เลขที่หนังสือในเกษียน เลขรับ) ได้ไม่ตรงกันในแต่ละรอบ และการตรวจข้อเท็จจริง
เทียบต้นเรื่องจับไม่ได้ เพราะต้นเรื่องก็คือข้อความที่ AI อ่านมาเอง — ตอนอ่านไฟล์จึงให้ AI ติดป้าย "[ลายมือ]"
ต่อท้ายตัวเลขเหล่านั้น (llm_drafter.OCR_HANDWRITING) แล้วตอนร่างเปลี่ยนตัวเลขนั้นในร่างเป็น
"[✏️ ระบุเลขลายมือ (AI อ่านได้ ...)]" ให้ป้าย "ต้องแก้" พาผู้ใช้ไปเทียบกับไฟล์สแกนทุกครั้ง
"""
from __future__ import annotations

import re
from typing import Set

from core.models import DocType, GovDocumentSchema

TAG = "[ลายมือ]"
_TO_ARABIC = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_DIGITS = r"[0-9๐-๙]"
_TAGGED = re.compile(rf"({_DIGITS}+)\s*\[ลายมือ\]")
_NUMBER = re.compile(rf"(?<!{_DIGITS}){_DIGITS}+(?!{_DIGITS})")
_CHIP = re.compile(r"\[✏️[^\]]*\]")
_MIN_DIGITS = 3            # วันที่/เดือนหลักเดียวสองหลักซ้ำกับข้อความทั่วไปบ่อย — ตรวจเฉพาะเลขที่/เลขรับ


def _key(digits: str) -> str:
    return digits.translate(_TO_ARABIC)


def _is_year(n: str) -> bool:
    """ปี พ.ศ./ค.ศ. ที่เขียนมือในเกษียน (เช่น ๒๕๖๙) ซ้ำกับปีที่พิมพ์ทั่วร่าง — ไม่ทำเป็นจุดตรวจ"""
    return len(n) == 4 and (2400 <= int(n) <= 2600 or 1900 <= int(n) <= 2100)


def handwritten_numbers(source: str) -> Set[str]:
    """ตัวเลขที่ติดป้ายลายมือในต้นเรื่อง (เลขอารบิก, ≥ ๓ หลัก, ไม่ใช่ปี)"""
    tagged = {_key(m.group(1)) for m in _TAGGED.finditer(source or "")}
    return {n for n in tagged if len(n) >= _MIN_DIGITS and not _is_year(n)}


def strip_tags(text: str) -> str:
    return (text or "").replace(TAG, "")


def flag_text(text: str, numbers: Set[str]) -> str:
    """เปลี่ยนตัวเลขลายมือในข้อความร่างเป็นจุดตรวจ (ไม่แตะตัวเลขในจุด [✏️ ...] ที่มีอยู่แล้ว)"""
    if not text:
        return text
    text = _TAGGED.sub(lambda m: m.group(1) + "\0", text)       # ป้ายที่ AI คัดมาด้วย = ลายมือแน่นอน
    out, last = [], 0
    chips = [m.span() for m in _CHIP.finditer(text)]
    for m in _NUMBER.finditer(text):
        if any(a <= m.start() < b for a, b in chips):
            continue
        marked = text[m.end():m.end() + 1] == "\0"
        if marked or _key(m.group(0)) in numbers:
            out.append(text[last:m.start()])
            out.append(f"[✏️ ระบุเลขลายมือ (AI อ่านได้ {m.group(0)})]")
            last = m.end()
    out.append(text[last:])
    return "".join(out).replace("\0", "")


def flag_handwritten(doc: GovDocumentSchema, source: str) -> int:
    """แก้เอกสารในที่: ตัวเลขลายมือในเนื้อความ/อ้างถึง → จุดตรวจ คืนจำนวนจุดที่เพิ่ม"""
    numbers = handwritten_numbers(source)
    if TAG not in (source or ""):
        return 0
    memo = ["memo_intro", "memo_facts", "memo_consideration", "memo_request"]
    paragraphs = ["paragraph_reason", "paragraph_details", "paragraph_purpose"]
    # บันทึกข้อความ: paragraph_* เป็นสำเนาของ memo_* — แก้ด้วยแต่นับเฉพาะ memo_*
    counted = ["subject", "memo_request_top"] + (memo if doc.doc_type == DocType.INTERNAL else paragraphs)
    added = 0
    for name in ["subject", "memo_request_top"] + memo + paragraphs:
        before = getattr(doc, name, None)
        if before:
            after = flag_text(before, numbers)
            if name in counted:
                added += after.count("[✏️ ระบุเลขลายมือ") - before.count("[✏️ ระบุเลขลายมือ")
            setattr(doc, name, after)
    if doc.references:
        refs = [flag_text(r, numbers) for r in doc.references]
        added += sum(r.count("[✏️ ระบุเลขลายมือ") for r in refs) - sum(
            r.count("[✏️ ระบุเลขลายมือ") for r in doc.references)
        doc.references = refs
    return added

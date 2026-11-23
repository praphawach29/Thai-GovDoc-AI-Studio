"""draft_review.py — ตรวจร่างที่ AI ตอบ แล้วส่งรายการปัญหากลับให้ AI แก้หนึ่งรอบ (llm_drafter.draft_content_with_llm)

ตรวจเฉพาะสิ่งที่ระบบรู้แน่ว่าผิดและ AI แก้เองได้จากต้นเรื่อง — ที่เหลือยังเป็นหน้าที่ของตัวตรวจเดิม
(ป้าย "ต้องแก้", ตรวจข้อเท็จจริง, ข้อกฎหมายที่ตัดทิ้ง) ซึ่งทำงานกับร่างหลังแก้เหมือนเดิม
"""
from __future__ import annotations

import re
from typing import List

from core.fact_check import check_fields

_TO_ARABIC = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_TOP_ITEM = re.compile(r"^\s*([๐-๙0-9]+)\.(?![๐-๙0-9])", re.M)
# "ข้อเท็จจริง ๒, ๔ และ ๖ - ๙" / "ข้อเท็จจริง ๓" — เลขข้อที่อ้างถึงทั้งชุด
_FACT_REF = re.compile(r"ข้อเท็จจริง(?:ข้อ)?\s*((?:[๐-๙0-9]+(?:\s*(?:[-–]|ถึง)\s*[๐-๙0-9]+)?(?:\s*(?:,|และ|หรือ)\s*|\s+)?)+)")
_NUM = re.compile(r"[๐-๙0-9]+")
_RANGE = re.compile(r"([๐-๙0-9]+)\s*(?:[-–]|ถึง)\s*([๐-๙0-9]+)")


def _n(s: str) -> int:
    return int(s.translate(_TO_ARABIC))


def fact_item_count(facts: str) -> int:
    return len(_TOP_ITEM.findall(facts or ""))


def fact_refs(text: str) -> List[int]:
    """เลขข้อเท็จจริงที่ถูกอ้างในข้อความ (ขยายช่วง ๖ - ๙ เป็น ๖ ๗ ๘ ๙)"""
    out: List[int] = []
    for m in _FACT_REF.finditer(text or ""):
        chunk = m.group(1)
        for a, b in _RANGE.findall(chunk):
            out += list(range(_n(a), _n(b) + 1))
        out += [_n(x) for x in _NUM.findall(_RANGE.sub(" ", chunk))]
    return out


def review_memo(content, source: str, *, recipient: str = "") -> List[str]:
    """ปัญหาในร่างบันทึกข้อความที่ส่งให้ AI แก้ได้ (ข้อความสั้น ๆ ภาษาไทย) — ว่าง = ผ่าน"""
    issues: List[str] = []
    facts_n = fact_item_count(content.memo_facts)

    # ๑. อ้างข้อเท็จจริงที่ไม่มี
    if facts_n:
        for field, label in (("memo_consideration", "ข้อพิจารณาและเสนอแนะ"),
                             ("memo_request_top", "ภาคความประสงค์ขั้นเสนอปลัดฯ")):
            bad = sorted({n for n in fact_refs(getattr(content, field, "")) if n > facts_n or n < 1})
            if bad:
                issues.append(f"{label} อ้าง \"ข้อเท็จจริง {', '.join(map(str, bad))}\" แต่ข้อเท็จจริงมีเพียง {facts_n} ข้อ "
                              "— แก้เลขข้อที่อ้างให้ตรงกับรายการในข้อเท็จจริง")

    # ๒. ต้นเรื่องไล่การมอบหมายเลยผู้รับบันทึก (ลงไปถึงตัวเจ้าหน้าที่)
    if recipient and re.search(re.escape(recipient) + r"\s*(?:ได้)?มอบ", content.memo_intro or ""):
        issues.append(f"ต้นเรื่องไล่การมอบหมายต่อจาก {recipient} ลงไปถึงตัวเจ้าหน้าที่ — "
                      f"ให้จบที่การมอบหมายมายัง {recipient} (หรือหน่วยของผู้ร่าง) ห้ามใส่ชื่อเจ้าหน้าที่ผู้รับเรื่อง")

    # ๓. ตัวเลข วันที่ เวลา ที่หาในต้นเรื่องไม่เจอ (ข้อกฎหมายที่คัดมาแล้วนับเป็นแหล่งด้วย)
    corpus = "\n".join(x for x in (source, content.memo_law) if x)
    fields = [(k, getattr(content, k, "") or "") for k in ("memo_intro", "memo_facts", "memo_consideration")]
    seen = set()
    for f in check_fields(fields, corpus):
        if (f.kind, f.text) in seen:
            continue
        seen.add((f.kind, f.text))
        what = {"date": "วันที่", "time": "เวลา"}.get(f.kind, "ตัวเลข")
        issues.append(f"{what} \"{f.text}\" ไม่พบในต้นเรื่อง — ตรวจกับ <source> แล้วแก้ให้ตรง "
                      "ถ้าต้นเรื่องไม่มีจริงให้เว้นเป็น [✏️ ระบุ...]")
    return issues[:12]


def repair_prompt(original_prompt: str, previous_json: str, issues: List[str]) -> str:
    """คำขอรอบแก้: คำขอเดิมทั้งหมด + ร่างรอบแรก + รายการปัญหา — แก้เฉพาะจุด คงส่วนอื่นตามเดิม"""
    listed = "\n".join(f"{i}. {x}" for i, x in enumerate(issues, 1))
    return (f"{original_prompt}\n\n"
            "ร่างรอบแรกของคุณ (JSON):\n<previous_draft>\n" + previous_json + "\n</previous_draft>\n\n"
            "ระบบตรวจร่างรอบแรกแล้วพบปัญหาต่อไปนี้:\n<issues>\n" + listed + "\n</issues>\n"
            "ตอบเป็นร่างฉบับแก้ทั้งฉบับตาม schema เดิม: แก้เฉพาะจุดที่ระบุ ส่วนอื่นคงข้อความเดิมทุกตัวอักษร "
            "ห้ามเพิ่มข้อเท็จจริงใหม่ที่ไม่มีใน <source> หรือ <reference>")


def should_review(content, doc_type_internal: bool) -> bool:
    return doc_type_internal and bool((getattr(content, "memo_intro", "") or getattr(content, "memo_facts", "")))


def remaining_ok(remaining_s: float, first_call_s: float, minimum_s: float = 20.0) -> bool:
    """รอบแก้ต้องมีเวลาพอสำหรับเรียก AI อีกครั้ง (ประมาณเท่ารอบแรก + เผื่อ) ภายในเพดานคำขอ"""
    return remaining_s >= max(minimum_s, first_call_s * 1.2 + 5)


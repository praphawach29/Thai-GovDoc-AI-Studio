"""law_grounding.py — ตรวจว่าข้อกฎหมายที่ AI เขียนมีอยู่จริงในต้นเรื่องหรือต้นแบบที่ผู้ใช้แนบ

AI คัดข้อกฎหมายจากหนังสือฉบับจริง (ต้นแบบ) ได้ แต่ห้ามแต่งเอง — ระบบจึงเทียบทีละบรรทัดกับข้อความแหล่ง
(ไม่สนช่องว่าง การขึ้นบรรทัด เลขไทย/อารบิก เครื่องหมายคำพูด และ "(เอกสาร ๑)") บรรทัดที่หาไม่เจอถูกตัดทิ้ง
ข้อหลักที่ชื่อกฎหมายหาไม่เจอถูกตัดทั้งข้อ แล้วเรียงเลขข้อใหม่
"""
from __future__ import annotations

import re
from typing import List, Tuple

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_DOC_TAG = re.compile(r"\(\s*เอกสาร[^)]*\)")
# ไม่เทียบสระบน/ล่างและวรรณยุกต์: ข้อความจากชั้นข้อความ PDF มักสลับที่ (เช่น "อตั รา") และ AI สะกดให้ถูก
_DROP = re.compile(r"[\s​\"'“”‘’ัิ-ฺ็-๎]+")
_ITEM = re.compile(r"^\s*([๐-๙0-9]+)\.(?![๐-๙0-9])\s*")
_PREFIX = 30          # เทียบเฉพาะส่วนต้นของบรรทัด — AI ตัดท้ายประโยคยาวได้ แต่ต้องขึ้นต้นตรงกับแหล่ง
_MIN_KEY = 6          # บรรทัดสั้นมาก (เช่น "ดังนี้") ไม่ใช่ข้อกฎหมาย ไม่ต้องตรวจ


def _norm(text: str) -> str:
    return _DROP.sub("", _DOC_TAG.sub("", text or "").translate(_THAI_DIGITS))


def _found(line: str, corpus: str) -> bool:
    key = _norm(_ITEM.sub("", line))
    return len(key) < _MIN_KEY or key[:_PREFIX] in corpus


def ground_law(law: str, sources: str) -> Tuple[str, int]:
    """คืน (ข้อกฎหมายเฉพาะส่วนที่พบในแหล่ง, จำนวนบรรทัดที่ตัดทิ้ง)"""
    lines = [ln.rstrip() for ln in (law or "").splitlines() if ln.strip()]
    if not lines:
        return "", 0
    corpus = _norm(sources)
    items: List[List[str]] = []
    for ln in lines:
        if _ITEM.match(ln) or not items:
            items.append([ln])
        else:
            items[-1].append(ln)

    kept: List[List[str]] = []
    dropped = 0
    for head, *rest in items:
        if not _found(head, corpus):
            dropped += 1 + len(rest)
            continue
        body = [ln for ln in rest if _found(ln, corpus)]
        dropped += len(rest) - len(body)
        kept.append([head, *body])

    first = _ITEM.match(lines[0])
    thai = bool(first and "๐" <= first.group(1)[0] <= "๙")   # เลขข้อแบบเดียวกับที่ AI เขียน
    out = []
    for n, (head, *body) in enumerate(kept, 1):
        m = _ITEM.match(head)
        if m:
            num = str(n).translate(str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")) if thai else str(n)
            head = f"{num}. {head[m.end():]}"
        out.append("\n".join([head, *body]))
    return "\n".join(out), dropped

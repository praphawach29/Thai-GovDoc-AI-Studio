"""legal_import.py — แยกไฟล์กฎหมาย/ระเบียบที่ AI อ่านแล้ว (ข้อความทีละหน้า) เป็นข้อ/มาตรา พร้อมเลขหน้า

ใช้กับคลังกฎหมาย: ผู้ใช้นำเข้าไฟล์สแกน → AI อ่านทีละหน้า → แยกเป็นข้อ → ผู้ใช้ตรวจแล้วยืนยัน
เลขหน้าของแต่ละข้อใช้ดึงเฉพาะหน้านั้นจากไฟล์สแกนจริงไปแนบท้าย PDF (ไม่พิมพ์ข้อความใหม่)

รูปแบบที่รองรับ (ดูจากไฟล์จริงของหน่วยงาน):
- ระเบียบ / ข้อบัญญัติกรุงเทพมหานคร: "ข้อ ๑๔ ..." แบ่งเป็น "หมวด ๒ ..." และมี "บัญชีท้ายระเบียบ" เป็นตาราง
- พระราชบัญญัติ: "มาตรา 5 ..." (เลขอารบิกหรือไทย)
- ประกาศ / หนังสือเวียน ที่ไม่มีข้อ: ทั้งฉบับเป็นรายการเดียว
"""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel

_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_THAI = "๐๑๒๓๔๕๖๗๘๙"

# หัวข้อต้นบรรทัด: "ข้อ ๑๔", "ข้อ 3/1", "มาตรา 5", "มาตรา ๔ ทวิ"
_HEADING = re.compile(r"^\s*(ข้อ|มาตรา)\s*([0-9๐-๙]+(?:/[0-9๐-๙]+)?)(\s*(?:ทวิ|ตรี|จัตวา))?(?=[\s“\"(]|$)")
_CHAPTER = re.compile(r"^\s*(หมวด|ส่วนที่)\s*([0-9๐-๙]+)\s*(.*)$")
_APPENDIX = re.compile(r"^\s*(บัญชี(?:ท้าย|อัตรา)[^\n]{0,80}|ภาคผนวก[^\n]{0,60}|แบบท้าย[^\n]{0,60})\s*$")
# หัว/ท้ายกระดาษที่ไม่ใช่เนื้อหา: "หน้า ๓", "เล่ม ๑๓๗ ตอนพิเศษ ... ราชกิจจานุเบกษา ...", "-๑๖-", "--- หน้าที่ 3 ---"
_PAGE_NOISE = re.compile(
    r"^\s*(?:หน้า\s*[0-9๐-๙]+|-\s*[0-9๐-๙]+\s*-|---\s*หน้าที่\s*[0-9๐-๙]+\s*---|เล่ม\s*[0-9๐-๙]+\s*ตอน.*ราชกิจจานุเบกษา.*|[0-9๐-๙]{1,4})\s*$"
)


class LegalSection(BaseModel):
    """หนึ่งรายการในคลังกฎหมาย (ข้อ / มาตรา / บัญชีท้าย / ทั้งฉบับ)"""
    label: str                    # "ข้อ ๑๔", "มาตรา ๕", "บัญชีท้ายระเบียบ", "ทั้งฉบับ"
    number: Optional[str] = None  # เลขข้อแบบอารบิก ใช้เรียง/ค้น ("14", "3/1")
    chapter: Optional[str] = None # "หมวด ๒ ค่าสมาชิก ค่าบริการ ..."
    text: str
    page_from: int                # หน้าในไฟล์ (เริ่ม 1)
    page_to: int


def _to_thai(s: str) -> str:
    return re.sub(r"[0-9]", lambda m: _THAI[int(m.group(0))], s)


def _clean_lines(page_text: str) -> List[str]:
    return [ln.rstrip() for ln in (page_text or "").replace("​", "").splitlines()
            if ln.strip() and not _PAGE_NOISE.match(ln)]


def split_sections(page_texts: List[str], *, thai_digits: bool = True) -> List[LegalSection]:
    """แยกข้อความทีละหน้าเป็นข้อ/มาตรา

    - ข้อความก่อนข้อแรก (ชื่อระเบียบ, อาศัยอำนาจ) ไม่เป็นรายการ — ชื่อเอกสารเก็บที่แหล่ง
    - ข้อที่ยาวข้ามหน้า: page_to = หน้าสุดท้ายที่มีเนื้อหาของข้อนั้น
    - หลังข้อสุดท้าย ถ้าเจอ "บัญชีท้าย..." แยกเป็นรายการของตัวเอง (ตารางอัตรา)
    - ไม่เจอข้อ/มาตราเลย (ประกาศ หนังสือเวียน) → ทั้งฉบับเป็นรายการเดียว
    - เลขข้อซ้ำ (เช่น "ข้อ ๑" ในบัญชีท้าย) หลังบัญชีท้ายไม่แยกเป็นข้อใหม่
    """
    sections: List[LegalSection] = []
    current: Optional[dict] = None
    chapter: Optional[str] = None
    in_appendix = False
    chapter_needs_title = False      # "หมวด ๒" อยู่บรรทัดเดียว ชื่อหมวดอยู่บรรทัดถัดไป
    seen_numbers = set()

    def close():
        nonlocal current
        if current is not None:
            text = "\n".join(current["lines"]).strip()
            if text:
                sections.append(LegalSection(label=current["label"], number=current["number"], chapter=current["chapter"],
                                             text=text, page_from=current["page_from"], page_to=current["page_to"]))
        current = None

    for page_no, page_text in enumerate(page_texts, 1):
        for line in _clean_lines(page_text):
            if not in_appendix:
                ch = _CHAPTER.match(line)
                if ch:
                    close()
                    title = ch.group(3).strip()
                    chapter = f"{ch.group(1)} {_to_thai(ch.group(2).translate(_DIGITS))}" + (f" {title}" if title else "")
                    chapter_needs_title = not title
                    continue
                if chapter_needs_title and not _HEADING.match(line):
                    chapter = f"{chapter} {line.strip()}"
                    chapter_needs_title = False
                    continue
                chapter_needs_title = False
                app = _APPENDIX.match(line) if sections or current else None
                if app:
                    close()
                    in_appendix = True
                    current = {"label": app.group(1).strip(), "number": None, "chapter": None,
                               "lines": [], "page_from": page_no, "page_to": page_no}
                    continue
                h = _HEADING.match(line)
                if h:
                    suffix = (h.group(3) or "").strip()
                    number = h.group(2).translate(_DIGITS) + (f" {suffix}" if suffix else "")
                    if (h.group(1), number) not in seen_numbers:
                        close()
                        seen_numbers.add((h.group(1), number))
                        shown = _to_thai(number) if thai_digits else number
                        current = {"label": f"{h.group(1)} {shown}", "number": number,
                                   "chapter": chapter, "lines": [line.strip()], "page_from": page_no, "page_to": page_no}
                        continue
            if current is not None:
                current["lines"].append(line.strip())
                current["page_to"] = page_no
    close()

    if not sections:
        text = "\n".join(ln.strip() for pt in page_texts for ln in _clean_lines(pt)).strip()
        if text:
            sections.append(LegalSection(label="ทั้งฉบับ", text=text, page_from=1, page_to=max(1, len(page_texts))))
    return sections


def guess_title(page_texts: List[str]) -> str:
    """ชื่อเอกสารจากหน้าแรก: บรรทัดแรก ๆ ก่อนข้อ/มาตราแรก ที่ขึ้นต้นด้วยชนิดกฎหมาย"""
    kinds = ("ระเบียบ", "ข้อบัญญัติ", "พระราชบัญญัติ", "ประกาศ", "คำสั่ง", "ข้อบังคับ", "กฎกระทรวง", "บันทึกข้อความ")
    lines = _clean_lines(page_texts[0] if page_texts else "")
    for i, line in enumerate(lines[:15]):
        if _HEADING.match(line):
            break
        if line.strip().startswith(kinds):
            # ชื่อมักต่อด้วยบรรทัด "ว่าด้วย..." / "เรื่อง ..." และปี พ.ศ.
            parts = [line.strip()]
            for j, nxt in enumerate(lines[i + 1:i + 4]):
                s = nxt.strip()
                # "พระราชบัญญัติ" อยู่บรรทัดเดียว ชื่ออยู่บรรทัดถัดไป เช่น "เครื่องหมายราชการ พุทธศักราช 2482"
                bare_kind = j == 0 and parts[0] in kinds and not _HEADING.match(s) and len(s) < 120
                if (bare_kind or s.startswith(("ว่าด้วย", "เรื่อง", "พ.ศ.", "พุทธศักราช", "(ฉบับที่", "สำนัก", "ตาม"))) \
                        and len(" ".join(parts)) < 200:
                    parts.append(s)
                else:
                    break
            return " ".join(parts)[:300]
    return ""

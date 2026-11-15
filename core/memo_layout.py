"""
memo_layout.py — ตัวจัดโครงสร้างเนื้อความ "บันทึกข้อความ" (หนังสือภายใน) ให้เป็นบล็อกย่อหน้าพร้อมเรนเดอร์

ใช้ร่วมกันระหว่าง Word / PDF (HTML) / Live Preview เพื่อให้ทุกช่องทางจัดหน้าเหมือนกัน

รูปแบบหัวข้อที่รองรับ (GovDocumentSchema.memo_heading_style)
- "bma" (ค่าเริ่มต้น) — ตามแบบบันทึกเสนอพิจารณาของกรุงเทพมหานคร:
      ต้นเรื่อง            (หัวข้อขีดเส้นใต้ บรรทัดเดี่ยว)
      ข้อกฎหมาย           (หัวข้อขีดเส้นใต้ บรรทัดเดี่ยว — ถ้ามี)
      ข้อเท็จจริง ....      (หัวข้อขีดเส้นใต้ นำหน้าข้อความในบรรทัดเดียวกัน)
      ข้อพิจารณาและเสนอแนะ .... (หัวข้อขีดเส้นใต้ นำหน้าข้อความ)
      จึงเรียนมาเพื่อโปรดพิจารณา ... (ย่อหน้าภาคความประสงค์แยกต่างหาก)
- "numbered" — แบบหัวข้อมีเลขกำกับตัวหนา: ๑. ต้นเรื่อง ๒. ข้อเท็จจริง ๓. ข้อกฎหมาย ๔. ข้อพิจารณาและเสนอแนะ

การย่อหน้า (first-line indent, บรรทัดถัดไปชิดขอบซ้าย ตามแบบหนังสือราชการ)
- หัวข้อ ต้นเรื่อง / ข้อกฎหมาย / ข้อเท็จจริง / ข้อพิจารณาและเสนอแนะ → ชิดขอบซ้าย (0 ซม.)
- ย่อหน้าปกติ / ข้อระดับ ๑ (๑. ...)           → 2.5 ซม.
- ข้อระดับ ๒ (๑.๑ ...) / มาตรา / ข้อ ของกฎหมาย → 3.5 ซม.
- ข้อระดับ ๓ (๑.๑.๑ ...)                       → 4.5 ซม.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

BASE_INDENT_CM = 2.5
LEVEL_STEP_CM = 1.0

_DIGIT = r"[0-9๐-๙]"
_RE_LEVEL3 = re.compile(rf"^{_DIGIT}+\.{_DIGIT}+\.{_DIGIT}+")
_RE_LEVEL2 = re.compile(rf"^{_DIGIT}+\.{_DIGIT}+")
_RE_LEVEL1 = re.compile(rf"^{_DIGIT}+\.")
_RE_CLAUSE = re.compile(rf"^(มาตรา|ข้อ)\s*{_DIGIT}+")
_RE_REQUEST = re.compile(r"^(จึงเรียน|จึงกราบเรียน)")

SECTION_TITLES = {
    "intro": "ต้นเรื่อง",
    "law": "ข้อกฎหมาย",
    "facts": "ข้อเท็จจริง",
    "consideration": "ข้อพิจารณาและเสนอแนะ",
}

# ลำดับหัวข้อของแต่ละรูปแบบ
SECTION_ORDER = {
    "bma": ("intro", "law", "facts", "consideration"),
    "numbered": ("intro", "facts", "law", "consideration"),
}

# หัวข้อที่เขียนนำหน้าข้อความในบรรทัดเดียวกัน (run-in) สำหรับรูปแบบ bma (ถ้าข้อความบรรทัดแรกไม่ได้เป็นข้อย่อย ๑.)
_BMA_RUN_IN = {"intro", "facts", "consideration"}

_THAI_DIGITS = "๐๑๒๓๔๕๖๗๘๙"


@dataclass
class MemoBlock:
    """ย่อหน้า ๑ ย่อหน้าในเนื้อความบันทึกข้อความ"""
    text: str
    indent_cm: float = BASE_INDENT_CM
    lead: str = ""             # หัวข้อที่นำหน้าย่อหน้า (ถ้ามี)
    lead_style: str = ""       # "underline" | "bold" | ""
    space_before_pt: float = 0.0
    kind: str = "body"         # "heading" | "body" | "request"
    section_key: str = ""      # "intro" | "facts" | "law" | "consideration"


def line_indent_cm(line: str) -> float:
    """คำนวณระยะย่อหน้าบรรทัดแรกจากรูปแบบเลขข้อนำหน้า"""
    s = line.lstrip()
    if _RE_LEVEL3.match(s):
        return BASE_INDENT_CM + 2 * LEVEL_STEP_CM
    if _RE_LEVEL2.match(s) or _RE_CLAUSE.match(s):
        return BASE_INDENT_CM + LEVEL_STEP_CM
    return BASE_INDENT_CM


def split_consideration_and_request(consideration: str, request: Optional[str]) -> Tuple[str, str]:
    """
    แยก "ข้อพิจารณาและเสนอแนะ" ออกจาก "ภาคความประสงค์" (จึงเรียนมาเพื่อ...)
    - ถ้ามี memo_request ใช้ค่านั้นตรง ๆ
    - ถ้าไม่มี จะดึงย่อหน้าสุดท้ายที่ขึ้นต้นด้วย "จึงเรียน..." ออกมาเป็นภาคความประสงค์ (รองรับข้อมูลเดิม)
    """
    consideration = (consideration or "").strip()
    if request and request.strip():
        return consideration, request.strip()

    lines = consideration.splitlines()
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        if _RE_REQUEST.match(lines[i].strip()):
            idx = i
        break
    if idx is not None:
        return "\n".join(lines[:idx]).strip(), "\n".join(lines[idx:]).strip()

    # กรณีเขียนต่อท้ายในย่อหน้าเดียวกัน: "... ต่อไป จึงเรียนมาเพื่อโปรดพิจารณา"
    m = re.search(r"\s(จึงเรียนมาเพื่อ.*|จึงกราบเรียนมาเพื่อ.*)$", consideration, flags=re.S)
    if m and m.start() > 0:
        return consideration[: m.start()].strip(), m.group(1).strip()
    return consideration, ""


def _to_thai_digit(n: int) -> str:
    return "".join(_THAI_DIGITS[int(c)] for c in str(n))


def build_memo_sections(intro: str, facts: str, law: str, consideration: str,
                        style: str = "bma") -> List[Tuple[str, str, str]]:
    """คืนค่า [(key, หัวข้อที่แสดง, เนื้อความ), ...] ตามลำดับของรูปแบบที่เลือก (ข้ามหัวข้อที่ว่าง)"""
    values = {"intro": intro, "facts": facts, "law": law, "consideration": consideration}
    order = SECTION_ORDER.get(style, SECTION_ORDER["bma"])
    out = []
    for key in order:
        body = (values.get(key) or "").strip()
        if not body:
            continue
        title = SECTION_TITLES[key]
        if style == "numbered":
            title = f"{_to_thai_digit(len(out) + 1)}. {title}"
        out.append((key, title, body))
    return out


# ระยะก่อนย่อหน้าตามแบบบันทึกข้อความที่หน่วยงานใช้จริง: 'เรียน' และทุกหัวข้อใหม่ 6 pt
SECTION_GAP_PT = 6.0
SALUTATION_GAP_PT = 6.0


def build_memo_blocks(sections: List[Tuple[str, str, str]], request: str,
                      style: str = "bma") -> List[MemoBlock]:
    """แปลงหัวข้อ + ภาคความประสงค์ เป็นรายการย่อหน้าพร้อมระยะย่อหน้า"""
    blocks: List[MemoBlock] = []
    lead_style = "bold" if style == "numbered" else "underline"

    for s_idx, (key, title, body) in enumerate(sections):
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        # ต้นเรื่อง (หัวข้อแรก ต่อจาก 'เรียน') 0 pt, ขึ้นหัวข้อใหม่ 6 pt, ย่อหน้าในหัวข้อเดียวกัน 0 pt
        gap = SECTION_GAP_PT if s_idx > 0 else 0.0
        run_in = style == "bma" and key in _BMA_RUN_IN and lines and not _RE_LEVEL1.match(lines[0])

        if run_in:
            # หัวข้อแบบ run-in ต้องชิดขอบซ้าย (ไม่ย่อหน้า) เพื่อให้ตรงกับแบบบันทึกต้นฉบับ
            blocks.append(MemoBlock(text=lines[0], indent_cm=0.0, lead=title,
                                    lead_style=lead_style, space_before_pt=gap, kind="body",
                                    section_key=key))
            lines = lines[1:]
        else:
            # หัวข้อบรรทัดเดี่ยวชิดขอบซ้าย ส่วนเนื้อความบรรทัดถัดไปยังย่อหน้า 2.5 ซม.
            blocks.append(MemoBlock(text="", indent_cm=0.0, lead=title, lead_style=lead_style,
                                    space_before_pt=gap, kind="heading", section_key=key))
        for ln in lines:
            blocks.append(MemoBlock(text=ln, indent_cm=line_indent_cm(ln), section_key=key))

    for i, ln in enumerate([x.strip() for x in (request or "").splitlines() if x.strip()]):
        blocks.append(MemoBlock(text=ln, indent_cm=BASE_INDENT_CM,
                                space_before_pt=SECTION_GAP_PT if i == 0 else 0.0, kind="request",
                                section_key="consideration"))
    return blocks


def render_memo_blocks_html(blocks: List[MemoBlock],
                            transform: Optional[Callable[[str], str]] = None,
                            indent_unit: str = "cm", indent_scale: float = 1.0,
                            include_pencils: bool = False) -> str:
    """
    เรนเดอร์บล็อกเป็น HTML (<p>) — ใช้ทั้งใน PDF และ Live Preview
    transform: ฟังก์ชันแปลงข้อความหลัง escape (เช่น แปลงเลขไทย / ไฮไลต์ placeholder)
    include_pencils: แสดงปุ่มดินสอแบบคลิกได้สำหรับเปิดป็อปอัปแก้ไขเรียลไทม์ (เฉพาะ Live Preview)
    """
    tf = transform or (lambda s: s)
    parts = []
    seen_pencil_keys = set()

    for b in blocks:
        style = (f"text-indent: {b.indent_cm * indent_scale:.2f}{indent_unit}; "
                 f"margin-top: {b.space_before_pt:.0f}pt; margin-bottom: 0;")
        lead_html = ""
        pencil_link = ""
        sec_key = getattr(b, "section_key", "")

        # ปักหมุดปุ่มดินสอหัวข้อแรกของแต่ละกลุ่มเนื้อหา
        if include_pencils and sec_key and sec_key not in seen_pencil_keys and (b.lead or b.kind in ("heading", "request") or b.space_before_pt > 0):
            seen_pencil_keys.add(sec_key)
            tip_name = b.lead or SECTION_TITLES.get(sec_key, sec_key)
            pencil_link = f'<a href="?edit={sec_key}" target="_self" class="doc-pencil-btn" title="คลิกเพื่อแก้ไข{tip_name} (ป็อปอัปเรียลไทม์)">✏️</a>'

        if b.lead:
            lead_txt = tf(html.escape(b.lead, quote=False))
            if b.lead_style == "underline":
                lead_html = f'<span class="memo-lead" style="text-decoration: underline;">{lead_txt}</span>'
            elif b.lead_style == "bold":
                lead_html = f'<strong class="memo-lead">{lead_txt}</strong>'
            else:
                lead_html = lead_txt
            if pencil_link:
                lead_html += f"&nbsp;{pencil_link}"
            if b.text:
                lead_html += "&nbsp;&nbsp;"
        elif pencil_link:
            lead_html = f"{pencil_link}&nbsp;"

        body_html = tf(html.escape(b.text, quote=False)) if b.text else ""
        if include_pencils and b.kind == "request" and pencil_link:
            body_html += f"&nbsp;{pencil_link}"

        parts.append(f'<p class="memo-{b.kind}" style="{style}">{lead_html}{body_html}</p>')
    return "\n".join(parts)

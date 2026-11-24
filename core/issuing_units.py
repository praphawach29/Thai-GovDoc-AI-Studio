"""issuing_units.py — ใช้หน่วยออกหนังสือกับเอกสาร และสร้างสายการเสนอ (กลุ่มงาน -> กอง -> สำนัก)

หนึ่งหน่วย = หนึ่งขั้นในสายการเสนอ: ส่วนราชการ, เลขที่เว้นเขียนมือ, วันที่เว้นเลขวัน,
ผู้รับ (เรียน), ผู้ลงนาม, ชื่อผู้พิจารณาใน "ข้อพิจารณาและเสนอแนะ" และภาคความประสงค์มาตรฐาน
"""

import re
from datetime import date
from typing import Iterable, List, Optional, Sequence

from core.models import HANDWRITE_GAP, GovDocumentSchema, IssuingUnit, Signer
from core.signers import OrgSigner, fill_from_roster
from core.thai_date import THAI_MONTHS, today_bangkok

SIGNER_NAME_PLACEHOLDER = "([✏️ ระบุชื่อผู้ลงนาม])"


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


AUTHORITY_PLACEHOLDER = "[✏️ ระบุกฎหมายและมาตรา/ข้อที่ให้อำนาจ]"

_RE_ITEM_NO = re.compile(r"^\s*([0-9๐-๙]+(?:\.[0-9๐-๙]+)*)\.?\s+(.*)$")
# คำกริยาของข้อเสนอ → (ชนิด, คำในภาคความประสงค์) — มองเฉพาะต้นข้อ ไม่นับคำที่อยู่กลางประโยค
_VERBS = [
    (re.compile(r"เห็นชอบ"), "approve", "ให้ความเห็นชอบ"),
    (re.compile(r"อนุญาต"), "approve", "อนุญาต"),
    (re.compile(r"อนุมัติ"), "approve", "อนุมัติ"),
    (re.compile(r"มอบหมาย|สั่งการ"), "command", "สั่งการ"),
]
_POWER_WORD = {"ให้ความเห็นชอบ": "เห็นชอบ", "อนุญาต": "อนุญาต", "อนุมัติ": "อนุมัติ"}


def _join_thai(parts: Sequence[str], gap: str = "") -> str:
    """['ก', 'ข', 'ค'] → 'ก ข และค' (gap=" " → 'ก ข และ ค' สำหรับเลขข้อ)"""
    parts = list(parts)
    return parts[0] if len(parts) == 1 else " ".join(parts[:-1]) + " และ" + gap + parts[-1]


def proposal_items(consideration: str) -> List[tuple]:
    """ข้อเสนอในข้อพิจารณาและเสนอแนะ: [(เลขข้อ, ชนิด, คำ), ...] ตามลำดับ

    ใช้เฉพาะข้อที่ขึ้นต้นด้วยคำกริยา (เห็นชอบ/อนุญาต/อนุมัติ/มอบหมาย) และไม่มีข้อย่อยที่มีคำกริยาเอง
    เช่น ๑. (มีข้อย่อย ๑.๑ เห็นชอบ ๑.๒ อนุญาต) → ใช้ ๑.๑ ๑.๒; ๒. มอบหมาย (ข้อย่อยเป็นรายชื่อหน่วย) → ใช้ ๒
    """
    found = []
    for line in (consideration or "").replace("​", "").splitlines():
        m = _RE_ITEM_NO.match(line.lstrip("\t"))
        if not m:
            continue
        number, head = m.group(1), m.group(2)[:30]
        hits = [(v.search(head), kind, word) for v, kind, word in _VERBS]
        hits = [(h.start(), kind, word) for h, kind, word in hits if h]
        if hits:
            _, kind, word = min(hits)
            found.append((number, kind, word))
    # ทิ้งข้อแม่ที่มีข้อย่อยซึ่งมีคำกริยาของตัวเอง
    numbers = [n for n, _, _ in found]
    return [f for f in found if not any(o.startswith(f[0] + ".") for o in numbers)]


def auto_top_request(consideration: str, unit: IssuingUnit) -> Optional[str]:
    """ภาคความประสงค์ขั้นสูงสุดจากข้อเสนอในข้อพิจารณา (ใช้เมื่อไม่มีต้นแบบ):
    "...หากเห็นชอบโปรดนำเรียน<ผู้มีอำนาจ> เพื่อโปรดพิจารณาให้ความเห็นชอบตามข้อ ๑ อนุญาตตามข้อ ๒ ...
    อำนาจในการ...เป็นของ<ผู้มีอำนาจ> ตาม[✏️ ระบุกฎหมาย...] และ<ผู้รับ>ได้โปรดสั่งการตามข้อ ๓"

    ไม่แต่งกฎหมายเอง — ช่องอ้างอำนาจเว้นให้ผู้ใช้กรอก; ไม่มีข้อเห็นชอบ/อนุญาต/อนุมัติ หรือหน่วยไม่มี
    "นำเรียน<ผู้มีอำนาจ>" ในภาคความประสงค์มาตรฐาน = None (ใช้ข้อความมาตรฐาน)
    """
    m = re.search(r"นำเรียน\s*(.+?)\s*เพื่อ", unit.request_text or "")
    items = proposal_items(consideration)
    approve = [(n, w) for n, k, w in items if k == "approve"]
    if not m or not approve:
        return None
    authority = m.group(1).strip()
    words = list(dict.fromkeys(w for _, w in approve))      # เรียงตามที่พบครั้งแรก ไม่ซ้ำ
    asks = [f"{w}ตามข้อ {_join_thai([n for n, x in approve if x == w], " ")}" for w in words]
    power = _join_thai([_POWER_WORD[w] for w in words])
    text = (f"จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียน{authority} เพื่อโปรดพิจารณา{_join_thai(asks)} "
            f"อำนาจในการ{power}เป็นของ{authority} ตาม{AUTHORITY_PLACEHOLDER}")
    command = [n for n, k, _ in items if k == "command"]
    if command and unit.recipient:
        text += f" และ{unit.recipient}ได้โปรดสั่งการตามข้อ {_join_thai(command, " ")}"
    return text


def unit_named_in_prompt(units: Iterable[IssuingUnit], prompt: str) -> Optional[IssuingUnit]:
    """หน่วยที่ผู้รับถูกระบุในคำสั่งว่า 'เสนอ <ผู้รับ>' หรือ 'ถึง <ผู้รับ>' (เช่น "ร่างบันทึกเสนอปลัดกรุงเทพมหานคร")

    ไม่นับ 'เรียน ...' เพราะมักเป็นผู้รับของหนังสือต้นเรื่องที่ผู้ใช้วางมา; หลายหน่วยตรง = เอาที่ปรากฏก่อน
    """
    text = re.sub(r"[\s​]+", "", prompt or "")
    best, best_pos = None, None
    for unit in units:
        recipient = re.sub(r"[\s​]+", "", unit.recipient or "")
        if not recipient:
            continue
        m = re.search(r"(?:เสนอ|ถึง)" + re.escape(recipient), text)
        if m and (best_pos is None or m.start() < best_pos):
            best, best_pos = unit, m.start()
    return best


def next_unit(units: Iterable[IssuingUnit], key: str) -> Optional[IssuingUnit]:
    """หน่วยขั้นถัดไปในสายการเสนอ (หน่วยถัดไปในรายการ) หรือ None ถ้าเป็นขั้นสุดท้าย"""
    units = list(units)
    for i, unit in enumerate(units):
        if unit.key == key:
            return units[i + 1] if i + 1 < len(units) else None
    return None


def _resolve_signer(signer: Signer, author: Optional[Signer]) -> Signer:
    if signer.is_author and author is not None and (author.name or author.position):
        return Signer(name=author.name or SIGNER_NAME_PLACEHOLDER,
                      position=author.position or signer.position, is_author=True)
    return Signer(name=signer.name or SIGNER_NAME_PLACEHOLDER, position=signer.position,
                  is_author=signer.is_author)


def _swap_review_party(text: Optional[str], unit: IssuingUnit, others: Iterable[IssuingUnit]) -> Optional[str]:
    """เปลี่ยน 'กลุ่มงาน...พิจารณาแล้ว' เป็นชื่อผู้พิจารณาของหน่วยนี้ (เฉพาะชื่อหน่วยที่รู้จัก)"""
    if not text or not unit.review_party:
        return text
    names = sorted({u.review_party for u in others if u.review_party and u.review_party != unit.review_party},
                   key=len, reverse=True)
    if not names:
        return text
    pattern = re.compile("(" + "|".join(re.escape(n) for n in names) + r")(\s*)(?=พิจารณาแล้ว)")
    return pattern.sub(lambda m: unit.review_party + m.group(2), text)


def apply_issuing_unit(
    doc: GovDocumentSchema,
    unit: IssuingUnit,
    day: Optional[date] = None,
    author: Optional[Signer] = None,
    units: Iterable[IssuingUnit] = (),
    replace_request: bool = False,
    roster: Sequence[OrgSigner] = (),
    use_default: bool = False,
) -> GovDocumentSchema:
    """คืนสำเนาเอกสารที่ใช้ค่าของหน่วยออกหนังสือ

    replace_request: ใช้ภาคความประสงค์มาตรฐานของหน่วยแทนข้อความเดิมเสมอ (ร่างใหม่)

    author: ชื่อ/ตำแหน่งของผู้ใช้ (แทนผู้ลงนามที่เป็น 'ผู้เสนอเรื่อง')
    units: หน่วยทั้งหมดในสาย — ใช้เปลี่ยนชื่อผู้พิจารณาและภาคความประสงค์มาตรฐานของหน่วยอื่นให้เป็นของหน่วยนี้
    roster: รายชื่อผู้ลงนามของหน่วยงาน — เติมชื่อในช่องที่ตำแหน่งตรงกัน (core/signers.py)
    use_default: ร่างใหม่ — ช่องผู้ลงนามหลักที่ยังว่างใช้ผู้ลงนามเริ่มต้นของหน่วยงาน
    """
    units = list(units)
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
    if unit.recipient:
        updated.salutation = f"เรียน {unit.recipient}"
    if unit.signers:
        stamps = [doc.signatory_stamp] + [c.stamp for c in (doc.co_signers or [])]
        signers = [_resolve_signer(s, author) for s in unit.signers]
        for i, s in enumerate(signers):
            s.stamp = stamps[i] if i < len(stamps) else False
        fill_from_roster(signers, roster, use_default)   # ชื่อจากรายชื่อผู้ลงนามของหน่วยงาน
        updated.signatory_name, updated.signatory_position = signers[0].name, signers[0].position
        updated.signatory_stamp = signers[0].stamp
        updated.co_signers = signers[1:] or None
    updated.memo_consideration = _swap_review_party(updated.memo_consideration, unit, units)
    # ขั้นสูงสุดของสาย (หน่วยสุดท้าย) ใช้ภาคความประสงค์ที่ร่างตามต้นแบบพร้อมอ้างอำนาจ ถ้ามี
    top = (doc.memo_request_top or "").strip()
    # ไม่มีต้นแบบ: ขั้นสูงสุดระบุข้อที่ขอให้เห็นชอบ/อนุญาต/อนุมัติจากข้อพิจารณา (เว้นช่องอ้างอำนาจ)
    is_top = bool(units) and unit.key == units[-1].key
    auto = auto_top_request(updated.memo_consideration, units[-1]) if units else None
    request = (top or auto or unit.request_text) if is_top else unit.request_text
    if request:
        # แทนเฉพาะภาคความประสงค์ที่ว่างหรือเป็นข้อความมาตรฐานของหน่วยอื่น (ไม่ทับข้อความที่ผู้ใช้เขียนเอง)
        standard = ({u.request_text.strip() for u in units if u.request_text}
                    | {t for t in (top, auto) if t})
        current = (updated.memo_request or "").strip()
        if replace_request or not current or current in standard:
            updated.memo_request = request
    return updated


def build_unit_chain(
    doc: GovDocumentSchema,
    units: Iterable[IssuingUnit],
    start_key: Optional[str] = None,
    day: Optional[date] = None,
    author: Optional[Signer] = None,
) -> List[tuple]:
    """ชุดบันทึกตั้งแต่หน่วยเริ่มต้นขึ้นไปจนสุดสาย: [(หน่วย, เอกสาร), ...] เรียงจากขั้นแรกไปขั้นสุดท้าย"""
    units = list(units)
    start = pick_unit(units, start_key)
    if start is None:
        return []
    chain = []
    for unit in units[units.index(start):]:
        chain.append((unit, apply_issuing_unit(doc, unit, day, author, units)))
    return chain


def units_as_dicts(units: Iterable[IssuingUnit]) -> List[dict]:
    return [u.model_dump() for u in units]

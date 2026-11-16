"""style_examples.py — คลัง "ตัวอย่างของหน่วย": หนังสือฉบับจริงที่ลงนาม/ส่งออกแล้ว ใช้สอนสำนวนให้ AI

๑. parse_example: แยกข้อความหนังสือจริง (จาก OCR / DOCX) เป็น เรื่อง / ประเภท / ภาคเหตุ / ภาคข้อเท็จจริง / ภาคความประสงค์
   - บันทึกข้อความ: ใช้หัวข้อ ต้นเรื่อง / ข้อเท็จจริง / ข้อพิจารณา (ไม่มีหัวข้อ → แบ่งแบบหนังสือภายนอก)
   - หนังสือภายนอก: ย่อหน้าแรกหลัง "เรียน/อ้างถึง/สิ่งที่ส่งมาด้วย" = ภาคเหตุ, ย่อหน้าที่ขึ้นต้น "จึง..." = ภาคความประสงค์
   ไม่ใช้ AI (ไม่มีค่าใช้จ่าย ทำซ้ำได้ ทดสอบได้)
๒. from_document: ร่างในระบบที่ผู้ใช้กด "นี่คือฉบับจริง" — มีโครงอยู่แล้ว ไม่ต้องแยก
๓. rank_examples: เลือกตัวอย่างที่ใกล้เรื่องที่สุดด้วยคำที่ตรงกัน (ไม่ใช้ embedding) เฉพาะประเภทเดียวกัน
๔. few_shot_block: ตัวอย่างสำหรับ prompt — ปิดเลข วันที่ ชื่อบุคคล และจำกัดความยาวรวม (งบ token)
   เพื่อให้ AI เรียนแค่ "สำนวน" ไม่ลอกข้อเท็จจริงของฉบับเก่า
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel

from core.models import DocType, GovDocumentSchema

# งบความยาวของตัวอย่างใน prompt (ตัวอักษรไทย ~ ๑ token ต่อ ๒–๓ ตัว → รวมราว ๒,๐๐๐ token)
PART_CHARS = 700
EXAMPLE_CHARS = 1800
TOTAL_CHARS = 4800
MAX_EXAMPLES = 3

MASK_NUMBER, MASK_DATE, MASK_NAME = "[เลข]", "[วันที่]", "[ชื่อบุคคล]"


class ParsedExample(BaseModel):
    doc_type: DocType
    subject: str = ""
    doc_number: str = ""
    doc_date: str = ""
    part_reason: str = ""       # ภาคเหตุ / ต้นเรื่อง
    part_details: str = ""      # ภาคข้อเท็จจริง / ข้อเท็จจริง
    part_purpose: str = ""      # ภาคความประสงค์ / ข้อพิจารณาและเสนอแนะ + ประโยคท้าย

    @property
    def usable(self) -> bool:
        """มีเนื้อความพอเป็นตัวอย่างสำนวน (ไม่ใช่ไฟล์ที่อ่านไม่ออก)"""
        return len((self.part_reason + self.part_details + self.part_purpose).strip()) >= 40


# ---------------------------------------------------------------- แยกข้อความ
_PAGE_MARK = re.compile(r"^-{2,}\s*หน้า(?:ที่)?\s*[\d๐-๙]+\s*-{2,}$")
_BRACKET_NOTE = re.compile(r"^\[[^\]]*\]$")                  # คำอธิบายภาพจาก AI OCR เช่น [ตราครุฑ]
_HEADER = re.compile(r"^(ส่วนราชการ|ที่|วันที่|เรื่อง|เรียน|กราบเรียน|อ้างถึง|สิ่งที่ส่งมาด้วย|บันทึกข้อความ)\b")
_SALUTATION = re.compile(r"^(?:เรียน|กราบเรียน)(?:\s|$)")
_ATTACH = re.compile(r"^(อ้างถึง|สิ่งที่ส่งมาด้วย)")
_ITEM = re.compile(r"^[\d๐-๙]+[.)]\s*")
_CLOSING = re.compile(r"^(ขอแสดงความนับถือ|ขอแสดงความนับถืออย่างยิ่ง|ด้วยความเคารพ)")
_SIGNATURE = re.compile(r"^\(\s*[^)]*\)$|^(ส่วนราชการเจ้าของเรื่อง|โทร\.?|โทรศัพท์|โทรสาร|ไปรษณีย์อิเล็กทรอนิกส์|E-?mail)", re.I)
_PURPOSE = re.compile(r"^(จึง|ทั้งนี้\s*จึง)")
_REASON_START = re.compile(r"^(ด้วย|ตามที่|ตาม|เนื่องด้วย|เนื่องจาก|อนุสนธิ|อ้างถึง|ตามหนังสือ)")
_DETAIL_START = re.compile(r"^(ในการนี้|บัดนี้|ทั้งนี้|อนึ่ง|สำหรับ|โดยที่|ในการ|ซึ่ง|ประกอบกับ)")
_MEMO_HEAD = [
    ("reason", re.compile(r"^(?:[\d๐-๙]+\.\s*)?(ต้นเรื่อง|เรื่องเดิม|ความเป็นมา)\s*:?$")),
    ("law", re.compile(r"^(?:[\d๐-๙]+\.\s*)?(ข้อกฎหมาย|ข้อระเบียบ|ระเบียบ\S*ที่เกี่ยวข้อง|กฎหมายที่เกี่ยวข้อง)\s*:?$")),
    ("details", re.compile(r"^(?:[\d๐-๙]+\.\s*)?(ข้อเท็จจริง)\s*:?$")),
    ("purpose", re.compile(r"^(?:[\d๐-๙]+\.\s*)?(ข้อพิจารณา(?:และ(?:ข้อ)?เสนอแนะ)?|ข้อเสนอแนะ|ข้อเสนอ|ความเห็น)\s*:?$")),
]


def _lines(text: str) -> List[str]:
    """บรรทัดที่สะอาด (คงบรรทัดว่างไว้เป็นตัวแบ่งย่อหน้า)"""
    out = []
    for raw in (text or "").replace("​", "").replace("\r", "").split("\n"):
        line = " ".join(raw.split())
        if _PAGE_MARK.match(line) or _BRACKET_NOTE.match(line):
            continue
        out.append(line)
    return out


def _join(lines: Iterable[str]) -> str:
    """รวมบรรทัดเป็นย่อหน้า: บรรทัดที่ขึ้นต้นด้วยเลขข้อหรือหลังบรรทัดว่างขึ้นย่อหน้าใหม่ ที่เหลือต่อกัน"""
    paras: List[str] = []
    fresh = True
    for line in lines:
        if not line:
            fresh = True
            continue
        if fresh or _ITEM.match(line) or not paras:
            paras.append(line)
        else:
            # OCR ตัดบรรทัดกลางประโยค: ภาษาไทยต่อกันไม่เว้นวรรค (ยกเว้นท้ายบรรทัดเป็นตัวเลข/ละติน)
            prev = paras[-1]
            sep = " " if re.search(r"[A-Za-z0-9๐-๙.,)]$", prev) else ""
            paras[-1] = prev + sep + line
        fresh = False
    return "\n".join(paras).strip()


def _body_lines(lines: List[str]) -> Tuple[List[str], List[str]]:
    """(ส่วนหัวก่อนเนื้อความ, เนื้อความ) — เนื้อความเริ่มหลัง "เรียน" + อ้างถึง/สิ่งที่ส่งมาด้วย และจบก่อนคำลงท้าย/ผู้ลงนาม"""
    start = next((i + 1 for i, l in enumerate(lines) if _SALUTATION.match(l)), None)
    if start is None:                     # ไม่พบ "เรียน" — ข้ามบรรทัดหัวหนังสือช่วงต้น
        start = 0
        while start < len(lines) and (not lines[start] or _HEADER.match(lines[start])):
            start += 1
    head = lines[:start]
    i, in_attach = start, False
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        if _ATTACH.match(line):
            in_attach = True
        elif not in_attach or _REASON_START.match(line) or _DETAIL_START.match(line) or _PURPOSE.match(line):
            break
        # ที่เหลือ: รายการ ๑. ๒. หรือบรรทัดต่อของ อ้างถึง/สิ่งที่ส่งมาด้วย
        head.append(line)
        i += 1
    body = []
    for line in lines[i:]:
        if line and (_CLOSING.match(line) or _SIGNATURE.match(line)):
            break
        body.append(line)
    return head, body


def _split_external(body: List[str]) -> Tuple[str, str, str]:
    """ภาคเหตุ / ภาคข้อเท็จจริง / ภาคความประสงค์ จากย่อหน้า"""
    blocks: List[List[str]] = [[]]
    for line in body:
        if not line:
            if blocks[-1]:
                blocks.append([])
            continue
        # ไม่มีบรรทัดว่างคั่น (OCR บางตัว): ขึ้นย่อหน้าใหม่เมื่อเจอคำขึ้นต้นภาคถัดไป
        if blocks[-1] and (_PURPOSE.match(line) or (_DETAIL_START.match(line) and len(blocks) == 1)):
            blocks.append([])
        blocks[-1].append(line)
    blocks = [b for b in blocks if b]
    if not blocks:
        return "", "", ""
    purpose_at = next((i for i in range(len(blocks) - 1, -1, -1) if _PURPOSE.match(blocks[i][0])), None)
    if purpose_at is None or purpose_at == 0:
        purpose_at = len(blocks) if len(blocks) == 1 else len(blocks) - 1
    reason = _join(blocks[0])
    details = "\n".join(_join(b) for b in blocks[1:purpose_at])
    purpose = "\n".join(_join(b) for b in blocks[purpose_at:])
    return reason, details, purpose


def _split_memo(body: List[str]) -> Optional[Tuple[str, str, str]]:
    """แยกตามหัวข้อของบันทึกข้อความ; ไม่มีหัวข้อเลย = None"""
    parts: Dict[str, List[str]] = {}
    current = None
    for line in body:
        key = next((k for k, rx in _MEMO_HEAD if rx.match(line)), None)
        if key:
            current = key
            parts.setdefault(key, [])
            continue
        if current is None:
            parts.setdefault("reason", []).append(line)    # ข้อความก่อนหัวข้อแรก ถือเป็นต้นเรื่อง
        else:
            parts[current].append(line)
    if not any(k in parts for k in ("details", "purpose")):
        return None
    return (_join(parts.get("reason", [])), _join(parts.get("details", [])), _join(parts.get("purpose", [])))


def parse_example(text: str) -> ParsedExample:
    """แยกหนังสือฉบับจริงเป็นส่วน ๆ (ข้อความจาก OCR/DOCX)"""
    from core.extractor import parse_govdoc_metadata

    lines = _lines(text)
    head_text = " ".join(lines[:12])
    is_memo = "บันทึกข้อความ" in head_text.replace(" ", "")
    meta = parse_govdoc_metadata("\n".join(l for l in lines if l))
    _, body = _body_lines(lines)
    split = _split_memo(body) if is_memo else None
    reason, details, purpose = split or _split_external(body)
    subject = (meta.get("subject") or "").strip()
    return ParsedExample(
        doc_type=DocType.INTERNAL if is_memo else DocType.EXTERNAL,
        subject=subject[:300],
        doc_number=(meta.get("doc_no") or "")[:120],
        doc_date=(meta.get("doc_date") or "")[:120],
        part_reason=reason, part_details=details, part_purpose=purpose,
    )


def from_document(doc: GovDocumentSchema) -> ParsedExample:
    """ร่างในระบบที่ผู้ใช้ยืนยันว่าเป็นฉบับจริง (ข้อความตามที่แก้ล่าสุด)"""
    if doc.doc_type == DocType.INTERNAL:
        intro, facts, _law, consideration, request = doc._memo_parts()
        reason, details = intro, facts
        purpose = "\n".join(x for x in (consideration, request) if x)
    else:
        reason, details, purpose = doc.paragraph_reason, doc.paragraph_details or "", doc.paragraph_purpose
    return ParsedExample(
        doc_type=doc.doc_type, subject=(doc.subject or "")[:300],
        doc_number=(doc.doc_number or "")[:120], doc_date=(doc.doc_date or "")[:120],
        part_reason=(reason or "").strip(), part_details=(details or "").strip(), part_purpose=(purpose or "").strip(),
    )


# ---------------------------------------------------------------- เลือกตัวอย่าง
def keywords_of(*texts: str, limit: int = 300) -> str:
    """คำสำคัญ (ตัดคำไทย ตัดคำทั่วไป) เก็บไว้ในฐานข้อมูล — ตอนร่างไม่ต้องตัดคำของทุกตัวอย่างซ้ำ"""
    from core.legal_suggest import _words

    seen: Dict[str, None] = {}
    for text in texts:
        for w in _words(text or ""):
            if not any(ch in w for ch in "[]✏️") and w not in seen:
                seen[w] = None
    return " ".join(list(seen)[:limit])


def rank_examples(context: str, rows: Sequence[dict], limit: int = MAX_EXAMPLES,
                  min_score: float = 1.5) -> List[Tuple[dict, float]]:
    """เรียงตัวอย่างตามคำที่ตรงกับเรื่องใหม่ (คำหายากในคลังได้น้ำหนักมากกว่า; คำในชื่อเรื่องของตัวอย่าง ×๒)
    rows: {"id", "subject", "keywords"} — ผู้เรียกกรองประเภทหนังสือมาแล้ว"""
    from core.legal_suggest import _words

    ctx = set(_words((context or "")[:6000]))
    if not ctx or not rows:
        return []
    sets = [set((r.get("keywords") or "").split()) for r in rows]
    subj = [set(_words(r.get("subject") or "")) for r in rows]
    n = len(rows)
    df: Dict[str, int] = {}
    for ws in sets:
        for w in ws:
            df[w] = df.get(w, 0) + 1
    scored = []
    for row, ws, ss in zip(rows, sets, subj):
        hit = ctx & ws
        score = sum(math.log(1 + n / df.get(w, 1)) * (2 if w in ss else 1) for w in hit)
        # ตัวอย่างยาวมีคำมาก — หารด้วยรากของจำนวนคำเล็กน้อย ไม่ให้ฉบับยาวชนะเสมอ
        score /= max(1.0, math.sqrt(len(ws) / 80))
        if len(hit) >= 2 and score >= min_score:
            scored.append((row, round(score, 2)))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


# ---------------------------------------------------------------- ใส่ใน prompt
_THAI_MONTHS = ("มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|"
                r"ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.")
_DATE_RX = re.compile(rf"(?:วันที่\s*)?[\d๐-๙]{{1,2}}\s*(?:{_THAI_MONTHS})\s*(?:พ\.ศ\.\s*)?[\d๐-๙]{{2,4}}")
_NUM_RX = re.compile(r"[\d๐-๙]+(?:[,.:/][\d๐-๙]+)*")
# คำนำหน้าชื่อ + ชื่อ (+ นามสกุล) — ยกเว้นคำที่ขึ้นต้นด้วย "นาย/นาง" แต่ไม่ใช่ชื่อคน
_NAME_RX = re.compile(
    r"(?:นางสาว|นาง(?!พยาบาล)|นาย(?!ก|ทะเบียน|อำเภอ|ช่าง|แพทย์|สัตวแพทย์|ตำรวจ|ทหาร|งาน|จ้าง|หน้า|ด่าน|ประตู|สนาม|ท้าย|ร้อย|พัน|พล|เรือ|สิบ)"
    r"|ว่าที่\s*ร(?:้อย)?\.?\s*\S+|ดร\.|ศ\.|รศ\.|ผศ\.)\s*[ก-ฮ][ก-๙]*(?:\s+[ก-ฮ][ก-๙]*)?"
)


def mask_facts(text: str) -> str:
    """ปิดข้อเท็จจริงเฉพาะฉบับ (วันที่ ตัวเลข ชื่อบุคคล) ก่อนส่งเป็นตัวอย่าง — AI จะลอกค่าเก่ามาไม่ได้"""
    text = _DATE_RX.sub(MASK_DATE, text or "")
    text = _NAME_RX.sub(MASK_NAME, text)
    text = _NUM_RX.sub(MASK_NUMBER, text)
    # ข้อ ๑. ๑.๑ (เลขข้อ) คงรูปแบบไว้ — ไม่ใช่ข้อเท็จจริง
    text = re.sub(r"(^|\n)\[เลข\](\.\s?)", r"\1๑\2", text)
    return text


def _cut(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind("\n"), cut.rfind(" "))
    return (cut[:stop] if stop > limit * 0.6 else cut).rstrip() + " …"


_LABELS = {
    DocType.INTERNAL: ("ต้นเรื่อง", "ข้อเท็จจริง", "ข้อพิจารณาและเสนอแนะ"),
    DocType.EXTERNAL: ("ภาคเหตุ", "ภาคข้อเท็จจริง", "ภาคความประสงค์"),
}


def few_shot_block(examples: Sequence[dict], total_chars: int = TOTAL_CHARS) -> str:
    """ส่วนตัวอย่างใน prompt — examples: แถว {"doc_type","subject","part_reason","part_details","part_purpose"}
    เรียงจากใกล้เรื่องที่สุด; ตัวที่ทำให้เกินงบรวมถูกตัดทิ้ง"""
    chunks: List[str] = []
    used = 0
    for ex in examples[:MAX_EXAMPLES]:
        doc_type = DocType(ex.get("doc_type") or "internal")
        labels = _LABELS[doc_type]
        lines = [f"เรื่อง: {mask_facts(ex.get('subject') or '')}"]
        for label, key in zip(labels, ("part_reason", "part_details", "part_purpose")):
            value = _cut(mask_facts(ex.get(key) or ""), PART_CHARS)
            if value:
                lines.append(f"{label}:\n{value}")
        body = _cut("\n".join(lines), EXAMPLE_CHARS)
        if chunks and used + len(body) > total_chars:
            break
        kind = "บันทึกข้อความ" if doc_type == DocType.INTERNAL else "หนังสือภายนอก"
        chunks.append(f'<example n="{len(chunks) + 1}" type="{kind}">\n{body}\n</example>')
        used += len(body)
    if not chunks:
        return ""
    return (
        "ตัวอย่างสำนวนจากหนังสือฉบับจริงของหน่วยงาน (ใช้เป็นแบบ \"สำนวน ลำดับความ คำขึ้นต้น-ลงท้ายของแต่ละภาค\" เท่านั้น):\n"
        "- ห้ามนำข้อเท็จจริงในตัวอย่างมาใช้ (ชื่อบุคคล หน่วยงานผู้ขอ เลขที่ วันที่ เวลา จำนวนเงิน สถานที่ ชื่องาน) "
        "ข้อเท็จจริงทุกอย่างต้องมาจากต้นเรื่อง/คำสั่งของเรื่องใหม่เท่านั้น ไม่มีก็เว้น [✏️ ระบุ...]\n"
        f"- {MASK_NUMBER} {MASK_DATE} {MASK_NAME} ในตัวอย่างคือส่วนที่ปิดไว้ ห้ามคัดลอกลงในร่าง\n"
        + "\n".join(chunks)
    )


def unmask_leftovers(text: str) -> str:
    """AI คัดลอกส่วนที่ปิดไว้มา → เปลี่ยนเป็นช่องให้ผู้ใช้กรอก"""
    return ((text or "").replace(MASK_DATE, "[✏️ ระบุวันที่]").replace(MASK_NAME, "[✏️ ระบุชื่อ]")
            .replace(MASK_NUMBER, "[✏️ ระบุ]"))

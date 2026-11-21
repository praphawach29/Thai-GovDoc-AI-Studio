"""
docx_template.py — ใช้ไฟล์ Word ที่ผู้ใช้แนบเป็นแม่แบบ: คงรูปแบบ ตาราง ระยะ ฟอนต์ ครุฑ ของไฟล์เดิมทั้งหมด
แล้วแก้เฉพาะ "ข้อความ" ทีละย่อหน้า (AI เสนอ → ผู้ใช้ตรวจ → สร้างไฟล์ใหม่)

- segments(): ย่อหน้าทุกย่อหน้าในเนื้อความและในตาราง (รวมย่อหน้าว่างในตาราง ซึ่งใช้จัดบรรทัดให้ตรงกัน)
  พร้อมรหัสคงที่ "p<ลำดับ>" ตามลำดับในไฟล์ และตำแหน่ง (เช่น "ตาราง 2 แถว 3 ช่อง 2")
- apply_edits(): แทนข้อความของย่อหน้าที่ระบุ แก้เฉพาะช่วงที่ต่างจากเดิม (คงตัวหนา/ขีดเส้นใต้ของส่วนที่ไม่เปลี่ยน
  เช่น ป้าย "ชื่อโครงการ" ตัวหนา) — run ที่มีรูป/ฟิลด์ไม่ถูกแตะ
ข้อจำกัด: เพิ่ม/ลบย่อหน้าหรือแถวตารางไม่ได้ (แก้ได้เฉพาะย่อหน้าที่มีอยู่ ช่องว่างเว้นเป็นข้อความว่าง)
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, Iterator, List, Tuple

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

MAX_SEGMENTS = 1500           # ไฟล์ยาวกว่านี้ไม่รับ (คำตอบ AI ใหญ่เกินเวลาที่มี)


@dataclass
class Segment:
    id: str
    where: str          # "เนื้อความ" / "ตาราง 2 แถว 3 ช่อง 2"
    text: str


def _iter_paragraphs(doc) -> Iterator[Tuple[Paragraph, str]]:
    """ย่อหน้าตามลำดับในไฟล์ (เนื้อความ + ตาราง + ตารางซ้อน) — ช่องที่รวมเซลล์นับครั้งเดียว"""
    table_no = 0

    def walk_table(table: Table, label: str):
        for r, row in enumerate(table.rows, 1):
            seen = set()
            col = 0
            for cell in row.cells:
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                col += 1
                where = f"{label} แถว {r} ช่อง {col}"
                for para in cell.paragraphs:
                    yield para, where
                for i, inner in enumerate(cell.tables, 1):
                    yield from walk_table(inner, f"{where} ตารางย่อย {i}")

    for element in doc.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(element, doc), "เนื้อความ"
        elif tag == "tbl":
            table_no += 1
            yield from walk_table(Table(element, doc), f"ตาราง {table_no}")


def _clean(text: str) -> str:
    return (text or "").replace("​", "")


def segments(data: bytes) -> List[Segment]:
    """ย่อหน้าที่ AI แก้ได้: ย่อหน้าในตารางทุกย่อหน้า (รวมที่ว่าง) + ย่อหน้าเนื้อความที่มีข้อความ
    รหัส p<n> นับทุกย่อหน้า (รวมย่อหน้าว่างที่ไม่ส่ง) จึงตรงกันทั้งตอนเสนอและตอนสร้างไฟล์"""
    doc = Document(io.BytesIO(data))
    out = []
    for n, (para, where) in enumerate(_iter_paragraphs(doc), 1):
        text = _clean(para.text)
        if text.strip() or where != "เนื้อความ":
            out.append(Segment(id=f"p{n}", where=where, text=text))
    return out


# ---------------------------------------------------------------- แทนข้อความ
def _text_runs(para: Paragraph):
    """run ที่เป็นข้อความล้วน (ไม่มีรูป/ฟิลด์/แท็บ/ขึ้นบรรทัด) — run อื่นคงไว้ตามเดิม"""
    out = []
    for run in para.runs:
        r = run._r
        if r.find(qn("w:drawing")) is not None or r.find(qn("w:pict")) is not None or r.find(qn("w:fldChar")) is not None:
            continue
        out.append(run)
    return out


def _set_run_text(run, text: str) -> None:
    """ข้อความของ run (\\n = ขึ้นบรรทัดใน run, \\t = แท็บ) — python-docx แปลงให้"""
    run.text = text


def replace_paragraph_text(para: Paragraph, new: str) -> bool:
    """แทนข้อความย่อหน้า: แก้เฉพาะช่วงกลางที่ต่าง (คงรูปแบบของส่วนหัว/ท้ายที่เหมือนเดิม) — คืน True ถ้าเปลี่ยน"""
    runs = _text_runs(para)
    texts = [_clean(r.text) for r in runs]
    old = "".join(texts)
    new = _clean(new)
    if old == new:
        return False
    if not runs:
        para.add_run(new)
        return True
    pre = 0
    while pre < min(len(old), len(new)) and old[pre] == new[pre]:
        pre += 1
    suf = 0
    while suf < min(len(old), len(new)) - pre and old[-1 - suf] == new[-1 - suf]:
        suf += 1
    start, end = pre, len(old) - suf             # ช่วงเดิมที่ถูกแทน [start, end)
    middle = new[pre:len(new) - suf]

    # run ที่รับข้อความใหม่ = run ที่มีอักษรตำแหน่ง start (แทรกท้ายสุด = run สุดท้าย)
    spans, pos = [], 0
    for text in texts:
        spans.append((pos, pos + len(text)))
        pos += len(text)
    target = next((i for i, (x, y) in enumerate(spans) if x <= start < y), len(runs) - 1)
    for i, (run, text, (x, y)) in enumerate(zip(runs, texts, spans)):
        if i < target:
            continue
        if i == target:
            _set_run_text(run, text[:max(0, start - x)] + middle + (text[end - x:] if end <= y else ""))
        elif y <= end:
            _set_run_text(run, "")                  # อยู่ในช่วงที่ถูกแทนทั้ง run
        elif x < end:
            _set_run_text(run, text[end - x:])
    return True


def apply_edits(data: bytes, edits: Dict[str, str]) -> Tuple[bytes, int]:
    """สร้างไฟล์ใหม่จากแม่แบบ: edits = {รหัสย่อหน้า: ข้อความใหม่} — คืน (ไฟล์, จำนวนย่อหน้าที่เปลี่ยน)"""
    doc = Document(io.BytesIO(data))
    changed = 0
    for n, (para, _) in enumerate(_iter_paragraphs(doc), 1):
        key = f"p{n}"
        if key in edits and replace_paragraph_text(para, edits[key]):
            changed += 1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), changed

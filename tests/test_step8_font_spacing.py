"""
Step 8: ฟอนต์และระยะย่อหน้าตามแบบบันทึกข้อความที่หน่วยงานใช้จริง
- ฟอนต์หลัก TH SarabunIT๙ (เลือก TH SarabunPSK / TH Sarabun New รายฉบับได้)
- ระยะก่อนย่อหน้า: "เรียน" 6 pt, ต้นเรื่อง 0 pt, ขึ้นหัวข้อใหม่ 6 pt, ในหัวข้อเดียวกัน 0 pt
"""

import re

from docx import Document
from fastapi.testclient import TestClient

from core.memo_layout import SECTION_GAP_PT
from core.templates_library import PRESET_TEMPLATES
from core.word_exporter import export_govdoc_to_docx
from server.main import app


def _memo():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.memo_intro = "๑. ต้นเรื่องข้อแรก\n๒. ต้นเรื่องข้อสอง"
    doc.memo_facts = "ข้อเท็จจริงย่อหน้าแรก\nข้อเท็จจริงย่อหน้าสอง"
    doc.memo_law = None
    doc.memo_consideration = "กลุ่มงานพิจารณาแล้ว เห็นควรพิจารณา"
    doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา"
    return doc


def _before(p):
    return p.paragraph_format.space_before.pt if p.paragraph_format.space_before is not None else 0.0


def test_memo_blocks_spacing_rules():
    gaps = [(b.lead or b.text[:12], b.space_before_pt) for b in _memo().get_memo_blocks()]
    assert gaps[0] == ("ต้นเรื่อง", 0.0)                       # หัวข้อแรกต่อจาก "เรียน"
    assert all(g == 0.0 for t, g in gaps if t.startswith(("๑. ต้น", "๒. ต้น", "ข้อเท็จจริงย่อ")))
    assert dict(gaps)["ข้อเท็จจริง"] == SECTION_GAP_PT == 6.0
    assert dict(gaps)["ข้อพิจารณาและเสนอแนะ"] == 6.0
    assert gaps[-1][1] == 6.0 and gaps[-1][0].startswith("จึงเรียนมา")


def test_word_paragraph_spacing_and_default_font(tmp_path):
    out = tmp_path / "m.docx"
    export_govdoc_to_docx(_memo(), str(out))
    paras = Document(str(out)).paragraphs
    plain = lambda p: p.text.replace("\u200b", "").strip()          # Word ได้ ZWSP สำหรับตัดคำ
    gap = lambda start: _before(next(p for p in paras if plain(p).startswith(start)))
    assert gap("เรียน") == 6.0
    assert gap("ต้นเรื่อง") == 0.0 and gap("๒. ต้นเรื่องข้อสอง") == 0.0
    assert gap("ข้อเท็จจริง  ") == 6.0 and gap("ข้อเท็จจริงย่อหน้าสอง") == 0.0
    assert gap("ข้อพิจารณาและเสนอแนะ") == 6.0
    assert gap("จึงเรียนมา") == 6.0
    fonts = {r.font.name for p in paras for r in p.runs if r.text.strip()}
    assert fonts == {"TH SarabunIT๙"}


def _render_header(client, doc):
    from io import BytesIO
    import pdfplumber
    pdf = client.post("/api/v1/export/pdf", json=doc).content
    with pdfplumber.open(BytesIO(pdf)) as f:
        return pdf, f.pages[0].crop((80, 95, 560, 125)).to_image(resolution=100).original.convert("L")


def test_pdf_uses_chosen_font_file():
    """TH SarabunIT๙ แสดงเลขอารบิกเป็นรูปเลขไทย ส่วน PSK ไม่ — ใช้ตรวจว่า PDF ใช้ไฟล์ฟอนต์ที่เลือกจริง
    (ไฟล์ IT๙ ใช้ชื่อภายใน THSarabunPSK เหมือน PSK จึงตรวจจากชื่อฟอนต์อย่างเดียวไม่ได้)"""
    from PIL import ImageChops
    client = TestClient(app)
    doc = _memo().model_dump(mode="json")
    doc["use_thai_numerals"] = False
    doc["dept_name"] = "กองการกีฬา โทร. 0 2246 8079"
    pdf_it9, it9 = _render_header(client, {**doc, "font_family": None})     # ค่าเริ่มต้น = IT๙
    _, psk = _render_header(client, {**doc, "font_family": "psk"})
    pdf_new, _ = _render_header(client, {**doc, "font_family": "sarabun_new"})
    assert ImageChops.difference(it9, psk).getbbox() is not None
    assert b"THSarabunPSK" in pdf_it9 and b"SarabunNew" in pdf_new

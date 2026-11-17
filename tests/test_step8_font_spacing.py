"""
Step 8: ฟอนต์และระยะย่อหน้าตามแบบบันทึกข้อความที่หน่วยงานใช้จริง
- ฟอนต์หลัก TH SarabunIT๙ (เลือก TH SarabunPSK / TH Sarabun New รายฉบับได้)
- ระยะก่อนย่อหน้า: "เรียน" 6 pt, ทุกหัวข้อรวมต้นเรื่อง 6 pt, ในหัวข้อเดียวกัน 0 pt
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
    assert gaps[0] == ("ต้นเรื่อง", 6.0)                       # ต้นเรื่องเว้น 6 pt จากบรรทัดบน
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
    assert gap("ต้นเรื่อง") == 6.0 and gap("๒. ต้นเรื่องข้อสอง") == 0.0
    assert gap("ข้อเท็จจริง") == 6.0 and gap("ข้อเท็จจริงย่อหน้าสอง") == 0.0
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


def test_headings_start_at_body_indent_in_word(tmp_path):
    out = tmp_path / "h.docx"
    export_govdoc_to_docx(_memo(), str(out))
    paras = Document(str(out)).paragraphs
    head = next(p for p in paras if p.text.strip() == "ต้นเรื่อง")
    assert abs(head.paragraph_format.first_line_indent.cm - 2.5) < 0.01


def test_free_indent_with_tabs_and_custom_headings():
    from core.memo_layout import line_indent_cm
    assert line_indent_cm("๑. ข้อหลัก") == 2.5
    assert line_indent_cm("๑.๑ ข้อย่อย") == 3.5
    assert line_indent_cm("1.1.1 ข้อย่อยสุด") == 4.5
    assert line_indent_cm("\t\t๑. ผู้ใช้ย่นเข้าเอง") == 3.5      # แท็บกำหนดเองแทนค่าอัตโนมัติ
    assert line_indent_cm("\t๑.๑ ผู้ใช้ดึงกลับ") == 2.5
    doc = _memo().model_copy(update={
        "memo_facts": "๑. ข้อแรก\n\t\t\tข้อความลึก\n๑.๑ ย่อย",
        "memo_headings": {"facts": "ข้อเท็จจริงและการตรวจสอบ", "law": ""},
        "memo_law": "ระเบียบ ฯ",
    })
    blocks = doc.get_memo_blocks()
    leads = [b.lead for b in blocks if b.kind == "heading"]
    assert "ข้อเท็จจริงและการตรวจสอบ" in leads and "ข้อกฎหมาย" not in leads
    law = next(b for b in blocks if b.text == "ระเบียบ ฯ")
    assert law.space_before_pt == 6.0                  # หัวข้อถูกซ่อน เนื้อความยังเว้นระยะขึ้นหัวข้อใหม่
    deep = next(b for b in blocks if b.text == "ข้อความลึก")
    assert deep.indent_cm == 4.5 and "\t" not in deep.text


def test_memo_signers_centered_like_pdf(tmp_path):
    out = tmp_path / "s.docx"
    export_govdoc_to_docx(_memo(), str(out))
    paras = Document(str(out)).paragraphs
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    sig = [p for p in paras if p.paragraph_format.left_indent is not None
           and abs(p.paragraph_format.left_indent.cm - 6.0) < 0.01]
    assert len(sig) >= 2 and all(p.alignment == WD_ALIGN_PARAGRAPH.CENTER for p in sig)


def _header_lines(tmp_path, subject):
    import re
    out = tmp_path / "sub.docx"
    export_govdoc_to_docx(_memo().model_copy(update={"subject": subject}), str(out))
    paras = Document(str(out)).paragraphs
    def lines(start):
        p = next(p for p in paras if p.text.startswith(start))
        return [tuple(float(v) for v in m) for m in
                re.findall(r'from="([\d.]+)pt,([\d.]+)pt" to="([\d.]+)pt,[\d.]+pt"', p._p.xml)]
    return lines


def test_header_dotted_lines_are_fixed_shapes(tmp_path):
    """เส้นประ ๓ บรรทัดบนเป็นรูปร่างเส้นตรงล็อกกับบรรทัด (แบบที่หน่วยงานวางเส้นเองใน Word) —
    แก้ข้อความแล้วเส้นอยู่ที่เดิม; เรื่องยาวกี่บรรทัดก็มีเส้นเฉพาะบรรทัดแรก ยาวถึงขอบขวา (16 ซม. = 453.5 pt)"""
    lines = _header_lines(tmp_path, "ขอเชิญเป็นเจ้าภาพร่วมจัดการแข่งขันกีฬาวิ่งเปี้ยวชิงแชมป์แห่งประเทศไทย "
                                    "ชิงถ้วยพระราชทาน ประจำปี ๒๕๗๐")
    dept, meta, sub = lines("ส่วนราชการ"), lines("ที่"), lines("เรื่อง")
    assert len(dept) == 1 and len(meta) == 2 and len(sub) == 1
    for x1, y, x2 in dept + sub + meta[1:]:
        assert abs(x2 - 453.54) < 0.1 and 15 < y < 25
    assert all(0 < x1 < 100 for x1, _, _ in dept + sub + meta[:1])
    assert meta[0][2] < 7.5 / 2.54 * 72 < meta[1][0]          # "ที่" ถึงก่อน "วันที่" แล้วต่อหลัง "วันที่"


def test_docx_has_no_blank_thumbnail(tmp_path):
    import zipfile
    out = tmp_path / "t.docx"
    export_govdoc_to_docx(_memo(), str(out))
    with zipfile.ZipFile(out) as z:
        assert "thumbnail" not in z.read("_rels/.rels").decode()
        assert not any("thumbnail" in n for n in z.namelist())


def test_width_measure_counts_letter_spacing():
    """Word เว้นระยะตัวอักษร 0.4 pt ทุกตัว — ไม่นับจะตัดบรรทัดเรื่องเกินจริง (คำล้นไปบรรทัดที่ ๒ พร้อมเส้นประ)"""
    from core import word_exporter as w
    text = "ขอเชิญเป็นเจ้าภาพร่วมจัดการแข่งขันกีฬาวิ่งเปี้ยวชิงแชมป์แห่งประเทศไทย ชิงถ้วย"
    plain = w._text_width_cm(text)
    tok = w._LETTER_SPACING.set(0.4)
    try:
        spaced = w._text_width_cm(text)
    finally:
        w._LETTER_SPACING.reset(tok)
    assert abs(spaced - plain - len(text) * 0.4 / 72 * 2.54) < 1e-6
    # เรื่องที่ Word ตัดบรรทัดหลัง "ชิงถ้วย" (ภาพจาก Word จริง) — วัดแบบเดียวกับ Word ต้องตัดตรงกัน
    from core.word_exporter import _split_first_line
    from core.thai_segmenter import insert_zwsp
    tok = w._LETTER_SPACING.set(0.4)
    try:
        _, rest = _split_first_line(insert_zwsp(
            "ขอเชิญเป็นเจ้าภาพร่วมจัดการแข่งขันกีฬาวิ่งเปี้ยวชิงแชมป์แห่งประเทศไทย ชิงถ้วยพระราชทาน ประจำปี ๒๕๗๐"),
            16.0 - 1.25 - 0.3)
    finally:
        w._LETTER_SPACING.reset(tok)
    assert rest.replace("\u200b", "").startswith("พระราชทาน")

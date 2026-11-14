"""
Step 4: ตำแหน่งจริงในเอกสารที่ส่งออก เทียบกับคู่มือการพิมพ์หนังสือราชการ
และโปรไฟล์บันทึกข้อความแบบกรุงเทพมหานคร (วัดพิกัดจาก PDF / อ่าน XML ของ DOCX)
"""

import io
import zipfile

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from server.main import app
from core.models import ExportOptions, SecretLevel, UrgencyLevel
from core.templates_library import PRESET_TEMPLATES
from core.typst_exporter import generate_typst_content
from core.word_exporter import export_govdoc_to_docx

CM = 72 / 2.54          # pt ต่อ 1 ซม.
LEFT = 3 * CM           # ขอบซ้าย 3 ซม.
LINE_CM = 20.8 / CM     # ระยะบรรทัด single ของ TH Sarabun 16 pt


def _external_doc(**changes):
    doc = PRESET_TEMPLATES["speaker_request"].schema.model_copy(deep=True)
    doc.doc_number = "ทส 0001/123"
    doc.doc_date = "14 พฤศจิกายน 2569"
    doc.signatory_name = "นายสมชาย ใจดี"  # ไม่ใส่วงเล็บ เพื่อวัดเส้นฐานได้ตรง (วงเล็บห้อยต่ำกว่าบรรทัด)
    doc.signatory_position = "ผู้อำนวยการกองทดสอบ"
    doc.use_thai_numerals = False
    for k, v in changes.items():
        setattr(doc, k, v)
    return doc


def _pdf_page(doc):
    res = TestClient(app).post("/api/v1/export/pdf", json=doc.model_dump(mode="json"))
    assert res.status_code == 200, res.text
    return pdfplumber.open(io.BytesIO(res.content)).pages[0]


def _word(page, text):
    for w in page.extract_words():
        if w["text"] == text:
            return w
    raise AssertionError(f"ไม่พบคำ {text!r}")


def _red_chars(page):
    return [c for c in page.chars if c.get("non_stroking_color") and tuple(round(x, 2) for x in c["non_stroking_color"])[:1] == (0.75,)]


# ---------------------------------------------------------------- PDF หนังสือภายนอก
@pytest.mark.requires_typst
def test_external_header_sits_on_garuda_foot_and_month_on_right_foot():
    page = _pdf_page(_external_doc())
    garuda_bottom_cm = 2.5 + 3.0
    number = _word(page, "0001/123")
    assert abs(number["bottom"] / CM - garuda_bottom_cm) < 0.15

    day = _word(page, "14")
    month_start_cm = (day["x1"] - LEFT) / CM + 0.15  # ช่องว่างหลังเลขวัน
    assert 8.5 < month_start_cm < 8.95, month_start_cm


@pytest.mark.requires_typst
def test_external_signature_block_spacing():
    page = _pdf_page(_external_doc())
    rows = sorted({round(w["bottom"], 1) for w in page.extract_words()})
    name = next(w for w in page.extract_words() if w["text"].startswith("น") and w["bottom"] > 15 * CM)
    closing_bottom = max(b for b in rows if b < name["bottom"] - 2 * CM)
    # ชื่อผู้ลงนามอยู่ใต้คำลงท้าย 4 Enter
    assert abs((name["bottom"] - closing_bottom) / CM - 4 * LINE_CM) < 0.1
    # ชื่อเริ่มใกล้แนวกึ่งกลาง (คำลงท้ายเริ่มที่ 8 ซม. และกึ่งกลางร่วมกัน)
    assert 7.5 < (name["x0"] - LEFT) / CM < 9.0


@pytest.mark.requires_typst
def test_external_urgency_32pt_and_secret_top_and_bottom():
    page = _pdf_page(_external_doc(urgency=UrgencyLevel.URGENT, secret=SecretLevel.SECRET))
    red = _red_chars(page)
    assert red, "ต้องมีตัวอักษรสีแดง (ชั้นความเร็ว/ชั้นความลับ)"
    assert max(c["size"] for c in red) >= 32
    secret_rows = {round(c["top"] / CM) for c in red if c["size"] < 30}
    assert min(secret_rows) < 3 and max(secret_rows) > 26, secret_rows


# ---------------------------------------------------------------- PDF บันทึกข้อความ
def test_memo_typst_defaults_to_bma_profile():
    doc = PRESET_TEMPLATES["procurement_approval"].schema
    code = generate_typst_content(doc)
    assert "top_margin: 1.5cm" in code and "title_size: 32pt" in code
    manual = generate_typst_content(doc, layout_profile="manual_memo")
    assert "top_margin: 2.5cm" in manual and "title_size: 29pt" in manual


@pytest.mark.requires_typst
def test_memo_pdf_shows_urgency_and_secret():
    doc = PRESET_TEMPLATES["procurement_approval"].schema.model_copy(deep=True)
    doc.urgency = UrgencyLevel.MOST_URGENT
    doc.secret = SecretLevel.VERY_SECRET
    page = _pdf_page(doc)
    red = _red_chars(page)
    assert max(c["size"] for c in red) >= 32
    assert {round(c["top"] / CM) < 3 for c in red if c["size"] < 30} == {True, False}


# ---------------------------------------------------------------- DOCX
def _docx_xml(tmp_path, doc, options=None):
    out = tmp_path / "out.docx"
    export_govdoc_to_docx(doc, str(out), options=options)
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xml")}


@pytest.mark.parametrize("template_id", ["speaker_request", "procurement_approval"])
def test_docx_marks_urgency_and_secret_on_every_page(tmp_path, template_id):
    doc = PRESET_TEMPLATES[template_id].schema.model_copy(deep=True)
    doc.urgency = UrgencyLevel.URGENT
    doc.secret = SecretLevel.SECRET
    xml = _docx_xml(tmp_path, doc)
    assert '<w:sz w:val="64"/>' in xml["word/document.xml"]  # ชั้นความเร็ว 32 pt
    assert "ด่วน" in xml["word/document.xml"]
    headers = [v for k, v in xml.items() if k.startswith("word/header")]
    footers = [v for k, v in xml.items() if k.startswith("word/footer")]
    assert headers and all("ลับ" in h for h in headers)
    assert footers and all("ลับ" in f for f in footers)


def test_docx_sets_thai_language_and_alignment_option(tmp_path):
    doc = PRESET_TEMPLATES["speaker_request"].schema
    xml = _docx_xml(tmp_path, doc)
    assert 'w:bidi="th-TH"' in xml["word/styles.xml"]
    assert 'w:val="thaiDistribute"' in xml["word/document.xml"]

    left = _docx_xml(tmp_path, doc, ExportOptions(body_alignment="left"))
    assert 'w:val="thaiDistribute"' not in left["word/document.xml"]


def test_docx_memo_title_follows_profile(tmp_path):
    doc = PRESET_TEMPLATES["procurement_approval"].schema
    bma = _docx_xml(tmp_path, doc)["word/document.xml"]
    assert '<w:sz w:val="64"/>' in bma and 'w:line="700"' in bma and 'w:lineRule="exact"' in bma
    manual = _docx_xml(tmp_path, doc, ExportOptions(layout_profile="manual_memo"))["word/document.xml"]
    assert '<w:sz w:val="58"/>' in manual

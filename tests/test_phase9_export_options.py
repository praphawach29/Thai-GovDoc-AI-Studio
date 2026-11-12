"""
test_phase9_export_options.py — ทดสอบตัวเลือกการส่งออก Word (Sprint 1)

ครอบคลุม:
- ฝังฟอนต์ TrueType (odttf) + fontTable + settings
- ระยะห่างตัวอักษร (character spacing) ระดับ style
- ขอบกระดาษบันทึกข้อความ 1.5 ซม. และเลขหน้าไทย
- ตัวเลือกซ่อนตราครุฑ / เส้นคั่น
"""

import zipfile
from pathlib import Path

import pytest
from docx import Document

from core.models import ExportOptions
from core.templates_library import PRESET_TEMPLATES
from core.word_exporter import export_govdoc_to_docx


@pytest.fixture
def memo_doc():
    doc = PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)
    doc.use_thai_numerals = True
    return doc


def _export(doc, tmp_path, **kwargs):
    out = tmp_path / "out.docx"
    export_govdoc_to_docx(doc, str(out), options=ExportOptions(**kwargs))
    return out


def test_docx_embeds_psk_fonts_and_spacing(memo_doc, tmp_path):
    out = _export(memo_doc, tmp_path)

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        font_table = z.read("word/fontTable.xml").decode("utf-8")
        settings = z.read("word/settings.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8")
        document = z.read("word/document.xml").decode("utf-8")
        content_types = z.read("[Content_Types].xml").decode("utf-8")

        assert "word/fonts/font1.odttf" in names
        assert "word/fonts/font2.odttf" in names
        assert "embedRegular" in font_table and "embedBold" in font_table
        assert "TH SarabunPSK" in font_table
        assert "embedTrueTypeFonts" in settings
        assert 'Extension="odttf"' in content_types
        # 0.4 pt = 8 twips ใน style Normal
        assert '<w:spacing w:val="8"/>' in styles
        # ขอบบน 1.5 ซม. = 850 twips + เลขหน้าไทย
        assert 'w:top="850"' in document
        assert 'w:pgNumType w:fmt="thaiNumbers"' in document

    # ต้องเปิดกลับด้วย python-docx ได้
    assert len(Document(str(out)).paragraphs) > 5


def test_odttf_is_obfuscated_but_same_length(tmp_path, memo_doc):
    out = _export(memo_doc, tmp_path)
    regular = Path("assets/fonts/THSarabunPSK.ttf").read_bytes()
    with zipfile.ZipFile(out) as z:
        embedded = z.read("word/fonts/font1.odttf")

    assert len(embedded) == len(regular)
    assert embedded[:32] != regular[:32]
    assert embedded[32:] == regular[32:]


def test_letter_spacing_can_be_customised(memo_doc, tmp_path):
    out = _export(memo_doc, tmp_path, letter_spacing_pt=0.2)
    with zipfile.ZipFile(out) as z:
        styles = z.read("word/styles.xml").decode("utf-8")
    assert '<w:spacing w:val="4"/>' in styles


def test_letterhead_can_be_hidden(memo_doc, tmp_path):
    out = _export(memo_doc, tmp_path, letterhead="none")
    with zipfile.ZipFile(out) as z:
        document = z.read("word/document.xml").decode("utf-8")
        assert "<w:drawing" not in document
        assert not [n for n in z.namelist() if n.startswith("word/media/")]


def test_divider_line_adds_border(memo_doc, tmp_path):
    out = _export(memo_doc, tmp_path, divider="line")
    with zipfile.ZipFile(out) as z:
        document = z.read("word/document.xml").decode("utf-8")
    assert "<w:pBdr>" in document


def test_sarabun_new_option_without_font_files_skips_embedding(memo_doc, tmp_path):
    out = _export(memo_doc, tmp_path, export_font="sarabun_new", embed_fonts=True)
    with zipfile.ZipFile(out) as z:
        document = z.read("word/document.xml").decode("utf-8")
        assert not [n for n in z.namelist() if n.startswith("word/fonts/")]
    assert 'w:ascii="TH Sarabun New"' in document


def test_embedding_can_be_disabled(memo_doc, tmp_path):
    out = _export(memo_doc, tmp_path, embed_fonts=False)
    with zipfile.ZipFile(out) as z:
        assert not [n for n in z.namelist() if n.startswith("word/fonts/")]

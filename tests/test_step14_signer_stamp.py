"""
Step 14: ผู้ลงนามใช้ตราประทับชื่อ-ตำแหน่ง — เว้นบรรทัดชื่อ/ตำแหน่งว่าง (ระยะเท่าเดิม) ทั้ง Word และ PDF
และไม่นับเป็นจุดที่ต้องระบุ
"""

from docx import Document

from core.issuing_units import apply_issuing_unit
from core.linter import lint_gov_document
from core.models import GovDocumentSchema, IssuingUnit, Signer
from core.templates_library import PRESET_TEMPLATES
from core.typst_exporter import generate_typst_content
from core.word_exporter import export_govdoc_to_docx

NAME, POS = "([✏️ ระบุชื่อผู้ลงนาม])", "เจ้าหน้าที่กลุ่มงานส่งเสริมกีฬา"
CO_NAME, CO_POS = "(นายหัวหน้า ทดสอบ)", "หัวหน้ากลุ่มงานส่งเสริมกีฬา"


def _memo(stamp_main=False, stamp_co=False) -> GovDocumentSchema:
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.signatory_name, doc.signatory_position = NAME, POS
    doc.co_signers = [Signer(name=CO_NAME, position=CO_POS, stamp=stamp_co)]
    doc.signatory_stamp = stamp_main
    return doc


def _docx_text(doc, tmp_path):
    out = tmp_path / "x.docx"
    export_govdoc_to_docx(doc, str(out))
    return [p.text.replace("​", "") for p in Document(str(out)).paragraphs]


def test_default_off_and_old_documents_still_load():
    data = _memo().model_dump(mode="json")
    data.pop("signatory_stamp")
    for co in data["co_signers"]:
        co.pop("stamp")
    doc = GovDocumentSchema.model_validate(data)
    assert doc.signatory_stamp is False and doc.co_signers[0].stamp is False


def test_stamped_signer_is_not_a_placeholder():
    assert any("ชื่อผู้ลงนาม" in p for p in _memo().find_placeholders())
    assert not any("ชื่อผู้ลงนาม" in p for p in _memo(stamp_main=True).find_placeholders())
    # ผู้ลงนามถัดไปที่ยังเป็นช่องว่างนับด้วย (เดิมไม่นับ) — ใช้ตราประทับแล้วไม่นับ
    doc = _memo(stamp_main=True)
    doc.co_signers[0].name = NAME
    assert any("ชื่อผู้ลงนาม (2)" in p for p in doc.find_placeholders())
    doc.co_signers[0].stamp = True
    assert doc.find_placeholders() == [p for p in doc.find_placeholders() if "ผู้ลงนาม" not in p]


def test_lint_does_not_require_name_when_stamped():
    doc = _memo()
    doc.signatory_name = ""
    assert any(i.rule_id == "RULE_MISSING_SIGNATORY_NAME" for i in lint_gov_document(doc).issues)
    doc.signatory_stamp = True
    assert not any(i.rule_id == "RULE_MISSING_SIGNATORY_NAME" for i in lint_gov_document(doc).issues)


def test_word_keeps_lines_but_blank(tmp_path):
    typed = _docx_text(_memo(), tmp_path)
    stamped = _docx_text(_memo(stamp_main=True, stamp_co=True), tmp_path)
    assert NAME in typed and CO_POS in typed
    assert NAME not in stamped and POS not in stamped and CO_NAME not in stamped and CO_POS not in stamped
    assert len(stamped) == len(typed)                         # จำนวนบรรทัดเท่าเดิม (ระยะประทับเท่ากับพิมพ์)
    assert stamped.count(" ") == 4


def test_word_only_one_signer_stamped(tmp_path):
    text = _docx_text(_memo(stamp_main=False, stamp_co=True), tmp_path)
    assert NAME in text and POS in text and CO_NAME not in text


def test_external_letter_word(tmp_path):
    doc = _memo(stamp_main=True)
    doc.doc_type = doc.doc_type.__class__("external")
    doc.co_signers = None
    text = _docx_text(doc, tmp_path)
    assert NAME not in text and POS not in text


def test_typst_blank_lines():
    content = generate_typst_content(_memo(stamp_main=True, stamp_co=True))
    assert NAME not in content and CO_NAME not in content and CO_POS not in content
    assert 'signatory_name: " "' in content


def test_changing_unit_keeps_stamp_choice():
    doc = _memo(stamp_main=False, stamp_co=True)
    unit = IssuingUnit(key="u", label="หน่วย", dept_name="ส่วนราชการ", doc_number_format="{gap}/{year}",
                       signers=[Signer(name="", position="ผู้เสนอ", is_author=True), Signer(name="", position="หัวหน้า")])
    out = apply_issuing_unit(doc, unit)
    assert out.signatory_stamp is False and out.co_signers[0].stamp is True

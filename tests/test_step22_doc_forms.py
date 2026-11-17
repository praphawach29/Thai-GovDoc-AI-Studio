"""
Step 22: หนังสือราชการชนิดอื่นตามระเบียบงานสารบรรณ (แบบที่ ๓ ขึ้นไป)

หนังสือประทับตรา (แบบที่ ๓): ที่ · ถึง · ข้อความ · ส่วนราชการที่ส่ง · ที่ว่างประทับตรา · วันที่ · ส่วนราชการเจ้าของเรื่อง
— schema/ประเภท, เลือกประเภทจากคำสั่ง, prompt + few-shot, ร่างผ่าน API, linter, Word และ PDF (ตำแหน่งจริง)
"""

import io
import zipfile

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from core.doc_forms import body_lines, line_level
from core.linter import lint_gov_document
from core.llm_drafter import DraftContent, build_user_prompt, draft_content_with_llm, LLMConfig
from core.models import FORM_KEYS, DocType, DocumentKind, UserProfileSchema, parse_form_key
from core.studio import choose_output_form, create_blank_document, requested_form, start_draft
from core.word_exporter import export_govdoc_to_docx
from server.main import app

client = TestClient(app)
CM = 72 / 2.54
LEFT = 3 * CM


def _stamp(**changes):
    doc = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(), kind=DocumentKind.STAMP_LETTER)
    values = dict(
        doc_number="กท 1205/123", salutation="ถึง  สำนักงานเขตปทุมวัน", subject="ขอเอกสารเพิ่มเติม",
        paragraph_reason="ตามที่ สำนักงานเขตปทุมวัน ได้มีหนังสือขอรับการสนับสนุนอุปกรณ์กีฬา นั้น",
        paragraph_details="ในการนี้ ขอให้จัดส่งเอกสาร ดังนี้\n1. รายละเอียดโครงการ\n1.1 แผนการจัดงาน",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดดำเนินการต่อไป",
        dept_name="กองการกีฬา", doc_date="17 พฤศจิกายน 2569",
        contact_dept="กลุ่มงานส่งเสริมกีฬา", contact_tel="0 2215 0000", use_thai_numerals=False,
    )
    values.update(changes)
    for k, v in values.items():
        setattr(doc, k, v)
    return doc


# ---------------------------------------------------------------- ประเภท
def test_form_keys_keep_db_doc_type_binary():
    # documents.doc_type ในฐานข้อมูลรับเฉพาะ external/internal — ชนิดอื่นแยกด้วย kind
    assert all(dt in (DocType.EXTERNAL, DocType.INTERNAL) for dt, _ in FORM_KEYS.values())
    assert parse_form_key("stamp_letter") == (DocType.EXTERNAL, DocumentKind.STAMP_LETTER)
    assert parse_form_key("") is None
    with pytest.raises(ValueError):
        parse_form_key("letter_x")


def test_blank_stamp_letter_shape():
    doc = _stamp()
    assert doc.form_key == "stamp_letter" and doc.is_stamp_letter
    blank = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(), kind=DocumentKind.STAMP_LETTER)
    assert blank.salutation.startswith("ถึง")
    assert blank.closing == "" and blank.references is None and blank.attachments is None
    assert "\n" not in blank.dept_name           # ส่วนราชการที่ส่ง = ชื่ออย่างเดียว ไม่มีที่อยู่
    # ไม่มีผู้ลงนาม/คำลงท้าย → ไม่นับเป็นจุดต้องระบุ
    assert not any(p.startswith(("ชื่อผู้ลงนาม", "ตำแหน่งผู้ลงนาม", "คำลงท้าย")) for p in blank.find_placeholders())


@pytest.mark.parametrize("prompt, expected", [
    ("ร่างหนังสือประทับตราขอเอกสารเพิ่มเติมจากสำนักงานเขต", "stamp_letter"),
    ("ช่วยร่างบันทึกข้อความขออนุมัติจัดงาน", "internal"),
    ("ร่างหนังสือตอบสมาคมกีฬา", "external"),
    ("ขอใช้สถานที่จัดงาน", None),
])
def test_requested_form_from_prompt(prompt, expected):
    assert requested_form(prompt) == expected


def test_choose_output_form_priority():
    assert choose_output_form("external", "ร่างหนังสือประทับตรา", has_source_file=True,
                              classified=DocType.INTERNAL)[0] == "external"
    assert choose_output_form(None, "ร่างหนังสือประทับตรา", has_source_file=True,
                              classified=DocType.INTERNAL)[0] == "stamp_letter"
    assert choose_output_form(None, "ขอใช้สถานที่", has_source_file=True,
                              classified=DocType.EXTERNAL)[0] == "internal"


def test_stamp_sender_is_department_name_only():
    from core.doc_forms import sender_name
    assert sender_name("สำนักวัฒนธรรมฯ (กองการกีฬา โทร. ๐ ๒๒๔๖ ๘๐๗๙)") == "สำนักวัฒนธรรมฯ"
    assert sender_name("กรมพลศึกษา\nถนนพระราม ๑") == "กรมพลศึกษา"
    profile = UserProfileSchema(dept_name="สำนักทดสอบ", department_full="สำนักทดสอบ (กองทดสอบ โทร. ๑๒๓๔)")
    doc = create_blank_document(DocType.EXTERNAL, profile=profile, kind=DocumentKind.STAMP_LETTER)
    assert doc.dept_name == "สำนักทดสอบ"


def test_body_line_levels():
    assert line_level("ข้อ ๑ ระเบียบนี้เรียกว่า") == 1       # ต่างจากบันทึกข้อความ
    assert line_level("๑.๑ รายละเอียด") == 2
    assert line_level("1.1.1 ย่อย") == 3
    assert line_level("\t\tเยื้องเอง") == 2
    assert body_lines("ก\n\nข", "1.1 ค") == [(2.5, "ก"), (2.5, "ข"), (3.5, "1.1 ค")]


# ---------------------------------------------------------------- AI prompt
def test_stamp_prompt_uses_form_and_few_shot():
    prompt = build_user_prompt(doc_type=DocType.EXTERNAL, kind=DocumentKind.STAMP_LETTER,
                               instruction="ขอเอกสารเพิ่ม", source_text="", recipient="สำนักงานเขตปทุมวัน")
    assert "หนังสือประทับตรา" in prompt and "แบบที่ ๓" in prompt
    assert "<form_example>" in prompt
    assert prompt.index("<form_example>") < prompt.index("<instruction>")     # ตัวอย่างอยู่ก่อนเรื่องใหม่
    assert "ไม่มีคำขึ้นต้น คำลงท้าย และผู้ลงนาม" in prompt


def test_draft_passes_kind_to_prompt():
    seen = {}

    def fake(prompt, config, timeout):
        seen["prompt"] = prompt
        return DraftContent(subject="ขอเอกสาร", memo_intro="", memo_facts="", memo_consideration="",
                            paragraph_reason="ตามที่ ... นั้น", paragraph_details="", paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
                            reference="", source_summary="")

    res = draft_content_with_llm(doc_type=DocType.EXTERNAL, kind=DocumentKind.STAMP_LETTER, instruction="x",
                                 source_text="", config=LLMConfig(gemini_api_key="k"),
                                 providers=[("gemini", "m", fake)])
    assert res.content is not None and "หนังสือประทับตรา" in seen["prompt"]


def test_start_draft_stamp_rule_based():
    res = start_draft(prompt="ร่างหนังสือประทับตรา ถึง สำนักงานเขตปทุมวัน ขอเอกสารโครงการเพิ่มเติม",
                      profile=UserProfileSchema())
    doc = res.document
    assert doc.kind == DocumentKind.STAMP_LETTER and doc.doc_type == DocType.EXTERNAL
    assert doc.salutation.startswith("ถึง")
    assert any("หนังสือประทับตรา" in s.detail for s in res.steps if s.key == "classify")


# ---------------------------------------------------------------- API
def test_api_blank_and_draft_stamp_letter():
    doc = client.post("/api/v1/studio/blank", json={"doc_type": "stamp_letter"}).json()
    assert doc["kind"] == "stamp_letter" and doc["doc_type"] == "external"
    assert client.post("/api/v1/studio/blank", json={"doc_type": "nope"}).status_code == 400

    res = client.post("/api/v1/studio/draft", data={"prompt": "แจ้งผลการดำเนินงานให้สำนักงานเขตทราบ",
                                                    "doc_type": "stamp_letter"})
    assert res.status_code == 200, res.text
    assert res.json()["document"]["kind"] == "stamp_letter"
    assert client.post("/api/v1/studio/draft", data={"prompt": "x", "doc_type": "nope"}).status_code == 400


# ---------------------------------------------------------------- linter
def test_lint_stamp_letter():
    rules = {i.rule_id for i in lint_gov_document(_stamp()).issues}
    assert "RULE_MISSING_SIGNATORY_NAME" not in rules     # ประทับตราแทนการลงชื่อ
    assert "RULE_PURPOSE_CONVENTION" not in rules
    assert "RULE_STAMP_RECIPIENT" not in rules
    rules = {i.rule_id for i in lint_gov_document(_stamp(salutation="เรียน  นายกรัฐมนตรี")).issues}
    assert {"RULE_STAMP_RECIPIENT", "RULE_STAMP_NOT_FOR_HIGH_OFFICIAL"} <= rules


# ---------------------------------------------------------------- Word
def test_stamp_docx(tmp_path):
    out = tmp_path / "stamp.docx"
    export_govdoc_to_docx(_stamp(), str(out))
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8").replace("​", "")
    assert "ถึง" in xml and "สำนักงานเขตปทุมวัน" in xml and "กองการกีฬา" in xml
    assert "ขอแสดงความนับถือ" not in xml
    assert "ขอเอกสารเพิ่มเติม" not in xml            # เรื่องไม่พิมพ์บนหนังสือประทับตรา
    assert 'w:val="thaiDistribute"' in xml
    from docx import Document
    d = Document(str(out))
    sec = d.sections[0]
    assert [round(x.cm, 2) for x in (sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin)] == [2.5, 2.0, 3.0, 2.0]
    pic = d.inline_shapes[0]
    assert abs(pic.height.cm - 3.0) < 0.01
    assert not any(p.text.startswith(("เรียน", "กราบเรียน")) for p in d.paragraphs)
    sender = next(p for p in d.paragraphs if p.text.replace("​", "") == "กองการกีฬา")
    assert abs(sender.paragraph_format.left_indent.cm - 8.0) < 0.01
    sub = next(p for p in d.paragraphs if p.text.replace("​", "").startswith("1.1"))
    assert abs(sub.paragraph_format.first_line_indent.cm - 3.5) < 0.01
    fonts = {r.font.name for p in d.paragraphs for r in p.runs if r.text.strip()}
    assert fonts == {"TH SarabunIT๙"}


# ---------------------------------------------------------------- PDF
@pytest.mark.requires_typst
def test_stamp_pdf_layout():
    # ข้อความไทยใน PDF ถอดกลับเป็น cid — ใช้คำภาษาอังกฤษ/ตัวเลขเป็นหมุดวัดตำแหน่ง
    doc = _stamp(dept_name="SENDER", paragraph_reason="REASON ตามที่ ... นั้น",
                 subject="SUBJECTX", paragraph_purpose="PURPOSE จึงเรียนมาเพื่อโปรดทราบ")
    res = client.post("/api/v1/export/pdf", json=doc.model_dump(mode="json"))
    assert res.status_code == 200, res.text
    page = pdfplumber.open(io.BytesIO(res.content)).pages[0]
    assert "SUBJECTX" not in page.extract_text()                                   # เรื่องไม่พิมพ์บนหนังสือ
    words = page.extract_words()
    garuda = page.images[0]
    assert abs((garuda["bottom"] - garuda["top"]) / CM - 3.0) < 0.05             # ครุฑ 3 ซม.
    assert abs((garuda["x0"] + garuda["x1"]) / 2 - (LEFT + 8 * CM)) < 0.1 * CM    # กึ่งกลางพื้นที่พิมพ์
    assert abs(garuda["top"] / CM - 2.5) < 0.05                                    # ขอบบน 2.5 ซม.
    number = next(w for w in words if "1205/123" in w["text"])
    assert abs(number["bottom"] / CM - 5.5) < 0.15                                 # "ที่" แนวเท้าครุฑ
    first = next(w for w in words if w["text"].startswith("REASON"))
    assert abs((first["x0"] - LEFT) / CM - 2.5) < 0.1                              # ย่อหน้า 2.5 ซม.
    sender = next(w for w in words if w["text"] == "SENDER")
    date = next(w for w in words if w["text"] == "17")
    assert abs((sender["x0"] - LEFT) / CM - 8.0) < 0.1 and abs((date["x0"] - LEFT) / CM - 8.0) < 0.1
    assert (date["top"] - sender["bottom"]) / CM > 2.0                             # ที่ว่างประทับตรา
    assert min(w["x0"] for w in words) / CM > 2.95                                 # ขอบซ้าย
    assert max(w["x1"] for w in words) / CM < 21.0 - 1.95                          # ขอบขวา


# ================================================================ คำสั่ง (แบบที่ ๔)
def _formal(kind=DocumentKind.ORDER, **changes):
    doc = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(dept_name="กองการกีฬา"), kind=kind)
    values = dict(
        doc_number="12/2569", subject="SUBJECTX แต่งตั้งคณะกรรมการ", special_title="TITLEX คำสั่งกองการกีฬา",
        paragraph_reason="REASON ด้วยกองการกีฬา กำหนดจัดการแข่งขัน จึงแต่งตั้งคณะกรรมการ ประกอบด้วย",
        paragraph_details="1. ผู้อำนวยการกอง ประธานกรรมการ\n1.1 DETAIL อำนาจหน้าที่",
        paragraph_purpose="ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป", doc_date="17 พฤศจิกายน พ.ศ. 2569",
        signatory_name="SIGNER", signatory_position="ผู้อำนวยการกองการกีฬา", use_thai_numerals=False,
    )
    values.update(changes)
    for k, v in values.items():
        setattr(doc, k, v)
    return doc


def test_blank_order_shape():
    doc = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(dept_name="กองการกีฬา"),
                                kind=DocumentKind.ORDER)
    assert doc.form_key == "order" and doc.is_formal
    assert doc.special_title == "คำสั่งกองการกีฬา"
    assert "พ.ศ." in doc.doc_date
    assert doc.salutation == "" and doc.closing == "" and doc.references is None
    labels = {p.split(":")[0] for p in doc.find_placeholders()}
    assert not labels & {"คำขึ้นต้น", "คำลงท้าย", "ส่วนราชการ"}
    assert doc.paragraph_purpose.startswith("ทั้งนี้")


def test_with_buddhist_era():
    from core.doc_forms import with_buddhist_era
    assert with_buddhist_era("๑๗ พฤศจิกายน ๒๕๖๙") == "๑๗ พฤศจิกายน พ.ศ. ๒๕๖๙"
    assert with_buddhist_era("17 พฤศจิกายน พ.ศ. 2569") == "17 พฤศจิกายน พ.ศ. 2569"
    assert with_buddhist_era("[✏️ ระบุวันที่]") == "[✏️ ระบุวันที่]"


@pytest.mark.parametrize("prompt, expected", [
    ("ช่วยร่างคำสั่งแต่งตั้งคณะกรรมการจัดการแข่งขันกีฬา", "order"),
    ("ออกคำสั่งมอบหมายให้เจ้าหน้าที่ปฏิบัติงานวันหยุด", "order"),
    ("ตามคำสั่งกรุงเทพมหานคร ที่ ๑๒/๒๕๖๙ ขอเชิญประชุม", None),
])
def test_requested_order(prompt, expected):
    assert requested_form(prompt) == expected


def test_order_prompt_form_and_few_shot():
    prompt = build_user_prompt(doc_type=DocType.EXTERNAL, kind=DocumentKind.ORDER,
                               instruction="แต่งตั้งคณะกรรมการ", source_text="")
    assert "คำสั่ง (แบบที่ ๔" in prompt and "อาศัยอำนาจตาม" in prompt
    assert "ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป" in prompt and "<form_example>" in prompt
    assert "ห้ามใช้ \"จึงเรียนมาเพื่อ\"" in prompt


def test_api_order_blank_and_draft():
    doc = client.post("/api/v1/studio/blank", json={"doc_type": "order"}).json()
    assert doc["kind"] == "order" and doc["special_title"].startswith("คำสั่ง")
    res = client.post("/api/v1/studio/draft", data={"prompt": "ร่างคำสั่งแต่งตั้งคณะกรรมการจัดงานกีฬาเยาวชน"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["document"]["kind"] == "order"
    assert any("คำสั่ง" in s["detail"] for s in body["steps"] if s["key"] == "classify")


def test_lint_order():
    rules = {i.rule_id for i in lint_gov_document(_formal(special_title="คำสั่งกองการกีฬา")).issues}
    assert not rules & {"RULE_REASON_CONVENTION", "RULE_PURPOSE_CONVENTION", "RULE_FORMAL_TITLE"}
    rules = {i.rule_id for i in lint_gov_document(
        _formal(paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ", special_title="กองการกีฬา")).issues}
    assert {"RULE_FORMAL_NO_LETTER_CLOSING", "RULE_FORMAL_TITLE"} <= rules


def test_order_docx(tmp_path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    out = tmp_path / "order.docx"
    export_govdoc_to_docx(_formal(), str(out))
    d = Document(str(out))
    text = {p.text.replace("​", ""): p for p in d.paragraphs}
    sec = d.sections[0]
    assert [round(x.cm, 2) for x in (sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin)] == [2.5, 2.0, 3.0, 2.0]
    assert abs(d.inline_shapes[0].height.cm - 3.0) < 0.01
    title = text["TITLEX คำสั่งกองการกีฬา"]
    assert title.alignment == WD_ALIGN_PARAGRAPH.CENTER and title.runs[0].bold
    assert text["ที่  12/2569"].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert text["เรื่อง  SUBJECTX แต่งตั้งคณะกรรมการ"].alignment == WD_ALIGN_PARAGRAPH.CENTER
    date = text["สั่ง ณ วันที่  17 พฤศจิกายน พ.ศ. 2569"]
    assert abs(date.paragraph_format.left_indent.cm - 5.0) < 0.01
    signer = text["SIGNER"]
    assert signer.alignment == WD_ALIGN_PARAGRAPH.CENTER and abs(signer.paragraph_format.left_indent.cm - 6.0) < 0.01
    assert abs(text["1.1 DETAIL อำนาจหน้าที่"].paragraph_format.first_line_indent.cm - 3.5) < 0.01
    assert not any(t.startswith(("เรียน", "ขอแสดงความนับถือ")) for t in text)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "<w:pBdr>" in xml                                   # เส้นคั่นใต้เรื่อง


@pytest.mark.requires_typst
def test_order_pdf_layout():
    res = client.post("/api/v1/export/pdf", json=_formal().model_dump(mode="json"))
    assert res.status_code == 200, res.text
    page = pdfplumber.open(io.BytesIO(res.content)).pages[0]
    words = page.extract_words()
    centre = LEFT + 8 * CM
    garuda = page.images[0]
    assert abs((garuda["bottom"] - garuda["top"]) / CM - 3.0) < 0.05
    assert abs((garuda["x0"] + garuda["x1"]) / 2 - centre) < 0.1 * CM
    assert abs(garuda["top"] / CM - 2.5) < 0.05

    def line_of(marker):
        w = next((w for w in words if w["text"] == marker), None) or next(w for w in words if marker in w["text"])
        row = [x for x in words if abs(x["bottom"] - w["bottom"]) < 2]
        return w, min(x["x0"] for x in row), max(x["x1"] for x in row)

    for marker in ("TITLEX", "12/2569", "SUBJECTX"):         # หัวกลาง
        _, x0, x1 = line_of(marker)
        assert abs((x0 + x1) / 2 - centre) < 0.3 * CM, marker
    title, _, _ = line_of("TITLEX")
    assert title["top"] > garuda["bottom"]
    assert line_of("12/2569")[0]["top"] > title["bottom"] and line_of("SUBJECTX")[0]["top"] > line_of("12/2569")[0]["bottom"]
    reason, _, _ = line_of("REASON")
    assert abs((reason["x0"] - LEFT) / CM - 2.5) < 0.1
    _, detail_x0, _ = line_of("DETAIL")
    assert abs((detail_x0 - LEFT) / CM - 3.5) < 0.1             # "1.1 DETAIL" — เลขข้อเริ่ม 3.5 ซม.
    rule = [l for l in page.lines + page.rects if abs((l["x1"] - l["x0"]) / CM - 4.0) < 0.1]
    assert rule and abs((rule[0]["x0"] + rule[0]["x1"]) / 2 - centre) < 0.1 * CM   # เส้นคั่น 4 ซม. กึ่งกลาง
    date, date_x0, _ = line_of("17")                             # บรรทัด "สั่ง ณ วันที่ 17 ..."
    assert abs((date_x0 - LEFT) / CM - 5.0) < 0.1               # เริ่ม 5 ซม.
    signer, sx0, sx1 = line_of("SIGNER")
    assert abs((sx0 + sx1) / 2 - (LEFT + 11 * CM)) < 0.2 * CM     # กึ่งกลางช่วง 6–16 ซม.
    assert (signer["top"] - date["bottom"]) / CM > 1.5           # ที่ว่างลงลายมือชื่อ
    assert min(w["x0"] for w in words) / CM > 2.95 and max(w["x1"] for w in words) / CM < 19.05


# ================================================================ ประกาศ (แบบที่ ๗)
def test_blank_announcement_shape():
    doc = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(dept_name="กองการกีฬา"),
                                kind=DocumentKind.ANNOUNCEMENT)
    assert doc.form_key == "announcement" and doc.special_title == "ประกาศกองการกีฬา"
    assert doc.paragraph_purpose == "จึงประกาศให้ทราบโดยทั่วกัน"
    labels = {p.split(":")[0] for p in doc.find_placeholders()}
    assert "เลขที่หนังสือ" not in labels                      # ประกาศไม่มีบรรทัด "ที่"
    rules = {i.rule_id for i in lint_gov_document(doc).issues}
    assert not rules & {"RULE_DOC_NUMBER_PLACEHOLDER", "RULE_DOC_NUMBER_MISSING", "RULE_PURPOSE_CONVENTION"}


@pytest.mark.parametrize("prompt, expected", [
    ("ร่างประกาศรับสมัครนักกีฬาเยาวชน", "announcement"),
    ("ช่วยทำประกาศรายชื่อผู้มีสิทธิ์เข้าแข่งขัน", "announcement"),
    ("ร่างคำสั่งแต่งตั้งคณะกรรมการ", "order"),
])
def test_requested_announcement(prompt, expected):
    assert requested_form(prompt) == expected


def test_announcement_prompt():
    prompt = build_user_prompt(doc_type=DocType.EXTERNAL, kind=DocumentKind.ANNOUNCEMENT,
                               instruction="รับสมัครนักกีฬา", source_text="")
    assert "ประกาศ (แบบที่ ๗" in prompt and "จึงประกาศให้ทราบโดยทั่วกัน" in prompt and "<form_example>" in prompt


def test_api_announcement():
    assert client.post("/api/v1/studio/blank", json={"doc_type": "announcement"}).json()["kind"] == "announcement"
    res = client.post("/api/v1/studio/draft", data={"prompt": "ร่างประกาศรับสมัครนักกีฬาเยาวชน ปิดรับ ๓๐ พ.ย."})
    assert res.status_code == 200 and res.json()["document"]["kind"] == "announcement"


def test_announcement_docx(tmp_path):
    from docx import Document

    out = tmp_path / "ann.docx"
    export_govdoc_to_docx(_formal(DocumentKind.ANNOUNCEMENT, special_title="ประกาศกองการกีฬา"), str(out))
    texts = [p.text.replace("​", "") for p in Document(str(out)).paragraphs]
    assert "ประกาศกองการกีฬา" in texts
    assert not any(t.startswith("ที่") for t in texts)          # ไม่มีบรรทัดเลขที่
    assert "ประกาศ ณ วันที่  17 พฤศจิกายน พ.ศ. 2569" in texts


@pytest.mark.requires_typst
def test_announcement_pdf():
    res = client.post("/api/v1/export/pdf", json=_formal(DocumentKind.ANNOUNCEMENT).model_dump(mode="json"))
    assert res.status_code == 200, res.text
    page = pdfplumber.open(io.BytesIO(res.content)).pages[0]
    words = page.extract_words()
    assert not any("12/2569" in w["text"] for w in words)       # ไม่มีบรรทัด "ที่"
    title = next(w for w in words if w["text"] == "TITLEX")
    subject = next(w for w in words if w["text"] == "SUBJECTX")
    assert 0.5 < (subject["bottom"] - title["bottom"]) / CM < 1.0   # เรื่องอยู่บรรทัดถัดจากชื่อเอกสาร
    date = next(w for w in words if w["text"] == "17")
    row = [w for w in words if abs(w["bottom"] - date["bottom"]) < 2]
    assert abs((min(w["x0"] for w in row) - LEFT) / CM - 5.0) < 0.1

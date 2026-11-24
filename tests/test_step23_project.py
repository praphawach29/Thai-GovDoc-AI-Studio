"""
Step 23: แบบเสนอโครงการของกรุงเทพมหานคร (รูปแบบการเขียนโครงการ / คู่มือการเขียนโครงการ กทม.)

ชื่อโครงการ · หน่วยงาน · ปีงบประมาณ · หัวข้อ ๑–๑๐ · ตารางแผนปฏิบัติการ/งบประมาณ/ความเสี่ยง/ตัวชี้วัด · ลงชื่อ
— ประเภท, เลือกอัตโนมัติจากต้นเรื่อง, AI ตอบเป็นตาราง, ยอดรวม/ตัวอักษร, ระดับความเสี่ยง, linter, Word, PDF
"""

import io

import pdfplumber
import pytest
from docx import Document
from fastapi.testclient import TestClient

from core.linter import lint_gov_document
from core.llm_drafter import LLMConfig, _strict_schema, draft_content_with_llm, apply_draft_content
from core.models import DocType, DocumentKind, UserProfileSchema, parse_form_key
from core.project import (BudgetRow, baht_text, budget_mismatches, budget_total, format_amount, line_level,
                          parse_amount, project_view, risk_level)
from core.project_ai import (BudgetRowContent, KpiRowContent, PlanStepContent, ProjectContent, RiskRowContent,
                             clean_project)
from core.studio import choose_output_form, create_blank_document, looks_like_project, requested_form
from core.word_exporter import export_govdoc_to_docx
from server.main import app
from tests.project_fixture import sample_project_doc

client = TestClient(app)
CFG = LLMConfig(anthropic_api_key="x", gemini_api_key="y")


# ---------------------------------------------------------------- ตัวเลข / ข้อความจำนวนเงิน
@pytest.mark.parametrize("amount, text", [
    (2174720, "สองล้านหนึ่งแสนเจ็ดหมื่นสี่พันเจ็ดร้อยยี่สิบบาทถ้วน"),   # ยอดจริงของโครงการกีฬาขั้นพื้นฐาน
    (21, "ยี่สิบเอ็ดบาทถ้วน"),
    (11, "สิบเอ็ดบาทถ้วน"),
    (1, "หนึ่งบาทถ้วน"),
    (101, "หนึ่งร้อยเอ็ดบาทถ้วน"),
    (1000001, "หนึ่งล้านเอ็ดบาทถ้วน"),
    (12500000, "สิบสองล้านห้าแสนบาทถ้วน"),
    (0.5, "ห้าสิบสตางค์"),
    (1234.25, "หนึ่งพันสองร้อยสามสิบสี่บาทยี่สิบห้าสตางค์"),
])
def test_baht_text(amount, text):
    assert baht_text(amount) == text


def test_amount_parse_and_format():
    assert parse_amount("1,087,200.-") == 1087200
    assert parse_amount("๒,๑๗๔,๗๒๐") == 2174720
    assert parse_amount("") is None and parse_amount(None) is None
    assert format_amount(96000) == "96,000" and format_amount(1234.5) == "1,234.50" and format_amount(None) == ""


def test_risk_level_matches_bma_matrix():
    # ตารางวิเคราะห์ระดับความเสี่ยง (คู่มือหน้า ๑๔): โอกาส × ผลกระทบ
    assert risk_level(1, 2) == "น้อย"
    assert risk_level(1, 5) == "ปานกลาง" and risk_level(3, 2) == "ปานกลาง"
    assert risk_level(2, 4) == "สูง" and risk_level(3, 3) == "สูง"          # ตัวอย่างในคู่มือ
    assert risk_level(3, 4) == "สูงมาก"                                       # โครงการกีฬาขั้นพื้นฐาน
    assert risk_level(0, 4) == "" and risk_level(6, 1) == ""


def test_budget_total_sums_only_leaf_rows():
    rows = [BudgetRow(item="1. หมวดค่าตอบแทน", amount=300),
            BudgetRow(item="1.1 ฟุตบอล", amount=300),
            BudgetRow(item="1.1.1 ผู้ตัดสิน", amount=100), BudgetRow(item="1.1.2 ผู้ช่วย", amount=200),
            BudgetRow(item="2. หมวดค่าอาหาร"),
            BudgetRow(item="2.1 ค่าอาหาร", amount=50)]
    assert budget_total(rows) == 350                          # ยอดหมวดไม่นับซ้ำ
    assert budget_mismatches(rows) == []
    rows[1].amount = 999
    assert budget_mismatches(rows) == [(0, 300, 999), (1, 999, 300)]
    assert budget_total([BudgetRow(item="- ค่าวัสดุ", amount=10), BudgetRow(item="- ค่าเช่า", amount=5)]) == 15


def test_line_level_subitems_start_at_body_indent():
    # "๒.๑ เพื่อ..." ของวัตถุประสงค์อยู่ระดับเดียวกับย่อหน้า (2.5 ซม.) — ต่างจากหนังสือ
    assert line_level("2.1 เพื่อ") == 1 and line_level("๑๐.๑ ตัวชี้วัด") == 1
    assert line_level("2.1.1 ย่อย") == 2 and line_level("\t\tแท็บ") == 2


# ---------------------------------------------------------------- ประเภท / เลือกอัตโนมัติ
def test_project_form_key_and_blank_document():
    assert parse_form_key("project") == (DocType.EXTERNAL, DocumentKind.PROJECT)
    doc = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(), kind=DocumentKind.PROJECT)
    assert doc.is_project and doc.form_key == "project"
    assert doc.project.agency == "กองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    assert doc.subject.startswith("โครงการ")
    labels = {p.split(":")[0] for p in doc.find_placeholders()}
    assert {"ชื่อโครงการ", "หลักการและเหตุผล", "ปีงบประมาณ"} <= labels
    assert "เลขที่หนังสือ" not in labels and "คำขึ้นต้น" not in labels


def test_project_requested_by_prompt_or_detected_from_source():
    assert requested_form("ช่วยเขียนโครงการส่งเสริมกีฬา ปีงบประมาณ 2571") == "project"
    assert requested_form("ตามโครงการที่ได้รับอนุมัติแล้ว ช่วยร่างหนังสือภายนอก") == "external"
    source = ("ชื่อโครงการ ค่าใช้จ่ายในการส่งเสริมกีฬาขั้นพื้นฐาน\n๑. หลักการและเหตุผล\n...\n๒. วัตถุประสงค์\n"
              "๓. เป้าหมาย\n๖. แผนปฏิบัติการ\n๙. ประโยชน์ที่คาดว่าจะได้รับ\n๑๐. การติดตามและประเมินผล")
    assert looks_like_project(source)
    form, why = choose_output_form(None, "", has_source_file=True, classified=DocType.EXTERNAL, source_text=source)
    assert form == "project" and "โครงการ" in why
    # หนังสือขอความอนุเคราะห์ทั่วไป ยังเป็นบันทึกข้อความเหมือนเดิม
    letter = "ด้วยสมาคมกีฬา... มีความประสงค์ขอใช้สนาม จึงเรียนมาเพื่อโปรดพิจารณา"
    assert not looks_like_project(letter)
    assert choose_output_form(None, "", has_source_file=True, classified=DocType.EXTERNAL,
                              source_text=letter)[0] == "internal"


# ---------------------------------------------------------------- AI
def _content(**over):
    data = dict(
        subject="โครงการทดสอบ", agency="กองการกีฬา", fiscal_year="2571", rationale="ย่อหน้า ๑\nย่อหน้า ๒",
        objectives="2.1 เพื่อ ก", targets="ผู้เข้าร่วม 100 คน", project_type="ภารกิจประจำ", alignment="1. แผน ก",
        project_format="จัดงาน", schedule="พ.ย. 70 – พ.ค. 71",
        plan=[PlanStepContent(step="1. ขออนุมัติ", months=[0, 1, 15])],
        budget_title="",
        budget=[BudgetRowContent(activity="กิจกรรม ก", item="1. ค่าตอบแทน", amount="1,200", law="บัญชี 3"),
                BudgetRowContent(activity="", item="รวมเป็นเงินทั้งสิ้น", amount="1200", law="")],
        budget_note="โดยเบิกจ่ายจาก...",
        risks=[RiskRowContent(risk="1. ฝนตก", likelihood=3, impact=9, mitigation="สถานที่ในร่ม")],
        benefits="9.1 ก", kpis=[KpiRowContent(indicator="1. จำนวนผู้เข้าร่วม", target="ร้อยละ 80", kind="ผลผลิต",
                                             method="ใบสมัคร", period="พ.ค. 71")],
        monitoring="รายเดือน", assessment="แบบสอบถาม", source_summary="",
    )
    data.update(over)
    return ProjectContent(**data)


def test_strict_schema_closes_nested_tables():
    schema = _strict_schema(ProjectContent)
    assert schema["additionalProperties"] is False
    budget = schema["$defs"]["BudgetRowContent"]
    assert budget["additionalProperties"] is False and set(budget["required"]) == {"activity", "item", "amount", "law"}


def test_project_draft_uses_project_schema_and_prompt():
    seen = {}

    def provider(prompt, config, timeout):
        seen["prompt"] = prompt
        return _content()

    res = draft_content_with_llm(doc_type=DocType.EXTERNAL, kind=DocumentKind.PROJECT, instruction="ทำเป็นปีงบประมาณ 2571",
                                 source_text="ชื่อโครงการ ...", config=CFG, providers=[("gemini", "m", provider)],
                                 title="กองการกีฬา สำนักวัฒนธรรมฯ")
    assert isinstance(res.content, ProjectContent)
    assert "แบบเสนอโครงการของกรุงเทพมหานคร" in seen["prompt"] and "กองการกีฬา สำนักวัฒนธรรมฯ" in seen["prompt"]
    assert [r.item for r in res.content.budget] == ["1. ค่าตอบแทน"]             # แถว "รวม" ที่ AI เขียนเองถูกตัด

    blank = create_blank_document(DocType.EXTERNAL, profile=UserProfileSchema(), kind=DocumentKind.PROJECT)
    doc = apply_draft_content(blank, res.content)
    p = doc.project
    assert doc.subject == "โครงการทดสอบ"
    assert p.plan[0].months == [0, 1]                       # เดือนนอกช่วง 0–11 ถูกตัด
    assert p.budget[0].amount == 1200
    assert p.risks[0].likelihood == 3 and p.risks[0].impact == 0      # คะแนนนอก 1–5 = ยังไม่ประเมิน


def test_clean_project_strips_markdown_everywhere():
    c = clean_project(_content(rationale="**ตัวหนา**  \n", budget=[
        BudgetRowContent(activity="", item="**1. รายการ**", amount="10", law="")]))
    assert c.rationale == "ตัวหนา" and c.budget[0].item == "1. รายการ"


# ---------------------------------------------------------------- ตรวจ / มุมมองพิมพ์
def test_project_lint_rules():
    doc = sample_project_doc()
    assert lint_gov_document(doc).issues == []
    doc.project.budget[1].amount = 1                        # ยอดกีฬาฟุตบอลไม่ตรงกับรายการย่อย
    doc.project.objectives = "2.1 ก\n2.2 ข\n2.3 ค\n2.4 ง"
    doc.project.kpis = doc.project.kpis[:1]
    doc.subject = "ส่งเสริมกีฬา"
    rules = {i.rule_id: i for i in lint_gov_document(doc).issues}
    assert {"RULE_PROJECT_BUDGET_SUM", "RULE_PROJECT_OBJECTIVES", "RULE_PROJECT_KPI_KINDS", "RULE_PROJECT_NAME"} <= set(rules)
    assert rules["RULE_PROJECT_BUDGET_SUM"].field.startswith("pj:budget.")


def test_project_view_totals_and_thai_numerals():
    doc = sample_project_doc(thai=True)
    view = project_view(doc.subject, doc.project, True)
    budget = next(b for b in view["blocks"] if b["type"] == "budget")
    assert budget["total"] == "๙๐๒,๖๐๐"
    assert budget["total_label"] == "รวมเป็นเงินทั้งสิ้น (เก้าแสนสองพันหกร้อยบาทถ้วน)"
    assert budget["rows"][0]["span"] == len(budget["rows"])       # กิจกรรมเดียวรวมเซลล์ทั้งคอลัมน์
    risks = next(b for b in view["blocks"] if b["type"] == "risks")
    assert [r["level"] for r in risks["rows"]] == ["สูงมาก", "สูง"]
    plan = next(b for b in view["blocks"] if b["type"] == "plan")
    assert plan["year"] == "๒๕๗๑" and plan["rows"][0]["months"][:3] == [True, True, False]


# ---------------------------------------------------------------- Word / PDF
def test_project_docx(tmp_path):
    out = tmp_path / "project.docx"
    export_govdoc_to_docx(sample_project_doc(), str(out))
    d = Document(str(out))
    text = "\n".join(p.text for p in d.paragraphs).replace("​", "")
    assert "ชื่อโครงการ" in text and "1. หลักการและเหตุผล" in text and "10.3 การประเมินผลโครงการ" in text
    assert "ผู้เสนอโครงการ" in text and "ผู้อนุมัติโครงการ" in text
    assert len(d.tables) == 4                                          # แผน งบประมาณ ความเสี่ยง ตัวชี้วัด
    budget = d.tables[1]
    last = [c.text.replace("​", "") for c in budget.rows[-1].cells]
    assert last[0].startswith("รวมเป็นเงินทั้งสิ้น (เก้าแสนสองพันหกร้อยบาทถ้วน)") and last[2] == "902,600"
    plan = d.tables[0]
    shaded = [c._tc.tcPr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd") is not None for c in plan.rows[2].cells[1:]]
    assert shaded[:3] == [True, True, False]                           # ต.ค. พ.ย. แรเงา
    sec = d.sections[0]
    assert round(sec.left_margin.cm, 1) == 3.0 and round(sec.right_margin.cm, 1) == 2.0


@pytest.mark.requires_typst
def test_project_pdf_via_api():
    doc = sample_project_doc()
    doc.subject = "PROJECTX"
    res = client.post("/api/v1/export/pdf", json=doc.model_dump(mode="json"))
    assert res.status_code == 200, res.text
    pdf = pdfplumber.open(io.BytesIO(res.content))
    words = pdf.pages[0].extract_words()
    name = next(w for w in words if w["text"] == "PROJECTX")
    assert abs(name["x0"] / (72 / 2.54) - (3.0 + 2.7)) < 0.15          # ชื่อโครงการเริ่มที่ 2.7 ซม. จากขอบซ้าย
    assert any("902,600" in (p.extract_text() or "") for p in pdf.pages)


def test_blank_project_via_api_and_check():
    res = client.post("/api/v1/studio/blank", json={"doc_type": "project"})
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["kind"] == "project" and doc["project"]["plan"]
    res = client.post("/api/v1/studio/check", json=doc)
    assert res.status_code == 200
    assert any("ชื่อโครงการ" in p for p in res.json()["placeholders"])


# ---------------------------------------------------------------- อ่านตารางจาก Word (ต้นเรื่องที่เป็นโครงการ)
def test_docx_tables_keep_order_rows_and_repeated_amounts(tmp_path):
    from core.extractor import extract_text_from_docx

    d = Document()
    d.add_paragraph("๗. งบประมาณ")
    t = d.add_table(rows=2, cols=3)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(0, 2).text = "กิจกรรม", "รายการ", "งบประมาณ"
    # รายการ/จำนวนเงินพิมพ์เป็นย่อหน้าซ้อนในเซลล์เดียว เว้นย่อหน้าว่างให้ตรงกัน + ขึ้นบรรทัดในย่อหน้า (Shift+Enter)
    items, amounts = t.cell(1, 1), t.cell(1, 2)
    items.text = "1.1 ผู้ตัดสิน"
    items.add_paragraph("1.2 ผู้ช่วย คู่ละ 2 คน ๆ ละ\n500 บาท")
    items.add_paragraph("1.3 เจ้าหน้าที่")
    amounts.text = "12,000.-"
    amounts.add_paragraph("96,000.-")
    amounts.add_paragraph("")
    amounts.add_paragraph("12,000.-")
    d.add_paragraph("โดยเบิกจ่ายจากงบประมาณ")
    path = tmp_path / "p.docx"
    d.save(str(path))
    text = extract_text_from_docx(str(path))
    assert text.index("๗. งบประมาณ") < text.index("[ตาราง]") < text.index("โดยเบิกจ่าย")     # ลำดับตามเอกสาร
    lines = text.split("[ตาราง]\n")[1].split("\n[/ตาราง]")[0].split("\n")
    assert lines[0] == "กิจกรรม | รายการ | งบประมาณ"
    assert " | 1.1 ผู้ตัดสิน | 12,000.-" in lines
    assert " | 1.2 ผู้ช่วย คู่ละ 2 คน ๆ ละ | 96,000.-" in lines
    assert " | 1.3 เจ้าหน้าที่ | 12,000.-" in lines                     # ค่าที่ซ้ำไม่หาย

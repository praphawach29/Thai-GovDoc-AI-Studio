"""
test_phase3.py — ชุดทดสอบการทำงานของระบบ Phase 3: Human-in-the-loop Review, Diff & Audit Trail
"""

import pytest
from pathlib import Path

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel
from core.copilot import (
    make_formal_tone,
    make_concise,
    insert_legal_reference,
    convert_doc_type,
    toggle_doc_numerals
)
from core.audit import (
    compute_text_diff,
    compute_doc_diff,
    AuditManager
)


@pytest.fixture
def sample_doc():
    return GovDocumentSchema(
        doc_type=DocType.EXTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="ดพร ๐๑๐๒/ว ๑๒๓",
        dept_name="สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน)",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="การขอความอนุเคราะห์วิทยากร",
        salutation="เรียน  อธิบดีกรมสรรพากร",
        paragraph_reason="ตามที่ ได้มีหนังสือแจ้งความประสงค์ขอความอนุเคราะห์วิทยากร นั้น",
        paragraph_details="สำนักงานยินดีให้ความอนุเคราะห์ในการจัดฝึกอบรม",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ",
        closing="ขอแสดงความนับถือ",
        signatory_name="(นายสมชาย ดิจิทัล)",
        signatory_position="ผู้อำนวยการฝ่ายพัฒนาเทคโนโลยี",
        contact_dept="ฝ่ายพัฒนาเทคโนโลยี",
        contact_tel="0 2612 6000"
    )


# -------------------------------------------------------------
# 1. ทดสอบ Diff Engine (การเปรียบเทียบความแตกต่าง)
# -------------------------------------------------------------
def test_text_diff_identical():
    text = "ข้อความเหมือนกันทุกประการ"
    blocks = compute_text_diff(text, text)
    assert len(blocks) == 1
    assert blocks[0].op == "equal"
    assert blocks[0].original_text == text


def test_text_diff_modified():
    orig = "สำนักงาน มีงาน เยอะมาก ช่วยดำเนินการด้วย"
    mod = "สำนักงาน มีงาน จำนวนมาก โปรดให้ความอนุเคราะห์ดำเนินการด้วย"
    blocks = compute_text_diff(orig, mod)
    
    # ต้องพบ op ที่ไม่ใช่ equal (replace, delete, insert)
    ops = [b.op for b in blocks]
    assert "replace" in ops or "insert" in ops or "delete" in ops


def test_doc_diff(sample_doc):
    mod_doc = sample_doc.model_copy(deep=True)
    mod_doc.subject = "การขอความอนุเคราะห์วิทยากรบรรยายพิเศษเพิ่มเติม"
    mod_doc.paragraph_details = "สำนักงานมีความยินดีอย่างยิ่งในการสนับสนุนวิทยากร"

    diffs = compute_doc_diff(sample_doc, mod_doc)
    diff_map = {d.field_name: d for d in diffs}

    assert diff_map["subject"].has_changes is True
    assert diff_map["paragraph_details"].has_changes is True
    assert diff_map["paragraph_reason"].has_changes is False
    assert diff_map["closing"].has_changes is False


# -------------------------------------------------------------
# 2. ทดสอบ Audit Manager (Version History & Audit Log)
# -------------------------------------------------------------
def test_audit_manager_workflow(sample_doc, tmp_path):
    test_db = str(tmp_path / "test_audit.db")
    mgr = AuditManager(db_path=test_db)

    # 1. บันทึกเวอร์ชัน 1
    v1 = mgr.save_version("DOC-001", sample_doc, author="AI Studio", note="ร่างเริ่มต้น")
    assert v1 == 1

    # 2. บันทึกเวอร์ชัน 2
    mod_doc = sample_doc.model_copy(deep=True)
    mod_doc.paragraph_details = "ปรับแก้เนื้อหาให้รัดกุมขึ้น"
    v2 = mgr.save_version("DOC-001", mod_doc, author="หัวหน้างาน", note="ตรวจแก้ครั้งที่ 1")
    assert v2 == 2

    # 3. เรียกดูเวอร์ชัน
    versions = mgr.list_versions("DOC-001")
    assert len(versions) == 2
    assert versions[0].version_num == 1
    assert versions[1].version_num == 2
    assert "ปรับแก้เนื้อหา" in versions[1].doc_data.paragraph_details

    # 4. ทดสอบบันทึกและดึง Audit Log
    mgr.log_action("DOC-001", "export_docx", "ผู้ใช้งาน", {"format": "docx"})
    logs = mgr.list_logs("DOC-001")
    assert len(logs) >= 3  # 2 save_version + 1 export_docx
    assert logs[0].action == "export_docx"


# -------------------------------------------------------------
# 3. ทดสอบ Copilot Assistants
# -------------------------------------------------------------
def test_copilot_make_formal():
    informal = "มีงาน เยอะ มาก ขอให้ ช่วย จัดส่งของ เร็วๆ นี้"
    formal = make_formal_tone(informal)
    assert "จำนวนมาก" in formal
    assert "ขอความอนุเคราะห์ให้" in formal
    assert "โปรดให้ความอนุเคราะห์" in formal
    assert "ในโอกาสแรก" in formal


def test_copilot_make_concise():
    long_text = "ในการจัดประชุมสัมมนาเชิงปฏิบัติการครั้งนี้นั้น ทางหน่วยงานมีความประสงค์ที่จะขอความร่วมมือและขอให้ทุกท่านเข้าร่วมการประชุมตามกำหนดการที่ได้แจ้งไว้แล้ว"
    short_text = make_concise(long_text)
    assert len(short_text) < len(long_text)


def test_copilot_insert_legal_reference(sample_doc):
    doc_with_law = insert_legal_reference(sample_doc, "saraban")
    assert "ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ" in doc_with_law.paragraph_details


def test_copilot_convert_doc_type(sample_doc):
    # จากภายนอก -> ภายใน
    internal = convert_doc_type(sample_doc, DocType.INTERNAL)
    assert internal.doc_type == DocType.INTERNAL
    assert internal.closing == ""  # หนังสือภายในต้องไม่มีคำลงท้าย

    # จากภายใน -> ภายนอก
    external = convert_doc_type(internal, DocType.EXTERNAL)
    assert external.doc_type == DocType.EXTERNAL
    assert external.closing == "ขอแสดงความนับถือ"


def test_copilot_toggle_numerals(sample_doc):
    sample_doc.doc_number = "กค 1234/2569"
    sample_doc.doc_date = "15 มีนาคม 2569"
    
    # แปลงเป็นเลขไทย
    thai_doc = toggle_doc_numerals(sample_doc, use_thai=True)
    assert "๑๒๓๔/๒๕๖๙" in thai_doc.doc_number
    assert "๑๕ มีนาคม ๒๕๖๙" in thai_doc.doc_date

    # แปลงกลับเป็นเลขอารบิก
    arab_doc = toggle_doc_numerals(thai_doc, use_thai=False)
    assert "1234/2569" in arab_doc.doc_number
    assert "15 มีนาคม 2569" in arab_doc.doc_date

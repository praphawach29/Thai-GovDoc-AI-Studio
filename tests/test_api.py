"""
test_api.py — ชุดทดสอบ REST API ของ Thai GovDoc AI Studio โดยตรง (Direct Function Testing)
เพื่อความรวดเร็วและปลอดภัยภายใต้ Environment ที่จำกัด Socket
"""

import pytest
from core.api import (
    health_check,
    draft_document,
    copilot_refine,
    validate_document,
    export_typst,
    get_next_number,
    reserve_number,
    list_outgoing,
    create_outgoing,
    DraftRequest,
    RefineRequest,
    ReserveRequest
)
from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext
from core.registry import OutgoingRecord
from core.ai_drafter import DraftingIntent


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
        subject="การให้ความอนุเคราะห์วิทยากร",
        salutation="เรียน  อธิบดีกรมสรรพากร",
        paragraph_reason="ตามที่ กรมสรรพากร ได้มีหนังสือแจ้งความประสงค์ขอความอนุเคราะห์วิทยากร นั้น",
        paragraph_details="สำนักงานพัฒนารัฐบาลดิจิทัล มีความยินดีและไม่ขัดข้องในการให้ความอนุเคราะห์",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ และดำเนินการต่อไป",
        closing="ขอแสดงความนับถือ",
        signatory_name="(นายสมชาย ดิจิทัล)",
        signatory_position="ผู้อำนวยการฝ่ายพัฒนาเทคโนโลยี",
        contact_dept="ฝ่ายพัฒนาเทคโนโลยี",
        contact_tel="0 2612 6000"
    )


# ---------------------------------------------------------------------
# 1. ทดสอบ Health Endpoint
# ---------------------------------------------------------------------
def test_api_health():
    res = health_check()
    assert res["status"] == "healthy"
    assert "ระเบียบสำนักนายกรัฐมนตรี" in res["standards"]


# ---------------------------------------------------------------------
# 2. ทดสอบ AI Drafting Endpoint
# ---------------------------------------------------------------------
def test_api_draft_document():
    ctx = SourceDocumentContext(
        source_filename="test.txt",
        source_dept="มหาวิทยาลัยเชียงใหม่",
        source_doc_no="อว ๑๒๓/๒๕๖๙",
        source_date="๑๐ มีนาคม ๒๕๖๙",
        source_subject="ขอความอนุเคราะห์วิทยากร",
        raw_text="เนื้อความต้นเรื่อง...",
        summary="ขอวิทยากร",
        core_issues=[],
        is_scanned=False,
        page_count=1
    )
    req = DraftRequest(
        context=ctx,
        doc_type=DocType.EXTERNAL,
        intent=DraftingIntent.ACCEPT,
        use_llm=False
    )
    draft = draft_document(req)
    assert draft.doc_type == DocType.EXTERNAL
    assert "ยินดีและไม่ขัดข้อง" in draft.paragraph_details
    assert draft.paragraph_purpose.startswith("จึงเรียนมาเพื่อโปรดทราบ")


def test_api_copilot_refine():
    req = RefineRequest(text="มีงานเยอะมาก ช่วยดำเนินการด้วย", command="formal")
    res = copilot_refine(req)
    assert "จำนวนมาก" in res["refined"]
    assert "โปรดให้ความอนุเคราะห์" in res["refined"]


# ---------------------------------------------------------------------
# 3. ทดสอบ Validation (Linter) Endpoint
# ---------------------------------------------------------------------
def test_api_validate_document(sample_doc):
    res = validate_document(sample_doc)
    assert res.is_valid is True
    assert len(res.issues) == 0

    # ทดสอบกรณีผิดระเบียบ (ใส่วันที่นำหน้า)
    invalid_doc = sample_doc.model_copy(deep=True)
    invalid_doc.doc_date = "วันที่ ๑๕ มีนาคม ๒๕๖๙"
    res_err = validate_document(invalid_doc)
    assert res_err.is_valid is False
    assert any(i.rule_id == "RULE_NO_PREFIX_DATE" for i in res_err.issues)


# ---------------------------------------------------------------------
# 4. ทดสอบ Export Typst Endpoint
# ---------------------------------------------------------------------
def test_api_export_typst(sample_doc):
    typ_code = export_typst(sample_doc)
    assert "#govdoc_external" in typ_code
    assert sample_doc.subject in typ_code


# ---------------------------------------------------------------------
# 5. ทดสอบ Registry Endpoints
# ---------------------------------------------------------------------
def test_api_registry_workflow():
    # 1. ขอเลขถัดไป
    res_num = get_next_number(prefix="กค ๐๔๐๖/", is_circular=False)
    assert "กค ๐๔๐๖/" in res_num["doc_number"]

    # 2. จองเลข
    req_reserve = ReserveRequest(
        prefix="กค ๐๔๐๖/",
        subject="จองเลขโครงการ API",
        reserved_by="นายสมชาย"
    )
    res_reserve = reserve_number(req_reserve)
    assert res_reserve["status"] == "success"
    assert "reserved_number" in res_reserve

    # 3. บันทึกและดึงรายการส่ง
    record = OutgoingRecord(
        doc_number="กค ๐๔๐๖/ว ๗๗๗",
        doc_type="external",
        subject="ทดสอบ API Outgoing",
        recipient="กรมบัญชีกลาง",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        status="sent"
    )
    res_out = create_outgoing(record)
    assert res_out["status"] == "registered"

    res_list = list_outgoing(limit=10)
    assert len(res_list) > 0

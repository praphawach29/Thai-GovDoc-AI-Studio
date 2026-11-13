"""
test_step0_grounding.py — Step 0: Rule-based drafter ต้องไม่แต่งข้อเท็จจริง/ข้อกฎหมายเอง
"""

import pytest

from core.ai_drafter import draft_from_context_rule_based, DraftingIntent
from core.models import DocType, SourceDocumentContext


def _ctx() -> SourceDocumentContext:
    return SourceDocumentContext(
        source_filename="request.txt",
        source_dept="สมาคมกีฬาแห่งประเทศไทย",
        source_doc_no="สกท ๑๒/๒๕๖๙",
        source_date="๑ มีนาคม ๒๕๖๙",
        source_subject="ขอความอนุเคราะห์ใช้สถานที่จัดกิจกรรม",
        summary="ขอใช้สถานที่จัดกิจกรรม",
        raw_text="สมาคมมีความประสงค์ขอใช้สถานที่จัดกิจกรรม",
    )


@pytest.mark.parametrize(
    "intent",
    [DraftingIntent.ACCEPT, DraftingIntent.DECLINE, DraftingIntent.FORWARD,
     DraftingIntent.MEMO_REVIEW, DraftingIntent.PROPOSAL],
)
def test_rule_based_draft_has_no_invented_facts(intent):
    draft = draft_from_context_rule_based(_ctx(), doc_type=DocType.INTERNAL, intent=intent)

    body = " ".join(filter(None, [
        draft.paragraph_reason or "",
        draft.paragraph_details or "",
        draft.paragraph_purpose or "",
        draft.memo_intro or "",
        draft.memo_facts or "",
        draft.memo_consideration or "",
        draft.memo_request or "",
    ]))

    # ข้อเท็จจริงเฉพาะที่เคยถูก hardcode ต้องไม่ปรากฏ
    for forbidden in [
        "ฝ่ายพัฒนาศักยภาพภาครัฐ",
        "ภารกิจสำคัญตามแผนงานเร่งด่วน",
        "งบประมาณดำเนินการตามแผนงานที่ได้รับอนุมัติ",
        "ได้มอบหมายให้เจ้าหน้าที่ผู้รับผิดชอบประสานงาน",
    ]:
        assert forbidden not in body, f"{forbidden} ปรากฏในร่าง intent={intent}"

    # เลขที่หนังสือต้องเป็นช่องว่าง ไม่ใช่เลขสมมติ
    assert draft.doc_number.startswith("......../")

    # สิ่งที่ส่งมาด้วยต้องไม่ถูกสร้างขึ้นเอง
    assert draft.attachments is None


def test_rule_based_never_invents_law_from_keyword():
    ctx = _ctx()
    ctx.source_subject = "ขอใช้สถานที่และขออนุญาตใช้ตราสัญลักษณ์"
    ctx.raw_text = "ขอใช้สถานที่และขออนุญาตใช้ตราสัญลักษณ์จัดกิจกรรม"
    draft = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL, intent=DraftingIntent.MEMO_REVIEW)
    assert draft.memo_law is None

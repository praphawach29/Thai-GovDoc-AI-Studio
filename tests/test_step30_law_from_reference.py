"""ข้อกฎหมายคัดได้จากต้นแบบที่แนบ (หนังสือฉบับจริง) แต่ห้ามแต่ง — ตรวจทีละบรรทัดกับต้นเรื่อง/ต้นแบบ"""
from core.law_grounding import ground_law
from core.llm_drafter import DraftContent, LLMConfig, apply_draft_content, build_user_prompt, draft_content_with_llm
from core.models import DocType
from core.templates_library import PRESET_TEMPLATES


def _memo():
    return PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)

REFERENCE = """ข้อกฎหมาย
๑. พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒ (เอกสาร ๑)
 มาตรา 6 ห้ามมิให้บุคคลใดใช้เครื่องหมายราชการเว้นแต่หน่วยราชการที่กำหนด
เครื่องหมายนั้นจะได้อนุญาต
๕. ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุงและค่าใช้จ่ายของศูนย์บริการและกิจกรรม
ส่งเสริมการกีฬา การดนตรี สำนักวัฒนธรรม กีฬา และการท่องเที่ยว พ.ศ. 2563 (เอกสาร ๕)
ข้อ 21 ในกรณีที่มีเหตุพิเศษสมควรปฏิบัติเป็นอย่างอื่น หรือที่มิได้กำหนดไว้ในระเบียบนี้
ให้เสนอผู้ว่าราชการกรุงเทพมหานครพิจารณาสั่งการเป็นกรณีๆ ไป"""

AI_LAW = """๑. พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒ (เอกสาร ๑)
มาตรา ๖ ห้ามมิให้บุคคลใดใช้เครื่องหมายราชการเว้นแต่หน่วยราชการที่กำหนดเครื่องหมายนั้นจะได้อนุญาต
มาตรา ๙ ข้อความที่ AI แต่งขึ้นเอง ไม่มีในต้นแบบ
๒. พระราชบัญญัติที่ไม่มีอยู่จริง พ.ศ. ๒๕๙๙
มาตรา ๑ ข้อความแต่ง
๓. ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุงและค่าใช้จ่ายของศูนย์บริการและกิจกรรมส่งเสริมการกีฬา การดนตรี สำนักวัฒนธรรม กีฬา และการท่องเที่ยว พ.ศ. ๒๕๖๓ (เอกสาร ๒)
ข้อ ๒๑ ในกรณีที่มีเหตุพิเศษสมควรปฏิบัติเป็นอย่างอื่น หรือที่มิได้กำหนดไว้ในระเบียบนี้ ให้เสนอผู้ว่าราชการกรุงเทพมหานครพิจารณาสั่งการเป็นกรณี ๆ ไป"""


def test_ground_law_keeps_reference_lines_drops_invented_and_renumbers():
    law, dropped = ground_law(AI_LAW, REFERENCE)
    assert "เครื่องหมายราชการ" in law and "มาตรา ๖" in law
    assert "ข้อ ๒๑" in law
    assert "ไม่มีอยู่จริง" not in law and "AI แต่ง" not in law
    assert dropped == 3
    heads = [ln for ln in law.splitlines() if ln[:2] in ("๑.", "๒.", "๓.")]
    assert [h[:2] for h in heads] == ["๑.", "๒."]


def test_ground_law_empty_when_no_source_has_law():
    assert ground_law(AI_LAW, "สมาคมขอใช้สนาม ไม่มีข้อกฎหมาย") == ("", 7)
    assert ground_law("", REFERENCE) == ("", 0)


def _content(law: str) -> DraftContent:
    return DraftContent(analysis="คำขอ ๑ ใช้ตรา → พ.ร.บ.เครื่องหมายราชการ", subject="ขอเชิญเป็นเจ้าภาพร่วม",
                        memo_intro="๑. สมาคม ได้มีหนังสือ", memo_law=law, memo_facts="๑. ขอใช้ตรา",
                        memo_consideration="พิจารณาแล้ว เห็นควร", paragraph_reason="", paragraph_details="",
                        paragraph_purpose="", reference="", source_summary="")


def test_draft_grounds_law_against_source_and_reference():
    res = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="สมาคมขอใช้ตราสัญลักษณ์",
                                 config=LLMConfig(gemini_api_key="k", mask_pii=False),
                                 providers=[("gemini", "m", lambda p, c, t: _content(AI_LAW))],
                                 law_sources="สมาคมขอใช้ตราสัญลักษณ์\n" + REFERENCE)
    assert res.content is not None and res.law_dropped == 3
    doc = apply_draft_content(_memo(), res.content)
    assert doc.memo_law and "มาตรา ๖" in doc.memo_law and "ไม่มีอยู่จริง" not in doc.memo_law


def test_draft_without_reference_drops_all_law():
    res = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="สมาคมขอใช้ตราสัญลักษณ์",
                                 config=LLMConfig(gemini_api_key="k", mask_pii=False),
                                 providers=[("gemini", "m", lambda p, c, t: _content(AI_LAW))])
    doc = apply_draft_content(_memo(), res.content)
    assert doc.memo_law is None


def test_memo_prompt_asks_for_law_and_analysis():
    prompt = build_user_prompt(doc_type=DocType.INTERNAL, instruction="", source_text="x")
    assert "memo_law" in prompt

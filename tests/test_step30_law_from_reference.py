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


# ---- ภาคความประสงค์ขั้นสูงสุด (เสนอปลัดฯ) อ้างอำนาจตามต้นแบบ ----
from core.issuing_units import apply_issuing_unit  # noqa: E402
from core.law_grounding import ground_citations  # noqa: E402
from core.models import default_issuing_units  # noqa: E402

TOP_REF = """จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร
เพื่อโปรดพิจารณาให้ความเห็นชอบตามข้อ 1.๑ อนุญาตตามข้อ ๑.2 และอนุมัติตามข้อ ๑.๓ อำนาจ
ในการเห็นชอบ อนุญาตและอนุมัติเป็นของผู้ว่าราชการกรุงเทพมหานคร ตามพระราชบัญญัติระเบียบบริหาร
ราชการกรุงเทพมหานคร พ.ศ. 2528 มาตรา 49 (2) ประกอบกับ พระราชบัญญัติเครื่องหมายราชการ
พุทธศักราช ๒๔๘๒ มาตรา ๖ และปลัดกรุงเทพมหานครได้โปรดสั่งการตามข้อ ๒"""

TOP = ("จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร เพื่อโปรดพิจารณาให้ความเห็นชอบตามข้อ ๑.๑ "
       "อนุญาตตามข้อ ๑.๒ อำนาจในการเห็นชอบ อนุญาตและอนุมัติเป็นของผู้ว่าราชการกรุงเทพมหานคร ตามพระราชบัญญัติระเบียบบริหาร"
       "ราชการกรุงเทพมหานคร พ.ศ. ๒๕๒๘ มาตรา ๔๙ (๒) ประกอบกับ พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒ มาตรา ๖ "
       "และปลัดกรุงเทพมหานครได้โปรดสั่งการตามข้อ ๒")


def test_ground_citations_keeps_authority_copied_from_reference():
    assert ground_citations(TOP, TOP_REF) == (TOP, True)


def test_ground_citations_cuts_invented_authority():
    bad = TOP.replace("มาตรา ๔๙ (๒)", "มาตรา ๕๐ (๗)")
    text, ok = ground_citations(bad, TOP_REF)
    assert not ok and "อำนาจ" not in text and text.endswith("อนุญาตตามข้อ ๑.๒")
    assert ground_citations("ตามระเบียบกรุงเทพมหานคร ว่าด้วยสิ่งที่ไม่มี ข้อ ๙", TOP_REF) == ("", False)


def test_top_request_used_only_at_last_unit():
    units = default_issuing_units()
    doc = _memo()
    doc.memo_request_top = TOP
    first = apply_issuing_unit(doc, units[0], units=units, replace_request=True)
    assert first.memo_request == units[0].request_text
    top = apply_issuing_unit(first, units[-1], units=units)
    assert top.memo_request == TOP
    back = apply_issuing_unit(top, units[1], units=units)          # ย้อนลงมาขั้นกลาง = ข้อความมาตรฐาน
    assert back.memo_request == units[1].request_text
    doc.memo_request_top = None
    assert apply_issuing_unit(doc, units[-1], units=units, replace_request=True).memo_request == units[-1].request_text


def test_closing_written_by_ai_in_consideration_is_not_printed_twice():
    content = _content("")
    content = content.model_copy(update={"memo_consideration": "พิจารณาแล้ว เห็นควร\n๑. เห็นชอบ\nจึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ"})
    doc = _memo()
    doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ"
    out = apply_draft_content(doc, content)
    assert "จึงเรียนมาเพื่อ" not in out.memo_consideration and out.memo_consideration.endswith("๑. เห็นชอบ")
    assert out.paragraph_purpose.count("จึงเรียนมาเพื่อ") == 1

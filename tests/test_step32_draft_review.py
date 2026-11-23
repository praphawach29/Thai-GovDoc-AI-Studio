"""ตรวจร่างที่ AI ตอบ แล้วให้ AI แก้หนึ่งรอบ (core/draft_review + llm_drafter.draft_content_with_llm)"""
from core.draft_review import fact_refs, remaining_ok, review_memo
from core.llm_drafter import DraftContent, LLMConfig, draft_content_with_llm
from core.models import DocType

SOURCE = """สมาคมวิ่งเปี้ยวประเทศไทย ที่ สวปท.๑๔/๒๕๖๙ วันที่ ๒๓ กันยายน ๒๕๖๙
ขอใช้อาคารกีฬาเวสน์ ๑ วันที่ ๓๐ มกราคม ๒๕๗๐ เวลา ๑๐.๐๐ - ๑๗.๐๐ น. และวันที่ ๓๑ มกราคม ๒๕๗๐
๑. อาคาร ๒. ค่าเช่าสถานที่ ๓. ระบบไฟ ๔. โลโก้"""

FACTS = "สมาคมขอความอนุเคราะห์ ดังนี้\n๑. ขอใช้อาคาร\n๒. ของดค่าเช่า\n๓. ระบบไฟ\n๔. ขอใช้โลโก้"


def _content(**kw) -> DraftContent:
    base = dict(analysis="", subject="ขอเชิญเป็นเจ้าภาพร่วม",
                memo_intro="๑. สมาคมวิ่งเปี้ยวประเทศไทย ได้มีหนังสือ ที่ สวปท.๑๔/๒๕๖๙ ลงวันที่ ๒๓ กันยายน ๒๕๖๙",
                memo_law="", memo_facts=FACTS,
                memo_consideration="พิจารณาแล้ว\n๑.๓ อนุมัติยกเว้นค่าธรรมเนียมตามข้อเท็จจริง ๑ และ ๒\n๒. มอบหมายตามข้อเท็จจริง ๓ - ๔",
                memo_request_top="", paragraph_reason="", paragraph_details="", paragraph_purpose="",
                reference="", source_summary="")
    base.update(kw)
    return DraftContent(**base)


def test_fact_refs_expand_lists_and_ranges():
    assert fact_refs("ตามข้อเท็จจริง ๒, ๔ และ ๖ - ๙ ตามความเหมาะสม") == [6, 7, 8, 9, 2, 4]
    assert fact_refs("ตามข้อเท็จจริง 3") == [3]


def test_clean_draft_has_no_issues():
    assert review_memo(_content(), SOURCE, recipient="หัวหน้ากลุ่มงานส่งเสริมกีฬา") == []


def test_reference_to_missing_fact_item():
    issues = review_memo(_content(memo_consideration="๒. มอบหมายตามข้อเท็จจริง ๓ - ๕"), SOURCE)
    assert len(issues) == 1 and "ข้อเท็จจริง 5" in issues[0] and "4 ข้อ" in issues[0]


def test_intro_tracing_past_recipient_to_staff():
    intro = "๑. ... รักษาการผู้อำนวยการกองการกีฬา มอบหัวหน้ากลุ่มงานส่งเสริมกีฬา และหัวหน้ากลุ่มงานส่งเสริมกีฬา มอบ ประชาภัทร์ ดำเนินการ"
    issues = review_memo(_content(memo_intro=intro), SOURCE, recipient="หัวหน้ากลุ่มงานส่งเสริมกีฬา")
    assert len(issues) == 1 and "ชื่อเจ้าหน้าที่" in issues[0]


def test_date_not_in_source():
    issues = review_memo(_content(memo_facts=FACTS + "\nจัดวันที่ ๑๖ - ๑๗ มกราคม ๒๕๗๐"), SOURCE)
    assert any("ไม่พบในต้นเรื่อง" in x and "๑๖" in x for x in issues)


def test_remaining_time_rule():
    assert remaining_ok(40, 15) and not remaining_ok(15, 5) and not remaining_ok(30, 25)


def _run(first: DraftContent, second: DraftContent, budget=75.0):
    prompts = []

    def fake(prompt, config, timeout):
        prompts.append(prompt)
        return first if len(prompts) == 1 else second

    res = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text=SOURCE,
                                 config=LLMConfig(gemini_api_key="k", mask_pii=False),
                                 providers=[("gemini", "m", fake)], budget_s=budget,
                                 recipient="หัวหน้ากลุ่มงานส่งเสริมกีฬา")
    return res, prompts


def test_repair_round_sends_issues_and_uses_fixed_draft():
    bad = _content(memo_consideration="๒. มอบหมายตามข้อเท็จจริง ๓ - ๕")
    good = _content()
    res, prompts = _run(bad, good)
    assert len(prompts) == 2 and "<issues>" in prompts[1] and "<previous_draft>" in prompts[1]
    assert res.repaired and res.review_left == [] and res.content.memo_consideration == good.memo_consideration


def test_no_repair_when_draft_is_clean():
    res, prompts = _run(_content(), _content())
    assert len(prompts) == 1 and not res.repaired and not res.review_issues


def test_no_repair_without_time_keeps_first_draft():
    bad = _content(memo_consideration="๒. มอบหมายตามข้อเท็จจริง ๓ - ๕")
    res, prompts = _run(bad, _content(), budget=12)
    assert len(prompts) == 1 and res.review_skipped and res.content.memo_consideration == bad.memo_consideration


def test_failed_repair_keeps_first_draft():
    bad = _content(memo_consideration="๒. มอบหมายตามข้อเท็จจริง ๓ - ๕")
    calls = []

    def fake(prompt, config, timeout):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return bad

    res = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text=SOURCE,
                                 config=LLMConfig(gemini_api_key="k", mask_pii=False),
                                 providers=[("gemini", "m", fake)])
    assert res.content is not None and not res.repaired and res.content.memo_consideration == bad.memo_consideration

"""
Step 23: ปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI และใส่ค่าจริงกลับ (core/pii_mask.py)
ใช้ผู้ให้บริการจำลอง ไม่เรียก API จริง
"""

from typing import List

from pydantic import BaseModel

from core import llm_drafter
from core.llm_drafter import DraftContent, LLMConfig, draft_content_with_llm, structured_call
from core.models import DocType
from core.pii_mask import PiiVault

SOURCE = """ด้วย นายสมชาย ใจดี เลขประจำตัวประชาชน 1-1020-30405-06-7 โทร 081-234-5678 อีเมล somchai@mail.com
บ้านเลขที่ 12/3 หมู่ที่ 4 ตำบลบางรัก ขอรับเงินเข้าบัญชีเลขที่ 123-4-56789-0
จึงเรียนมาเพื่อโปรดพิจารณา
(สมชาย ใจดี)"""
SECRETS = ("สมชาย", "ใจดี", "1-1020-30405-06-7", "081-234-5678", "somchai@mail.com", "12/3", "123-4-56789-0")


# ---------------------------------------------------------------- mask
def test_mask_hides_every_kind():
    vault = PiiVault()
    masked = vault.mask(SOURCE)
    for secret in SECRETS:
        assert secret not in masked, secret
    for token in ("[ชื่อ_1]", "[เลขบัตร_1]", "[โทร_1]", "[อีเมล_1]", "[บัญชี_1]", "[ที่อยู่_1]"):
        assert token in masked
    # ชื่อในวงเล็บใต้ลายมือชื่อ = คนเดียวกับ นายสมชาย ใจดี → รหัสเดิม
    assert "([ชื่อ_1])" in masked
    assert vault.counts["ชื่อ"] == 1
    assert vault.summary().startswith("อีเมล 1")


def test_mask_keeps_what_drafting_needs():
    text = "ตามหนังสือ ที่ กท 0123/4567 ลงวันที่ ๑ ตุลาคม ๒๕๖๙ ขอสนับสนุนงบประมาณ 15,000 บาท ตำบลบางรัก"
    vault = PiiVault()
    assert vault.mask(text) == text
    assert vault.total == 0


def test_words_starting_with_nai_are_not_names():
    text = "นายกรัฐมนตรี ได้สั่งการ นายอำเภอ และนายทะเบียน ตาม พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล นางพยาบาล"
    assert PiiVault().mask(text) == text


def test_name_does_not_swallow_following_verb():
    vault = PiiVault()
    masked = vault.mask("นางสาวสมหญิง ขอลาป่วย และนายมานะ ได้รับมอบหมาย")
    assert masked == "[ชื่อ_1] ขอลาป่วย และ[ชื่อ_2] ได้รับมอบหมาย"


def test_ranks_and_thai_digits():
    vault = PiiVault()
    masked = vault.mask("พ.ต.อ.สมศักดิ์ รักชาติ โทร ๐๘๑ ๒๓๔ ๕๖๗๘ และ ว่าที่ร้อยตรีเอก แสงดี")
    assert masked == "[ชื่อ_1] โทร [โทร_1] และ [ชื่อ_2]"


def test_same_value_same_token():
    vault = PiiVault()
    masked = vault.mask("นายสมชาย ใจดี แจ้งว่า สมชาย ใจดี (สมชาย ใจดี) โทร 0812345678 และ 081-234-5678")
    assert masked.count("[ชื่อ_1]") == 2 and "[ชื่อ_2]" not in masked
    assert masked.count("[โทร_1]") == 2


# ---------------------------------------------------------------- unmask
def test_unmask_restores_and_tolerates_ai_variants():
    vault = PiiVault()
    vault.mask(SOURCE)
    out = vault.unmask("[ชื่อ_1] / [ชื่อ ๑] / [ ชื่อ-1 ] / นาย[ชื่อ_1] / โทร [โทร_๑]")
    assert out == ("นายสมชาย ใจดี / นายสมชาย ใจดี / นายสมชาย ใจดี / นายสมชาย ใจดี / โทร 081-234-5678")


def test_unknown_token_becomes_placeholder():
    vault = PiiVault()
    vault.mask(SOURCE)
    assert vault.unmask("[ชื่อ_7] โทร [โทร_9]") == "[✏️ ระบุชื่อ] โทร [✏️ ระบุหมายเลขโทรศัพท์]"


def test_unmask_leaves_ordinary_brackets():
    vault = PiiVault()
    text = "[✏️ ระบุวันที่] และ [อ่านไม่ออก]"
    assert vault.unmask(text) == text


# ---------------------------------------------------------------- draft pipeline
CFG = LLMConfig(gemini_api_key="k", total_timeout_s=45)


def _capture(sent: List[str]):
    def call(prompt, config, timeout):
        sent.append(prompt)
        return DraftContent(
            subject="ขอรับเงินสนับสนุน",
            memo_intro="๑. [ชื่อ_1] ได้มีหนังสือ ขอรับเงินเข้าบัญชีเลขที่ [บัญชี_1]",
            memo_facts="๑. ติดต่อ [ชื่อ_1] โทร [โทร_1]",
            memo_consideration="พิจารณาแล้ว เห็นควรอนุมัติ",
            paragraph_reason="", paragraph_details="", paragraph_purpose="",
            reference="", source_summary="นาย[ชื่อ_1] ขอรับเงิน",
        )
    return call


def test_draft_prompt_has_no_personal_data_and_answer_is_restored():
    sent: List[str] = []
    result = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="ร่างบันทึกเสนอ นายสมชาย ใจดี",
                                    source_text=SOURCE, config=CFG, providers=[("gemini", "m", _capture(sent))])
    assert len(sent) == 1
    for secret in SECRETS:
        assert secret not in sent[0], secret
    assert "[ชื่อ_1]" in sent[0]
    c = result.content
    assert c.memo_intro == "๑. นายสมชาย ใจดี ได้มีหนังสือ ขอรับเงินเข้าบัญชีเลขที่ 123-4-56789-0"
    assert c.memo_facts == "๑. ติดต่อ นายสมชาย ใจดี โทร 081-234-5678"
    assert c.source_summary == "นายสมชาย ใจดี ขอรับเงิน"
    assert "ชื่อ 1" in result.masked


def test_mask_can_be_turned_off():
    sent: List[str] = []
    cfg = LLMConfig(gemini_api_key="k", total_timeout_s=45, mask_pii=False)
    result = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text=SOURCE, config=cfg,
                                    providers=[("gemini", "m", _capture(sent))])
    assert "นายสมชาย ใจดี" in sent[0]
    assert result.masked == ""


def test_system_prompt_tells_ai_to_keep_tokens():
    assert "[ชื่อ_1]" in llm_drafter.SYSTEM_PROMPT


# ---------------------------------------------------------------- structured_call (เสนอข้อกฎหมาย)
class Pick(BaseModel):
    id: str
    reason: str


class Picks(BaseModel):
    picks: List[Pick]


def test_structured_call_masks_prompt_and_unmasks_nested_answer(monkeypatch):
    sent = {}

    def fake_once(name, system, prompt, schema, config, timeout_s, errors):
        sent["prompt"] = prompt
        return Picks(picks=[Pick(id="a1", reason="เกี่ยวกับการจ่ายเงินให้ [ชื่อ_1]")])

    monkeypatch.setattr(llm_drafter, "_structured_once", fake_once)
    out = structured_call("sys", "เรื่องที่กำลังร่าง: นายสมชาย ใจดี ขอรับเงิน", Picks, CFG)
    assert "สมชาย" not in sent["prompt"]
    assert out.picks[0].reason == "เกี่ยวกับการจ่ายเงินให้ นายสมชาย ใจดี"

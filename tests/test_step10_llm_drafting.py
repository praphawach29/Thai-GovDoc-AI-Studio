"""
Step 10: AI ร่างเนื้อความ — Claude → Gemini → ร่างตามกฎ (สลับอัตโนมัติเมื่อตัวใดไม่ทำงาน)
ใช้ผู้ให้บริการจำลองทั้งหมด ไม่เรียก API จริง
"""

import json
import sys
import types

import pytest
from fastapi.testclient import TestClient

from core import llm_drafter
from core.llm_drafter import DraftContent, LLMConfig, apply_draft_content, draft_content_with_llm
from core.models import DocType, SecretLevel
from core.templates_library import PRESET_TEMPLATES

CONTENT = DraftContent(
    subject="ขอความอนุเคราะห์ใช้อาคารกีฬา",
    memo_intro="๑. สมาคมกีฬา ได้มีหนังสือ ที่ [✏️ ระบุเลขที่] ขอใช้อาคาร",
    memo_facts="๑. ขอใช้อาคารวันที่ [✏️ ระบุวันที่]",
    memo_consideration="กลุ่มงานส่งเสริมกีฬาพิจารณาแล้ว เห็นว่า... จึงเห็นควรอนุญาต",
    paragraph_reason="", paragraph_details="", paragraph_purpose="",
    reference="หนังสือสมาคมกีฬา ลงวันที่ ๑ ตุลาคม ๒๕๖๙",
)
CFG = LLMConfig(anthropic_api_key="k1", gemini_api_key="k2", total_timeout_s=45, claude_timeout_s=30)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _ok(seconds=1.0, clock=None, content=CONTENT):
    def call(prompt, config, timeout):
        if clock:
            clock.now += seconds
        return content
    return call


def _fail(exc, seconds=1.0, clock=None):
    def call(prompt, config, timeout):
        if clock:
            clock.now += seconds
        raise exc
    return call


def _run(providers, **kw):
    return draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="ต้นเรื่องทดสอบ",
                                  config=CFG, providers=providers, **kw)


def test_claude_first_when_it_works():
    calls = []
    res = _run([("claude", "claude-opus-5-5", lambda p, c, t: calls.append(("claude", t)) or CONTENT),
                ("gemini", "gemini-2.5-flash", lambda p, c, t: calls.append(("gemini", t)) or CONTENT)])
    assert res.provider == "claude" and [c[0] for c in calls] == ["claude"]
    assert calls[0][1] <= 30                                    # ตัวแรกไม่กินเวลารวมทั้งหมด


def test_falls_back_to_gemini_on_error_timeout_or_refusal():
    for exc, reason in [(RuntimeError("boom"), "เรียกไม่สำเร็จ"), (TimeoutError("timed out"), "หมดเวลา"),
                        (llm_drafter.ProviderRefused("x"), "ปฏิเสธ")]:
        res = _run([("claude", "m", _fail(exc)), ("gemini", "g", _ok())])
        assert res.provider == "gemini", exc
        assert not res.attempts[0].ok and reason in res.attempts[0].error


def test_all_fail_returns_none_for_rule_based():
    res = _run([("claude", "m", _fail(RuntimeError())), ("gemini", "g", _fail(ValueError("bad json")))])
    assert res.content is None and res.provider == "" and len(res.attempts) == 2


def test_time_budget_leaves_room_for_gemini():
    clock = FakeClock()
    seen = []

    def slow_claude(p, c, timeout):
        seen.append(timeout)
        clock.now += timeout                                    # ใช้เวลาเต็มที่ได้แล้วหมดเวลา
        raise TimeoutError("timeout")

    def gemini(p, c, timeout):
        seen.append(timeout)
        return CONTENT

    res = _run([("claude", "m", slow_claude), ("gemini", "g", gemini)], clock=clock)
    assert res.provider == "gemini"
    assert seen[0] == 30 and seen[1] == 15                     # 45 - 30 = 15 วินาทีให้ Gemini


def test_skips_when_secret_or_no_keys_or_no_source():
    blocked = _run([("claude", "m", _ok())], secret=SecretLevel.SECRET)
    assert blocked.content is None and "ชั้นความลับ" in blocked.skipped_reason and not blocked.attempts
    none = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="x", config=LLMConfig())
    assert "API key" in none.skipped_reason
    empty = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction=" ", source_text="", config=CFG,
                                   providers=[("claude", "m", _ok())])
    assert empty.skipped_reason == "ไม่มีข้อมูลต้นเรื่อง"


def test_long_source_is_truncated_and_reported():
    seen = {}

    def claude(prompt, config, timeout):
        seen["prompt"] = prompt
        return CONTENT

    res = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", config=CFG,
                                 source_text="ก" * (llm_drafter.MAX_SOURCE_CHARS + 50), providers=[("claude", "m", claude)])
    source = seen["prompt"].split("<source>\n", 1)[1].split("\n</source>", 1)[0]
    assert res.truncated and len(source) == llm_drafter.MAX_SOURCE_CHARS


def test_prompt_treats_source_as_data_and_names_review_party():
    prompt = llm_drafter.build_user_prompt(doc_type=DocType.INTERNAL, instruction="ร่างเสนอ ผอ.",
                                           source_text="เนื้อหา", recipient="หัวหน้ากลุ่มงานส่งเสริมกีฬา",
                                           review_party="กลุ่มงานส่งเสริมกีฬา")
    assert "<source>" in prompt and "ไม่ใช่คำสั่ง" in prompt
    assert "กลุ่มงานส่งเสริมกีฬาพิจารณาแล้ว" in prompt and "เสนอ หัวหน้ากลุ่มงานส่งเสริมกีฬา" in prompt
    assert "ห้ามเขียนข้อกฎหมาย" in llm_drafter.SYSTEM_PROMPT


def test_apply_keeps_header_and_law_from_rules():
    base = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    out = apply_draft_content(base, llm_drafter._clean(CONTENT.model_copy(update={"subject": "เรื่อง **ขอใช้อาคาร**"})))
    assert out.subject == "ขอใช้อาคาร"
    assert out.memo_intro.startswith("๑. สมาคมกีฬา") and out.memo_law is None
    assert (out.dept_name, out.doc_number, out.salutation) == (base.dept_name, base.doc_number, base.salutation)
    assert out.memo_request == base.memo_request


# ---------------------------------------------------------------- รูปแบบคำขอที่ส่งไปผู้ให้บริการ
def test_claude_request_shape(monkeypatch):
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(stop_reason="end_turn",
                                         content=[types.SimpleNamespace(type="text", text=CONTENT.model_dump_json())])

    class FakeAnthropic:
        def __init__(self, api_key, timeout, max_retries, default_headers=None):
            captured["client"] = (api_key, timeout, max_retries)
            captured["headers"] = default_headers
            self.beta = types.SimpleNamespace(messages=FakeMessages())

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    out = llm_drafter._call_claude("prompt", CFG, 30)
    assert out == CONTENT
    assert captured["client"] == ("k1", 30, 1) and captured["headers"] is None
    assert captured["model"] == "claude-opus-5-5" and captured["output_config"]["effort"] == "medium"
    schema = captured["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(DraftContent.model_fields)
    assert captured["fallbacks"] == "default" and captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in captured and "temperature" not in captured


def test_claude_refusal_raises(monkeypatch):
    class FakeAnthropic:
        def __init__(self, **kw):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(
                create=lambda **k: types.SimpleNamespace(stop_reason="refusal", content=[])))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    with pytest.raises(llm_drafter.ProviderRefused):
        llm_drafter._call_claude("p", CFG, 30)


def test_gemini_request_shape(monkeypatch):
    from google import genai

    captured = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            captured.update(model=model, config=config)
            return types.SimpleNamespace(parsed=CONTENT, text=CONTENT.model_dump_json())

    class FakeClient:
        def __init__(self, api_key, http_options):
            captured["timeout_ms"] = http_options.timeout
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    assert llm_drafter._call_gemini("prompt", CFG, 15) == CONTENT
    assert captured["model"] == "gemini-3.8-flash" and captured["timeout_ms"] == 15000
    assert captured["config"].response_schema is DraftContent


# ---------------------------------------------------------------- ผ่าน API ของหน้าเว็บ
def test_studio_draft_uses_ai_and_reports_fallback(monkeypatch):
    from server.main import app
    from server.settings import Settings, get_settings

    # ค่าเริ่มต้น Gemini ก่อน: Gemini หมดเวลา → Claude ร่างแทน
    monkeypatch.setattr(llm_drafter, "_call_gemini", _fail(TimeoutError("timeout")))
    monkeypatch.setattr(llm_drafter, "_call_claude", _ok())
    app.dependency_overrides[get_settings] = lambda: Settings(anthropic_api_key="k1", gemini_api_key="k2")
    try:
        body = TestClient(app).post("/api/v1/studio/draft", data={
            "prompt": "ร่างบันทึกขอใช้อาคารกีฬา", "doc_type": "internal"}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["ai_provider"] == "claude"
    step = next(s for s in body["steps"] if s["key"] == "ai")
    assert "Gemini หมดเวลา" in step["detail"] and "Claude" in step["detail"]
    doc = body["document"]
    assert doc["subject"] == CONTENT.subject and doc["memo_facts"].startswith("๑. ขอใช้อาคาร")
    # หน่วยตั้งต้น (กลุ่มงาน) ยังกำหนดหัวหนังสือ ผู้รับ และภาคความประสงค์
    assert doc["salutation"] == "เรียน หัวหน้ากลุ่มงานส่งเสริมกีฬา"
    assert doc["memo_request"].startswith("จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬา")


# ---------------------------------------------------------------- อ่านไฟล์สแกนด้วย AI
def _scanned_pdf(tmp_path, pages=2):
    from PIL import Image, ImageDraw

    imgs = []
    for i in range(pages):
        im = Image.new("RGB", (600, 850), "white")
        ImageDraw.Draw(im).rectangle((50, 50 + i * 10, 300, 80 + i * 10), fill="black")
        imgs.append(im)
    path = tmp_path / "scan.pdf"
    imgs[0].save(path, save_all=True, append_images=imgs[1:])
    return path


def test_ocr_gemini_first_then_claude():
    order = []
    ok = lambda name: (lambda imgs, c, t: order.append(name) or "--- หน้าที่ 1 ---\nข้อความที่อ่านได้จากภาพ ยาวพอ")
    res = llm_drafter.ocr_images_with_llm(["img"], CFG, providers=[
        ("gemini", "g", lambda imgs, c, t: (_ for _ in ()).throw(TimeoutError("timeout"))), ("claude", "c", ok("claude"))])
    assert res.provider == "claude" and order == ["claude"]
    assert res.attempts[0].error == "หมดเวลารอคำตอบ"
    empty = llm_drafter.ocr_images_with_llm(["img"], CFG, providers=[("gemini", "g", lambda i, c, t: "  ")])
    assert empty.text == "" and empty.attempts[0].error == "อ่านข้อความจากภาพไม่ได้"
    default = llm_drafter.ocr_images_with_llm(["img"], LLMConfig())
    assert default.text == "" and not default.attempts               # ไม่มีคีย์ = ไม่เรียก


def test_extractor_sends_all_scanned_pages_in_one_ai_call(tmp_path):
    from core.extractor import extract_source_document

    calls = []

    def ocr_fn(images):
        calls.append(len(images))
        return "--- หน้าที่ 1 ---\nสมาคมกีฬาขอใช้อาคาร\n--- หน้าที่ 2 ---\nรายละเอียด", "Gemini (gemini-2.5-flash)"

    ctx = extract_source_document(str(_scanned_pdf(tmp_path)), ocr_fn=ocr_fn)
    assert calls == [2] and not ctx.extraction_failed
    assert "สมาคมกีฬาขอใช้อาคาร" in ctx.raw_text and ctx.ocr_engine_used.startswith("Gemini")
    # ชั้นความลับ: ไม่เรียก AI เลย
    calls.clear()
    secret_ctx = extract_source_document(str(_scanned_pdf(tmp_path)), ocr_fn=ocr_fn, secret=SecretLevel.SECRET)
    assert calls == [] and secret_ctx.extraction_failed


def test_ai_ocr_failure_does_not_retry_page_by_page_in_cloud(tmp_path, monkeypatch):
    from core import extractor

    monkeypatch.setenv("GEMINI_API_KEY", "set-on-server")
    per_page = []
    monkeypatch.setattr(extractor, "extract_ocr_gemini", lambda img, api_key=None: per_page.append(1) or "x" * 50)
    ctx = extractor.extract_source_document(str(_scanned_pdf(tmp_path)), ocr_fn=lambda imgs: ("", None))
    assert per_page == [] and ctx.extraction_failed
    assert "ANTHROPIC_API_KEY" in ctx.extraction_error


def test_short_budget_puts_gemini_first(monkeypatch):
    order = []
    monkeypatch.setattr(llm_drafter, "_call_claude", lambda p, c, t: order.append("claude") or CONTENT)
    monkeypatch.setattr(llm_drafter, "_call_gemini", lambda p, c, t: order.append("gemini") or CONTENT)
    claude_first = LLMConfig(anthropic_api_key="k1", gemini_api_key="k2", provider_order=("claude", "gemini"))
    full = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="x", config=claude_first)
    short = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="x", config=claude_first,
                                   budget_s=20)
    assert full.provider == "claude" and short.provider == "gemini"


def test_studio_draft_scanned_pdf_end_to_end(tmp_path, monkeypatch):
    from server.main import app
    from server.settings import Settings, get_settings

    monkeypatch.setattr(llm_drafter, "_ocr_gemini", lambda imgs, c, t: "--- หน้าที่ 1 ---\nสมาคมวิ่งเปี้ยวขอเชิญเป็นเจ้าภาพร่วม")
    monkeypatch.setattr(llm_drafter, "_call_claude", _ok())
    app.dependency_overrides[get_settings] = lambda: Settings(
        anthropic_api_key="k1", gemini_api_key="k2", upload_dir=tmp_path / "up")
    try:
        with open(_scanned_pdf(tmp_path), "rb") as f:
            body = TestClient(app).post("/api/v1/studio/draft", data={"prompt": "ร่างบันทึกเสนอ", "doc_type": "internal"},
                                        files={"file": ("งานวิ่งเปี้ยว.pdf", f, "application/pdf")}).json()
    finally:
        app.dependency_overrides.clear()
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["extract"]["ok"] and "Gemini" in steps["extract"]["detail"]
    assert "วิ่งเปี้ยว" in body["context"]["raw_text"]
    assert body["ai_provider"] == "claude" and body["document"]["subject"] == CONTENT.subject


# ---------------------------------------------------------------- สาเหตุ error ที่แสดง/บันทึก
class _AnthropicLikeError(Exception):
    def __init__(self, status, message):
        super().__init__(f"Error code: {status}")
        self.status_code = status
        self.body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}


class _GoogleLikeError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code, self.message = code, message


@pytest.mark.parametrize("exc, expected", [
    (_AnthropicLikeError(400, "Your credit balance is too low to access the Anthropic API."), "เครดิต"),
    (_AnthropicLikeError(400, "messages.0.content.1: image too large"), "คำขอถูกปฏิเสธ (400): messages.0"),
    (_AnthropicLikeError(401, "invalid x-api-key"), "API key ไม่ถูกต้อง (401)"),
    (_GoogleLikeError(504, "Deadline expired before operation could complete."), "ไม่ทันเวลา (504)"),
    (_GoogleLikeError(404, "models/gemini-x is not found"), "ไม่พบรุ่นโมเดล"),
    (_GoogleLikeError(503, "The model is overloaded."), "ขัดข้องชั่วคราว (503)"),
])
def test_errors_are_described_by_status(exc, expected):
    assert expected in llm_drafter._short_error(exc)


def test_claude_retries_without_fallbacks_when_account_rejects_them():
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            if "fallbacks" in kw:
                raise _AnthropicLikeError(400, "fallbacks: this beta is not available for your organization")
            return "ok"

    client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=Messages()))
    assert llm_drafter._claude_create(client, {"model": "m", "fallbacks": "default", "betas": ["b"]}) == "ok"
    assert len(calls) == 2 and "fallbacks" not in calls[1] and "betas" not in calls[1]
    with pytest.raises(_AnthropicLikeError):            # 400 อื่นไม่ลองซ้ำ
        llm_drafter._claude_create(types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(
            create=lambda **kw: (_ for _ in ()).throw(_AnthropicLikeError(400, "image too large"))))),
            {"model": "m", "fallbacks": "default"})


def test_workspace_header_and_message(monkeypatch):
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **k: types.SimpleNamespace(
                stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=CONTENT.model_dump_json())])))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    llm_drafter._call_claude("p", LLMConfig(anthropic_api_key="k", anthropic_workspace_id="wrkspc_1"), 10)
    assert seen["default_headers"] == {"anthropic-workspace-id": "wrkspc_1"}
    err = _AnthropicLikeError(400, "This API key is not scoped to a workspace, so this request must include the "
                                   "anthropic-workspace-id header with the ID of the workspace to use")
    assert "ANTHROPIC_WORKSPACE_ID" in llm_drafter._short_error(err)


def test_gemini_low_thinking_with_retry_when_unsupported():
    configs = []

    class Models:
        def generate_content(self, model, contents, config):
            configs.append(config)
            if config.thinking_config is not None:
                raise _GoogleLikeError(400, "Thinking level is not supported for this model.")
            return "ok"

    client = types.SimpleNamespace(models=Models())
    assert llm_drafter._gemini_generate(client, "gemini-2.5-flash", "x", response_mime_type="application/json") == "ok"
    assert configs[0].thinking_config.thinking_level.value == "LOW" and configs[1].thinking_config is None
    assert configs[1].response_mime_type == "application/json"


# ---------------------------------------------------------------- ประเภทหนังสือที่จะร่าง
@pytest.mark.parametrize("hint, prompt, has_file, classified, expected", [
    (DocType.EXTERNAL, "ช่วยร่างบันทึกข้อความ", True, DocType.INTERNAL, DocType.EXTERNAL),   # ผู้ใช้เลือกเองชนะ
    (None, "ช่วยร่างบันทึกข้อความ เรื่องขอเป็นเจ้าภาพร่วม", True, DocType.EXTERNAL, DocType.INTERNAL),
    (None, "ร่างหนังสือตอบสมาคม", True, DocType.INTERNAL, DocType.EXTERNAL),
    (None, "", True, DocType.EXTERNAL, DocType.INTERNAL),        # ต้นเรื่องรับเข้า → บันทึกเสนอตามสายงาน
    (None, "ขอใช้อาคาร", False, DocType.EXTERNAL, DocType.EXTERNAL),
])
def test_choose_output_type(hint, prompt, has_file, classified, expected):
    from core.studio import choose_output_type

    assert choose_output_type(hint, prompt, has_source_file=has_file, classified=classified)[0] == expected


def test_incoming_letter_with_memo_request_drafts_memo(tmp_path, monkeypatch):
    """ต้นเรื่องเป็นหนังสือภายนอกจากสมาคม + คำสั่ง 'ร่างบันทึกข้อความ' → ได้บันทึกข้อความ (ไม่ใช่หนังสือภายนอก)"""
    from server.main import app
    from server.settings import Settings, get_settings

    monkeypatch.setattr(llm_drafter, "_ocr_gemini", lambda imgs, c, t:
                        "ที่ สวปท.๑๔/๒๕๖๗ ด้วยสมาคมวิ่งเปี้ยวขอเชิญกรุงเทพมหานครเป็นเจ้าภาพร่วม จึงเรียนมาเพื่อโปรดพิจารณา ขอแสดงความนับถือ")
    monkeypatch.setattr(llm_drafter, "_call_claude", _ok())
    app.dependency_overrides[get_settings] = lambda: Settings(
        anthropic_api_key="k1", gemini_api_key="k2", upload_dir=tmp_path / "up")
    try:
        with open(_scanned_pdf(tmp_path), "rb") as f:
            body = TestClient(app).post("/api/v1/studio/draft", data={
                "prompt": "ช่วยร่างบันทึกข้อความ เรื่องขอเป็นเจ้าร่วมกีฬาวิ่งเปี้ยว"},
                files={"file": ("งานวิ่งเปี้ยว.pdf", f, "application/pdf")}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["document"]["doc_type"] == "internal"
    step = next(s for s in body["steps"] if s["key"] == "classify")
    assert "บันทึกข้อความ" in step["detail"] and "คำสั่ง" in step["detail"]
    assert body["document"]["salutation"] == "เรียน หัวหน้ากลุ่มงานส่งเสริมกีฬา"



# ---------------------------------------------------------------- ใช้โมเดลเดียวทั้งงาน
def test_default_order_is_gemini_then_claude(monkeypatch):
    order = []
    monkeypatch.setattr(llm_drafter, "_call_claude", lambda p, c, t: order.append("claude") or CONTENT)
    monkeypatch.setattr(llm_drafter, "_call_gemini", lambda p, c, t: order.append("gemini") or CONTENT)
    res = draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="x", config=CFG)
    assert res.provider == "gemini" and order == ["gemini"]          # สำเร็จแล้วไม่เรียกตัวอื่น (ไม่เสียเงินซ้ำ)


def test_provider_that_read_the_file_keeps_drafting_and_failed_one_goes_last(monkeypatch):
    order = []
    monkeypatch.setattr(llm_drafter, "_call_claude", lambda p, c, t: order.append("claude") or CONTENT)
    monkeypatch.setattr(llm_drafter, "_call_gemini", lambda p, c, t: order.append("gemini") or CONTENT)
    draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="x", config=CFG, avoid=("gemini",))
    assert order == ["claude"]                                       # Gemini เพิ่งล้มตอนอ่านไฟล์ → Claude ทำต่อ
    order.clear()
    claude_first = LLMConfig(anthropic_api_key="k1", gemini_api_key="k2", provider_order=("claude", "gemini"))
    draft_content_with_llm(doc_type=DocType.INTERNAL, instruction="", source_text="x", config=claude_first,
                           prefer="gemini")
    assert order == ["gemini"]                                       # Gemini อ่านไฟล์สำเร็จ → ร่างต่อด้วย Gemini


def test_scanned_flow_uses_one_provider_end_to_end(tmp_path, monkeypatch):
    from server.main import app
    from server.settings import Settings, get_settings

    calls = []
    monkeypatch.setattr(llm_drafter, "_ocr_gemini", lambda i, c, t: calls.append("gemini-ocr") or "--- หน้าที่ 1 ---\nสมาคมขอเชิญเป็นเจ้าภาพร่วม")
    monkeypatch.setattr(llm_drafter, "_ocr_claude", lambda i, c, t: calls.append("claude-ocr") or "x" * 50)
    monkeypatch.setattr(llm_drafter, "_call_gemini", lambda p, c, t: calls.append("gemini-draft") or CONTENT)
    monkeypatch.setattr(llm_drafter, "_call_claude", lambda p, c, t: calls.append("claude-draft") or CONTENT)
    app.dependency_overrides[get_settings] = lambda: Settings(anthropic_api_key="k1", gemini_api_key="k2",
                                                              upload_dir=tmp_path / "up")
    try:
        with open(_scanned_pdf(tmp_path), "rb") as f:
            TestClient(app).post("/api/v1/studio/draft", data={"prompt": "ร่างบันทึกข้อความ"},
                                 files={"file": ("a.pdf", f, "application/pdf")})
    finally:
        app.dependency_overrides.clear()
    assert calls == ["gemini-ocr", "gemini-draft"]                   # ไม่แตะ Claude เลยเมื่อ Gemini ทำได้


def test_ai_order_setting(monkeypatch):
    from server.settings import Settings

    assert Settings().ai_order == ("gemini", "claude")
    monkeypatch.setenv("GOVDOC_AI_ORDER", "Claude, Gemini")
    assert Settings().ai_order == ("claude", "gemini")
    monkeypatch.setenv("GOVDOC_AI_ORDER", "openai")
    assert Settings().ai_order == ("gemini", "claude")               # ค่าผิดใช้ค่าเริ่มต้น


def test_gemini_model_setting_accepts_master_name(monkeypatch):
    from server.settings import Settings

    assert Settings().gemini_model == "gemini-3.8-flash"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x-flash")              # ชื่อที่ branch master ใช้
    assert Settings().gemini_model == "gemini-x-flash"
    monkeypatch.setenv("GOVDOC_GEMINI_MODEL", "gemini-y-flash")       # ชื่อหลักมาก่อน
    assert Settings().gemini_model == "gemini-y-flash"


def test_ocr_logo_annotation_gives_clean_sender_name():
    from core.extractor import parse_govdoc_metadata
    text = ("--- หน้าที่ 1 ---\n[ตรายางมุมบนซ้าย:] สนง. ปลัดกรุงเทพมหานคร เลขรับ 3778\n"
            "[ตราสัญลักษณ์: สมาคมวิ่งเปี้ยวประเทศไทย WING PIOW ASSOCIATION OF THAILAND]\n"
            "ที่ สวปท.๑๔/๒๕๖๙\n๒๓ กันยายน ๒๕๖๙\nเรื่อง ขอเชิญเป็นเจ้าภาพร่วม\nเรียน ผู้ว่าราชการกรุงเทพมหานคร\n")
    meta = parse_govdoc_metadata(text)
    assert meta["dept"] == "สมาคมวิ่งเปี้ยวประเทศไทย"


def test_ai_reference_replaces_pattern_guess():
    """อ้างถึงจาก AI (ชื่อองค์กรผู้ส่ง + วันที่ลงหนังสือ) แทนค่าที่จับจากรูปแบบข้อความ เมื่อเปิดหัวข้ออ้างถึงไว้"""
    from core.llm_drafter import apply_draft_content
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.references = ["หนังสือรองกรรมการผู้จัดการใหญ่ ลงวันที่ ๑๔ กันยายน ๒๕๖๘"]
    out = apply_draft_content(doc, CONTENT)
    assert out.references == ["หนังสือสมาคมกีฬา ลงวันที่ ๑ ตุลาคม ๒๕๖๙"]
    doc.references = None
    assert apply_draft_content(doc, CONTENT).references is None


def test_letter_date_line_preferred_over_event_date():
    from core.extractor import parse_govdoc_metadata
    text = ("บริษัท เซ็นทรัล จำกัด\nเรื่อง ขออนุญาตจัดกิจกรรม\nเรียน ผู้ว่าราชการกรุงเทพมหานคร\n"
            "ด้วยบริษัทจะจัดงานในวันอาทิตย์ที่ ๑๔ กันยายน ๒๕๖๘ ณ ลานหน้าศูนย์การค้า\n๒๒ กรกฎาคม ๒๕๖๘\n")
    assert parse_govdoc_metadata(text)["doc_date"] == "๒๒ กรกฎาคม ๒๕๖๘"

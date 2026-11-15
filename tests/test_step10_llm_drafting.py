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
        def __init__(self, api_key, timeout, max_retries):
            captured["client"] = (api_key, timeout, max_retries)
            self.beta = types.SimpleNamespace(messages=FakeMessages())

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    out = llm_drafter._call_claude("prompt", CFG, 30)
    assert out == CONTENT
    assert captured["client"] == ("k1", 30, 1)
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
    assert captured["model"] == "gemini-2.5-flash" and captured["timeout_ms"] == 15000
    assert captured["config"].response_schema is DraftContent


# ---------------------------------------------------------------- ผ่าน API ของหน้าเว็บ
def test_studio_draft_uses_ai_and_reports_fallback(monkeypatch):
    from server.main import app
    from server.settings import Settings, get_settings

    monkeypatch.setattr(llm_drafter, "_call_claude", _fail(TimeoutError("timeout")))
    monkeypatch.setattr(llm_drafter, "_call_gemini", _ok())
    app.dependency_overrides[get_settings] = lambda: Settings(anthropic_api_key="k1", gemini_api_key="k2")
    try:
        body = TestClient(app).post("/api/v1/studio/draft", data={
            "prompt": "ร่างบันทึกขอใช้อาคารกีฬา", "doc_type": "internal"}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["ai_provider"] == "gemini"
    step = next(s for s in body["steps"] if s["key"] == "ai")
    assert "Claude หมดเวลา" in step["detail"] and "Gemini" in step["detail"]
    doc = body["document"]
    assert doc["subject"] == CONTENT.subject and doc["memo_facts"].startswith("๑. ขอใช้อาคาร")
    # หน่วยตั้งต้น (กลุ่มงาน) ยังกำหนดหัวหนังสือ ผู้รับ และภาคความประสงค์
    assert doc["salutation"] == "เรียน หัวหน้ากลุ่มงานส่งเสริมกีฬา"
    assert doc["memo_request"].startswith("จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬา")

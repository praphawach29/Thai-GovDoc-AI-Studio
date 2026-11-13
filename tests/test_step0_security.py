"""
test_step0_security.py — Step 0: บังคับชั้นความลับที่ backend และ fail-closed
"""

import pytest

from PIL import Image

from core.ai_drafter import draft_from_context_llm, _sanitize_llm_draft
from core.extractor import extract_source_document
from core.models import GovDocumentSchema, SecretLevel, SourceDocumentContext
from core.security import CloudAIBlocked, cloud_ai_allowed


def test_cloud_ai_policy_fail_closed():
    assert cloud_ai_allowed(SecretLevel.NORMAL) is True
    assert cloud_ai_allowed("normal") is True
    for secret in [SecretLevel.SECRET, SecretLevel.VERY_SECRET, SecretLevel.TOP_SECRET]:
        assert cloud_ai_allowed(secret) is False
    # ค่าไม่ทราบ/ว่างต้อง fail-closed
    assert cloud_ai_allowed("") is False
    assert cloud_ai_allowed("unknown") is False


def test_llm_draft_blocks_secret_before_network():
    ctx = SourceDocumentContext(
        source_filename="x.txt",
        source_subject="เรื่องทดสอบ",
        raw_text="ข้อความทดสอบ",
    )
    with pytest.raises(CloudAIBlocked):
        draft_from_context_llm(ctx, secret=SecretLevel.SECRET, api_key="fake-key")


def test_llm_draft_blocks_when_allow_cloud_false():
    ctx = SourceDocumentContext(
        source_filename="x.txt",
        source_subject="เรื่องทดสอบ",
        raw_text="ข้อความทดสอบ",
    )
    with pytest.raises(CloudAIBlocked):
        draft_from_context_llm(ctx, allow_cloud=False, api_key="fake-key")


def test_sanitize_clears_number_date_and_law():
    doc = GovDocumentSchema.model_validate({
        "doc_type": "internal",
        "doc_number": "๑๒๓/๒๕๖๙",
        "dept_name": "หน่วยงาน",
        "doc_date": "๑๕ มีนาคม ๒๕๖๙",
        "subject": "เรื่อง",
        "salutation": "เรียน ผู้บริหาร",
        "paragraph_reason": "ด้วยเหตุผล",
        "paragraph_purpose": "จึงเรียนมาเพื่อโปรดพิจารณา",
        "memo_law": "พระราชบัญญัติปลอม พ.ศ. ๒๕๐๐",
        "closing": "",
        "signatory_name": "(นายทดสอบ)",
        "signatory_position": "ตำแหน่ง",
        "contact_dept": "ฝ่าย",
    })
    doc = _sanitize_llm_draft(doc)
    assert doc.doc_number.startswith("......../")
    assert doc.memo_law is None


def test_ocr_does_not_call_external_ai_for_secret(tmp_path, monkeypatch):
    called = {"gemini": False}

    def fake_gemini(pil_img, api_key=None):
        called["gemini"] = True
        return "ไม่ควรถูกเรียก"

    monkeypatch.setattr("core.extractor.extract_ocr_gemini", fake_gemini)

    image = Image.new("RGB", (40, 40), "white")
    image_path = tmp_path / "secret.png"
    image.save(image_path)

    ctx = extract_source_document(str(image_path), allow_cloud=True, secret=SecretLevel.SECRET)
    assert called["gemini"] is False
    assert ctx.ocr_engine_used != "Gemini Vision"


def test_ocr_does_not_call_external_ai_when_allow_cloud_false(tmp_path, monkeypatch):
    called = {"gemini": False}

    def fake_gemini(pil_img, api_key=None):
        called["gemini"] = True
        return "ไม่ควรถูกเรียก"

    monkeypatch.setattr("core.extractor.extract_ocr_gemini", fake_gemini)

    image = Image.new("RGB", (40, 40), "white")
    image_path = tmp_path / "normal.png"
    image.save(image_path)

    ctx = extract_source_document(str(image_path), allow_cloud=False, secret=SecretLevel.NORMAL)
    assert called["gemini"] is False
    assert ctx.ocr_engine_used != "Gemini Vision"

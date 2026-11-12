"""
test_phase11_p0_safety.py — P0: ห้าม AI สร้างเลขที่/วันที่, Linter และ security gate
"""

from datetime import date

import pytest

from core.ai_drafter import draft_from_context_llm, draft_from_context_rule_based
from core.linter import lint_gov_document
from core.models import DOC_NUMBER_PLACEHOLDER, DocType, SecretLevel, SourceDocumentContext, is_blank_doc_number
from core.security import CloudAIBlocked, assert_cloud_ai_allowed, cloud_ai_allowed
from core.templates_library import PRESET_TEMPLATES
from core.thai_date import blank_doc_number, format_thai_date


@pytest.fixture
def ctx():
    return SourceDocumentContext(
        source_filename="request.txt",
        source_dept="สมาคมกีฬาทดสอบ",
        source_doc_no="ทด ๐๑/๒๕๖๙",
        source_date="๑ พฤศจิกายน ๒๕๖๙",
        source_subject="ขอความอนุเคราะห์จัดกิจกรรม",
        raw_text="สมาคมกีฬาทดสอบขอความอนุเคราะห์จัดกิจกรรม",
        summary="ขอความอนุเคราะห์จัดกิจกรรม",
    )


def test_rule_based_draft_does_not_invent_number_or_date(ctx):
    doc = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL)
    assert is_blank_doc_number(doc.doc_number)
    assert doc.doc_number == blank_doc_number()
    assert doc.doc_date == format_thai_date()
    assert "มีนาคม ๒๕๖๙" not in doc.doc_date


def test_thai_date_formatter():
    assert format_thai_date(date(2026, 11, 12)) == "12 พฤศจิกายน 2569"
    assert format_thai_date(date(2026, 11, 12), use_thai_numerals=True) == "๑๒ พฤศจิกายน ๒๕๖๙"


def test_cloud_ai_security_policy():
    assert cloud_ai_allowed(SecretLevel.NORMAL) is True
    assert cloud_ai_allowed(SecretLevel.SECRET) is False
    with pytest.raises(CloudAIBlocked):
        assert_cloud_ai_allowed(SecretLevel.SECRET)


def test_llm_draft_blocks_cloud_for_secret(ctx):
    with pytest.raises(CloudAIBlocked):
        draft_from_context_llm(ctx, secret=SecretLevel.SECRET, api_key="test-key")


def test_llm_draft_blocks_when_allow_cloud_false(ctx):
    with pytest.raises(CloudAIBlocked):
        draft_from_context_llm(ctx, allow_cloud=False, api_key="test-key")


def test_linter_warns_placeholder_number():
    doc = PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)
    doc.doc_number = DOC_NUMBER_PLACEHOLDER
    res = lint_gov_document(doc)
    assert any(i.rule_id == "RULE_DOC_NUMBER_PLACEHOLDER" for i in res.warnings)


def test_linter_errors_missing_number():
    doc = PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)
    doc.doc_number = ""
    res = lint_gov_document(doc)
    assert any(i.rule_id == "RULE_DOC_NUMBER_MISSING" for i in res.errors)


def test_linter_warns_multiple_references_for_external():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.doc_type = DocType.EXTERNAL
    doc.references = ["หนังสือฉบับที่ ๑", "หนังสือฉบับที่ ๒"]
    res = lint_gov_document(doc)
    assert any(i.rule_id == "RULE_REFERENCES_SINGLE" for i in res.warnings)


def test_blank_doc_number_format_and_detection():
    value = blank_doc_number()
    assert value.startswith("......../")
    assert is_blank_doc_number(value) is True
    assert is_blank_doc_number("123/2569") is False

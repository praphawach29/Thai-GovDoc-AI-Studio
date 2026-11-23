"""ตัวเลขลายมือ/ตรายางในต้นเรื่อง (AI ติดป้าย [ลายมือ] ตอนอ่านไฟล์) → จุดตรวจในร่าง"""
from core.handwriting import flag_handwritten, flag_text, handwritten_numbers
from core.llm_drafter import OCR_HANDWRITING, OCR_PROMPT, ocr_images_with_llm, LLMConfig
from core.templates_library import PRESET_TEMPLATES

SOURCE = """ที่ สวปท.๑๔/๒๕๖๙                       วันที่ ๒๓ กันยายน ๒๕๖๙
ที่ กท ๐๒๐๐/๕๗๕๙[ลายมือ]
เรียน ป.กทม.
ลว. ๒๘ ก.ย. ๒๕๖๙[ลายมือ]
ที่ กท ๐๒๐๐/๒๖๗๔[ลายมือ]
รับที่ ๓๑๘๒[ลายมือ]  วันที่ ๑[ลายมือ] ต.ค."""


def test_handwritten_numbers_skip_years_and_short_numbers():
    assert handwritten_numbers(SOURCE) == {"5759", "2674", "3182"}


def test_flag_text_turns_handwritten_numbers_into_check_points():
    text = "เลขานุการฯ ได้มีบันทึก ที่ กท ๐๒๐๐/๕๗๕๙ ลงวันที่ ๒๘ กันยายน ๒๕๖๙ และ ที่ กท ๐๒๐๐/2674[ลายมือ]"
    out = flag_text(text, handwritten_numbers(SOURCE))
    assert "[✏️ ระบุเลขลายมือ (AI อ่านได้ ๕๗๕๙)]" in out
    assert "[✏️ ระบุเลขลายมือ (AI อ่านได้ 2674)]" in out
    assert "๒๘ กันยายน ๒๕๖๙" in out and "[ลายมือ]" not in out and "\0" not in out


def test_tagged_years_and_days_copied_by_ai_are_not_check_points():
    text = "ลงวันที่ ๒๘[ลายมือ] กันยายน ๒๕๖๙[ลายมือ] เรียน ปลัดฯ ที่ ๐๒๐๐/๖๖๘๒[ลายมือ]"
    assert flag_text(text, set()) == "ลงวันที่ ๒๘ กันยายน ๒๕๖๙ เรียน ปลัดฯ ที่ ๐๒๐๐/[✏️ ระบุเลขลายมือ (AI อ่านได้ ๖๖๘๒)]"


def test_flag_text_leaves_existing_chips_and_typed_numbers():
    text = "ที่ [✏️ ระบุเลขที่ ๕๗๕๙] หนังสือ ที่ สวปท.๑๔/๒๕๖๙"
    assert flag_text(text, {"5759"}) == text


def test_flag_handwritten_on_memo_counts_once():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.memo_intro = "๑. เลขานุการฯ ได้มีบันทึก ที่ กท ๐๒๐๐/๕๗๕๙ ลงวันที่ ๒๘ กันยายน ๒๕๖๙"
    doc.paragraph_reason = doc.memo_intro
    assert flag_handwritten(doc, SOURCE) == 1
    assert "ระบุเลขลายมือ" in doc.memo_intro and "ระบุเลขลายมือ" in doc.paragraph_reason


def test_no_tags_in_source_changes_nothing():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    doc.memo_intro = "ที่ กท ๐๒๐๐/๕๗๕๙"
    assert flag_handwritten(doc, "ที่ กท ๐๒๐๐/๕๗๕๙") == 0 and doc.memo_intro == "ที่ กท ๐๒๐๐/๕๗๕๙"


def test_ocr_prompt_marks_handwriting_only_when_asked(monkeypatch):
    import core.llm_drafter as m

    seen = []
    monkeypatch.setattr(m, "_ocr_gemini", lambda images, config, timeout, prompt=OCR_PROMPT: seen.append(prompt) or "ข้อความ" * 10)
    cfg = LLMConfig(gemini_api_key="k")
    ocr_images_with_llm(["img"], cfg, mark_handwriting=True)
    ocr_images_with_llm(["img"], cfg)
    assert OCR_HANDWRITING in seen[0] and OCR_HANDWRITING not in seen[1]


def test_check_point_sits_right_after_slash():
    assert flag_text("ที่ กท ๐๒๐๐/ ๒๖๙๔[ลายมือ] ลงวันที่", set()) == "ที่ กท ๐๒๐๐/[✏️ ระบุเลขลายมือ (AI อ่านได้ ๒๖๙๔)] ลงวันที่"

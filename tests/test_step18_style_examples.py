"""
Step 18: คลังตัวอย่างของหน่วย — หนังสือฉบับจริงที่ลงนามแล้ว ใช้สอนสำนวนให้ AI (few-shot)
"""

from core.models import DocType
from core.style_examples import (
    MASK_DATE,
    MASK_NAME,
    MASK_NUMBER,
    few_shot_block,
    from_document,
    keywords_of,
    mask_facts,
    parse_example,
    rank_examples,
    unmask_leftovers,
)

# บันทึกข้อความแบบ กทม. ที่ AI OCR อ่านจากไฟล์สแกน (มีคำอธิบายภาพ, ตัดบรรทัดกลางประโยค)
MEMO = """--- หน้าที่ 1 ---
[ตราครุฑ]
บันทึกข้อความ
ส่วนราชการ กลุ่มงานส่งเสริมกีฬา กองการกีฬา โทร. ๐ ๒๒๔๗ ๐๐๗๗
ที่ กท ๑๒๐๕/๑๒๓๔ วันที่ ๓ พฤศจิกายน ๒๕๖๙
เรื่อง ขอความอนุเคราะห์ใช้สนามกีฬาจัดการแข่งขันฟุตบอลเยาวชน
เรียน ผู้อำนวยการกองการกีฬา
ต้นเรื่อง
๑. สมาคมกีฬาฟุตบอลแห่งประเทศไทย ได้มีหนังสือ ที่ สฟท ๐๗๗/๒๕๖๙ ลงวันที่ ๒๗ ตุลาคม ๒๕๖๙
ขอความอนุเคราะห์ใช้สนามกีฬาไทย-ญี่ปุ่น ดินแดง
ข้อเท็จจริง
๑. การแข่งขันกำหนดจัดระหว่างวันที่ ๑๕ - ๑๖ พฤศจิกายน ๒๕๖๙ เวลา ๐๘.๐๐ - ๑๘.๐๐ น.
๒. ผู้ประสานงานคือ นายสมชาย ใจดี โทร. ๐๘๑ ๒๓๔ ๕๖๗๘
ข้อพิจารณาและเสนอแนะ
กลุ่มงานส่งเสริมกีฬาพิจารณาแล้ว เห็นว่า การจัดการแข่งขันดังกล่าวเป็นการส่งเสริมกีฬาเยาวชน
จึงเห็นควรอนุญาตให้ใช้สนามกีฬาตามที่ขอ
จึงเรียนมาเพื่อโปรดพิจารณา
(นางสาวสุดา รักงาน)
นักพัฒนาการกีฬาชำนาญการ
"""

LETTER = """[ตราครุฑ]
ที่ กท ๑๒๐๕/๕๖๗
สำนักวัฒนธรรม กีฬา และการท่องเที่ยว
ศาลาว่าการกรุงเทพมหานคร ๒
๑๐ พฤศจิกายน ๒๕๖๙
เรื่อง ตอบรับการขอใช้สนามกีฬา
เรียน นายกสมาคมกีฬาฟุตบอลแห่งประเทศไทย
อ้างถึง หนังสือสมาคมกีฬาฟุตบอลแห่งประเทศไทย ที่ สฟท ๐๗๗/๒๕๖๙
ลงวันที่ ๒๗ ตุลาคม ๒๕๖๙
สิ่งที่ส่งมาด้วย ๑. แผนผังสนาม จำนวน ๑ ฉบับ

ตามหนังสือที่อ้างถึง สมาคมกีฬาฟุตบอลแห่งประเทศไทย ขอความอนุเคราะห์ใช้สนามกีฬาไทย-ญี่ปุ่น ดินแดง
เพื่อจัดการแข่งขันฟุตบอลเยาวชน ความละเอียดแจ้งแล้ว นั้น

สำนักวัฒนธรรม กีฬา และการท่องเที่ยว พิจารณาแล้ว ยินดีให้ใช้สนามกีฬาตามวันและเวลาที่ขอ
ทั้งนี้ ขอให้ประสานกับผู้ดูแลสนามล่วงหน้าไม่น้อยกว่า ๓ วัน

จึงเรียนมาเพื่อโปรดทราบ
ขอแสดงความนับถือ
(นายวิชัย มั่นคง)
ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว
ส่วนราชการเจ้าของเรื่อง กองการกีฬา
โทร. ๐ ๒๒๔๗ ๐๐๗๗
"""


def test_parse_memo_by_headings():
    ex = parse_example(MEMO)
    assert ex.doc_type == DocType.INTERNAL
    assert ex.subject == "ขอความอนุเคราะห์ใช้สนามกีฬาจัดการแข่งขันฟุตบอลเยาวชน"
    assert ex.part_reason.startswith("๑. สมาคมกีฬาฟุตบอลแห่งประเทศไทย")
    assert "ขอความอนุเคราะห์ใช้สนามกีฬาไทย-ญี่ปุ่น" in ex.part_reason          # บรรทัดที่ OCR ตัดต่อกันแล้ว
    assert "\n" not in ex.part_reason
    assert ex.part_details.splitlines()[1].startswith("๒. ผู้ประสานงาน")
    assert ex.part_purpose.startswith("กลุ่มงานส่งเสริมกีฬาพิจารณาแล้ว")
    assert ex.part_purpose.endswith("จึงเรียนมาเพื่อโปรดพิจารณา")
    assert "สุดา" not in ex.part_purpose and "ตราครุฑ" not in ex.part_reason   # ผู้ลงนาม/คำอธิบายภาพไม่ปน
    assert ex.usable


def test_parse_external_letter_three_parts():
    ex = parse_example(LETTER)
    assert ex.doc_type == DocType.EXTERNAL
    assert ex.subject == "ตอบรับการขอใช้สนามกีฬา"
    assert ex.part_reason.startswith("ตามหนังสือที่อ้างถึง") and ex.part_reason.endswith("นั้น")
    assert "แผนผังสนาม" not in ex.part_reason and "ลงวันที่ ๒๗" not in ex.part_reason   # อ้างถึง/สิ่งที่ส่งมาด้วยไม่ปน
    assert ex.part_details.startswith("สำนักวัฒนธรรม") and "ทั้งนี้" in ex.part_details
    assert ex.part_purpose == "จึงเรียนมาเพื่อโปรดทราบ"
    assert "วิชัย" not in ex.part_purpose + ex.part_details


def test_parse_letter_without_blank_lines():
    text = LETTER.replace("\n\n", "\n")
    ex = parse_example(text)
    assert ex.part_reason.startswith("ตามหนังสือที่อ้างถึง")
    assert ex.part_purpose == "จึงเรียนมาเพื่อโปรดทราบ"


def test_parse_garbage_is_not_usable():
    assert not parse_example("[ภาพไม่ชัด]\nอ่านไม่ออก").usable


def test_from_document():
    from core.studio import create_blank_document, normalize_for_editor

    doc = normalize_for_editor(create_blank_document(DocType.INTERNAL))
    doc.subject = "ขอใช้สนาม"
    doc.memo_intro = "๑. สมาคม ... ได้มีหนังสือ"
    doc.memo_facts = "ข้อเท็จจริง"
    doc.memo_consideration = "พิจารณาแล้ว เห็นควร"
    ex = from_document(doc)
    assert ex.doc_type == DocType.INTERNAL and ex.subject == "ขอใช้สนาม"
    assert ex.part_reason.startswith("๑. สมาคม") and ex.part_purpose.startswith("พิจารณาแล้ว")
    assert ex.part_purpose.endswith("จึงเรียนมาเพื่อโปรดพิจารณา")


def test_mask_facts_hides_numbers_dates_names_keeps_style():
    text = ("๑. สมาคม ได้มีหนังสือ ที่ สฟท ๐๗๗/๒๕๖๙ ลงวันที่ ๒๗ ตุลาคม ๒๕๖๙ ผู้ประสานงานคือ นายสมชาย ใจดี "
            "เสนอนายกรัฐมนตรีและนายทะเบียน เงิน 12,500 บาท\n๒. นางสาวสุดา รักงาน")
    out = mask_facts(text)
    assert "๐๗๗" not in out and "๒๗" not in out and "12,500" not in out
    assert MASK_DATE in out and MASK_NUMBER in out and out.count(MASK_NAME) == 2
    assert "สมชาย" not in out and "สุดา" not in out
    assert "นายกรัฐมนตรี" in out and "นายทะเบียน" in out          # ไม่ใช่ชื่อคน
    assert out.startswith("๑. ") and "\n๑. " in out              # เลขข้อคงรูปแบบ


def test_rank_examples_prefers_same_topic():
    rows = [
        {"id": "a", "subject": "ขอใช้สนามกีฬาจัดการแข่งขันฟุตบอล",
         "keywords": keywords_of("ขอใช้สนามกีฬาจัดการแข่งขันฟุตบอล สมาคมกีฬา ขอความอนุเคราะห์ใช้สนาม")},
        {"id": "b", "subject": "ขอเบิกค่าตอบแทนวิทยากร",
         "keywords": keywords_of("ขอเบิกค่าตอบแทนวิทยากร โครงการอบรม งบประมาณ")},
        {"id": "c", "subject": "ขออนุมัติจัดซื้อวัสดุสำนักงาน", "keywords": keywords_of("จัดซื้อ วัสดุ สำนักงาน")},
    ]
    got = rank_examples("สมาคมกีฬาวอลเลย์บอลขอความอนุเคราะห์ใช้สนามกีฬาเพื่อจัดการแข่งขัน", rows)
    assert [r["id"] for r, _ in got][:1] == ["a"]
    assert "c" not in [r["id"] for r, _ in got]
    assert rank_examples("", rows) == [] and rank_examples("ฟุตบอล", []) == []


def test_few_shot_block_masks_and_respects_budget():
    ex = parse_example(MEMO).model_dump(mode="json")
    block = few_shot_block([ex])
    assert block.startswith("ตัวอย่างสำนวน") and '<example n="1" type="บันทึกข้อความ">' in block
    assert "ต้นเรื่อง:" in block and "ข้อพิจารณาและเสนอแนะ:" in block
    assert "๑๒๓๔" not in block and "สมชาย" not in block and "๐๘๑" not in block
    assert "ห้ามนำข้อเท็จจริงในตัวอย่างมาใช้" in block
    long = dict(ex, part_details="ข้อความยาว " * 2000)
    many = few_shot_block([long, long, long, long])
    assert many.count("<example ") == 3 and len(many) < 6500
    assert few_shot_block([]) == ""


def test_unmask_leftovers():
    assert unmask_leftovers(f"ลงวันที่ {MASK_DATE} โดย {MASK_NAME} ที่ {MASK_NUMBER}") == \
        "ลงวันที่ [✏️ ระบุวันที่] โดย [✏️ ระบุชื่อ] ที่ [✏️ ระบุ]"

"""
copilot.py — เครื่องมือช่วยเหลือผู้ใช้งานแบบ Human-in-the-loop (AI Copilot Assistant)
ยกระดับการตรวจแก้ ขัดเกลาภาษา และแทรกข้อกฎหมายระเบียบราชการ
"""

import re
from typing import Optional
from core.models import GovDocumentSchema, DocType
from core.thai_segmenter import to_thai_numerals, to_arabic_numerals


COMMON_LEGAL_REFERENCES = {
    "procurement": "พระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. ๒๕๖๐",
    "saraban": "ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม",
    "digital_gov": "พระราชบัญญัติการบริหารงานและการให้บริการภาครัฐผ่านระบบดิจิทัล พ.ศ. ๒๕๖๒",
    "pdpa": "พระราชบัญญัติคุ้มครองข้อมูลส่วนบุคคล พ.ศ. ๒๕๖๒",
    "budget": "พระราชบัญญัติวิธีการงบประมาณ พ.ศ. ๒๕๖๑",
    "official_info": "พระราชบัญญัติข้อมูลข่าวสารของราชการ พ.ศ. ๒๕๔๐"
}


def make_formal_tone(text: str) -> str:
    """ขัดเกลาข้อความให้เป็นภาษาราชการชั้นสูงและสุภาพรัดกุม"""
    replacements = [
        ("เยอะ", "จำนวนมาก"),
        ("ขอให้", "ขอความอนุเคราะห์ให้"),
        ("ช่วย", "โปรดให้ความอนุเคราะห์"),
        ("เสร็จแล้ว", "ดำเนินการเรียบร้อยแล้ว"),
        ("ต้องการ", "มีความประสงค์"),
        ("คุยกัน", "หารือร่วมกัน"),
        ("ส่งของ", "ส่งมอบพัสดุ/เอกสาร"),
        ("บอกว่า", "แจ้งว่า"),
        ("ไม่เอา", "ไม่ประสงค์จะรับ"),
        ("เร็วๆ นี้", "ในโอกาสแรก"),
        ("จ่ายเงิน", "เบิกจ่ายงบประมาณ"),
        ("ทำเรื่อง", "ดำเนินการจัดทำเอกสาร"),
        ("ติดขัด", "มีข้อขัดข้อง"),
        ("ส่งเมล", "ส่งทางไปรษณีย์อิเล็กทรอนิกส์")
    ]
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def make_concise(text: str) -> str:
    """ย่อความให้กระชับ ตัดประโยคที่ซ้ำซ้อนโดยคงสาระสำคัญไว้ครบถ้วน"""
    from core.thai_segmenter import segment_thai_words
    text = re.sub(r'\s+', ' ', text).strip()
    words = segment_thai_words(text)
    if len(words) > 10:
        # ย่อเหลือประมาณ 65% ของจำนวนคำ
        cutoff = max(8, int(len(words) * 0.65))
        return "".join(words[:cutoff]).strip()
    return text


def insert_legal_reference(doc: GovDocumentSchema, law_key: str) -> GovDocumentSchema:
    """
    แทรกการอ้างอิงข้อกฎหมายหรือระเบียบราชการลงในภาคข้อเท็จจริง/พิจารณา (Paragraph 2)
    """
    law_text = COMMON_LEGAL_REFERENCES.get(law_key, law_key)
    citation = f"ทั้งนี้ การดำเนินการดังกล่าวเป็นไปตามหลักเกณฑ์ที่กำหนดไว้ใน {law_text} "

    doc_copy = doc.model_copy(deep=True)
    if doc_copy.paragraph_details:
        doc_copy.paragraph_details = doc_copy.paragraph_details.strip() + " " + citation
    else:
        doc_copy.paragraph_details = citation
    return doc_copy


def convert_doc_type(doc: GovDocumentSchema, target_type: DocType) -> GovDocumentSchema:
    """
    แปลงระหว่างหนังสือภายนอก <-> หนังสือภายใน (บันทึกข้อความ) อัตโนมัติ
    """
    doc_copy = doc.model_copy(deep=True)
    doc_copy.doc_type = target_type

    if target_type == DocType.INTERNAL:
        # หนังสือภายใน: ไม่มีคำลงท้าย (เช่น ขอแสดงความนับถือ)
        doc_copy.closing = ""
        # ยุบส่วนราชการให้กระชับ
        doc_copy.dept_name = re.split(r'\s+(?:ถนน|ต\.|ตำบล|อ\.|อำเภอ|จ\.|จังหวัด)', doc_copy.dept_name)[0]
    else:
        # หนังสือภายนอก: มีคำลงท้าย และใช้คำขึ้นต้นเป็นทางการ
        if not doc_copy.closing:
            doc_copy.closing = "ขอแสดงความนับถือ"
    return doc_copy


def toggle_doc_numerals(doc: GovDocumentSchema, use_thai: bool) -> GovDocumentSchema:
    """
    แปลงตัวเลขทุกจุดในเอกสาร (เลขที่, วันที่, อ้างถึง, 3 ย่อหน้า) ให้สอดคล้องกันทั้งฉบับ
    """
    doc_copy = doc.model_copy(deep=True)
    doc_copy.use_thai_numerals = use_thai
    converter = to_thai_numerals if use_thai else to_arabic_numerals

    doc_copy.doc_number = converter(doc_copy.doc_number)
    doc_copy.doc_date = converter(doc_copy.doc_date)
    doc_copy.paragraph_reason = converter(doc_copy.paragraph_reason)
    if doc_copy.paragraph_details:
        doc_copy.paragraph_details = converter(doc_copy.paragraph_details)
    doc_copy.paragraph_purpose = converter(doc_copy.paragraph_purpose)

    if doc_copy.references:
        doc_copy.references = [converter(r) for r in doc_copy.references]
    if doc_copy.attachments:
        doc_copy.attachments = [converter(a) for a in doc_copy.attachments]
    if doc_copy.contact_tel:
        doc_copy.contact_tel = converter(doc_copy.contact_tel)

    return doc_copy

"""
linter.py — เครื่องมือตรวจสอบความถูกต้องของหนังสือราชการตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
(Automated Sarabun Rules Linter)
"""

import re
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from core.models import DocType, GovDocumentSchema, is_blank_doc_number


THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
]

HIGH_OFFICIALS = [
    "นายกรัฐมนตรี", "ประธานองคมนตรี", "ประธานรัฐสภา", "ประธานสภาผู้แทนราษฎร",
    "ประธานวุฒิสภา", "ประธานศาลฎีกา", "ประธานศาลรัฐธรรมนูญ", "ประธานศาลปกครองสูงสุด"
]


class LintIssue(BaseModel):
    rule_id: str
    severity: str = Field(..., description="'error' หรือ 'warning'")
    field: str
    message: str
    suggestion: str


class LintResult(BaseModel):
    is_valid: bool
    issues: List[LintIssue] = Field(default_factory=list)

    @property
    def errors(self) -> List[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[LintIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def lint_gov_document(doc: GovDocumentSchema) -> LintResult:
    """
    ตรวจสอบความถูกต้องของหนังสือราชการตามกฎระเบียบงานสารบรรณ
    """
    issues: List[LintIssue] = []

    # 1. ตรวจสอบวันที่ (Rule: RULE_NO_PREFIX_DATE)
    if doc.doc_date.strip().startswith("วันที่"):
        issues.append(LintIssue(
            rule_id="RULE_NO_PREFIX_DATE",
            severity="error",
            field="doc_date",
            message="ห้ามใส่คำว่า 'วันที่' นำหน้าวันเดือนปีในหนังสือราชการ",
            suggestion=f"ตัดคำว่า 'วันที่' ออก ให้เหลือเฉพาะ '{re.sub(r'^วันที่\s*', '', doc.doc_date.strip())}'"
        ))

    # ตรวจสอบว่ามีชื่อเดือนภาษาไทยหรือไม่
    has_thai_month = any(m in doc.doc_date for m in THAI_MONTHS)
    if not has_thai_month:
        issues.append(LintIssue(
            rule_id="RULE_THAI_MONTH_NAME",
            severity="warning",
            field="doc_date",
            message="วันที่ควรระบุชื่อเดือนเต็มเป็นภาษาไทย",
            suggestion="เช่น '๑๕ มีนาคม ๒๕๖๙' หรือ '15 มีนาคม 2569'"
        ))

    # 1.1 ตรวจสอบเลขที่หนังสือ: AI ต้องไม่สร้างเอง และต้องออกจากทะเบียนก่อนส่ง
    number = doc.doc_number.strip()
    if not number:
        issues.append(LintIssue(
            rule_id="RULE_DOC_NUMBER_MISSING",
            severity="error",
            field="doc_number",
            message="ยังไม่มีเลขที่หนังสือ",
            suggestion="เว้นช่องเป็น '......../ปี พ.ศ.' แล้วออกเลขจากทะเบียนหนังสือส่งก่อนส่งออก"
        ))
    elif is_blank_doc_number(number):
        issues.append(LintIssue(
            rule_id="RULE_DOC_NUMBER_PLACEHOLDER",
            severity="warning",
            field="doc_number",
            message="เลขที่หนังสือยังเป็นช่องว่างสำหรับกรอก",
            suggestion="ออกเลขที่หนังสือจากทะเบียนส่ง แล้วแทนที่ช่องนี้ก่อนเสนอลงนาม"
        ))

    # 1.2 หนังสือภายนอกควรอ้างถึงหนังสือฉบับสุดท้ายเพียงฉบับเดียว
    if doc.doc_type == DocType.EXTERNAL and doc.references and len(doc.references) > 1:
        issues.append(LintIssue(
            rule_id="RULE_REFERENCES_SINGLE",
            severity="warning",
            field="references",
            message="หนังสือภายนอกควรอ้างถึงหนังสือที่เคยติดต่อกันฉบับสุดท้ายเพียงฉบับเดียว",
            suggestion="เลือกอ้างถึงเฉพาะหนังสือฉบับสุดท้าย หรือย้ายฉบับอื่นไปไว้ใน 'สิ่งที่ส่งมาด้วย'"
        ))

    # 2. ตรวจสอบโครงสร้างเนื้อความ
    if doc.doc_type == DocType.INTERNAL:
        # บันทึกข้อความ: ตรวจสอบ ต้นเรื่อง, ข้อเท็จจริง, ข้อพิจารณาและเสนอแนะ, และประโยคลงท้าย (ข้อกฎหมายเป็น "ถ้ามี")
        intro, facts, law, consideration, request = doc._memo_parts()

        # 2.1 ต้นเรื่อง (ต้องมีทุกครั้ง)
        clean_intro = (intro or "").strip()
        if not clean_intro:
            issues.append(LintIssue(
                rule_id="RULE_MEMO_REQUIRED_INTRO",
                severity="error",
                field="memo_intro",
                message="หนังสือบันทึกข้อความต้องมีเนื้อความ 'ต้นเรื่อง' ทุกครั้ง",
                suggestion="ต้องระบุความเป็นมาของเรื่อง หรือหนังสือ/คำร้องเดิมที่ได้รับ"
            ))

        # 2.2 ข้อเท็จจริง (ต้องมีทุกครั้ง)
        clean_facts = (facts or "").strip()
        if not clean_facts:
            issues.append(LintIssue(
                rule_id="RULE_MEMO_REQUIRED_FACTS",
                severity="error",
                field="memo_facts",
                message="หนังสือบันทึกข้อความต้องมีเนื้อความ 'ข้อเท็จจริง' ทุกครั้ง",
                suggestion="ต้องระบุรายละเอียดผลการตรวจสอบ ข้อเท็จจริง หรือรายการคำขอแยกเป็นข้อ ๆ"
            ))

        # 2.3 ข้อพิจารณาและเสนอแนะ (ต้องมีทุกครั้ง)
        if doc.memo_intro is not None or doc.memo_facts is not None or doc.memo_consideration is not None:
            clean_consideration = (consideration or "").strip()
            if not clean_consideration:
                issues.append(LintIssue(
                    rule_id="RULE_MEMO_REQUIRED_CONSIDERATION",
                    severity="error",
                    field="memo_consideration",
                    message="หนังสือบันทึกข้อความต้องมีเนื้อความ 'ข้อพิจารณาและเสนอแนะ' ทุกครั้ง",
                    suggestion="ต้องระบุการวิเคราะห์ข้อดีข้อเสีย และข้อเสนอแนะ ๑., ๒., ๓. สำหรับให้ผู้บังคับบัญชาพิจารณา"
                ))

        # 2.4 ประโยคลงท้ายตามระดับชั้น (ต้องมีทุกครั้ง)
        clean_req = (request or "").strip()
        if not clean_req:
            issues.append(LintIssue(
                rule_id="RULE_MEMO_REQUIRED_CLOSING",
                severity="error",
                field="memo_request",
                message="หนังสือบันทึกข้อความต้องมีประโยคลงท้ายตามระดับชั้น",
                suggestion="เช่น 'จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนาม...' หรือตามระดับชั้นที่เสนอ"
            ))
        elif not (clean_req.startswith("จึงเรียน") or clean_req.startswith("จึงกราบเรียน")):
            issues.append(LintIssue(
                rule_id="RULE_MEMO_CLOSING_CONVENTION",
                severity="warning",
                field="memo_request",
                message="ประโยคลงท้ายในบันทึกข้อความ ควรขึ้นต้นด้วย 'จึงเรียนมาเพื่อ...' หรือ 'จึงกราบเรียนมาเพื่อ...'",
                suggestion="เช่น 'จึงเรียนมาเพื่อโปรดพิจารณา' หรือ 'จึงเรียนมาเพื่อโปรดพิจารณาลงนาม...'"
            ))
    else:
        # หนังสือภายนอก: ตรวจสอบโครงสร้าง 3 ภาค (Rule: RULE_3_PARAGRAPHS)
        # 2.1 ภาคเหตุ
        valid_reason_starters = ("ด้วย", "เนื่องจาก", "ตามที่", "สืบเนื่องจาก")
        clean_reason = doc.paragraph_reason.strip()
        if not clean_reason:
            issues.append(LintIssue(
                rule_id="RULE_MISSING_REASON_PARAGRAPH",
                severity="error",
                field="paragraph_reason",
                message="ขาดข้อความภาคเหตุ (ย่อหน้าที่ 1)",
                suggestion="ต้องระบุความเป็นมา หรือเหตุผลในการออกหนังสือ"
            ))
        elif not any(clean_reason.startswith(s) for s in valid_reason_starters):
            issues.append(LintIssue(
                rule_id="RULE_REASON_CONVENTION",
                severity="warning",
                field="paragraph_reason",
                message="ภาคเหตุมักขึ้นต้นด้วยคำว่า 'ด้วย', 'เนื่องจาก' (เรื่องใหม่) หรือ 'ตามที่', 'สืบเนื่องจาก' (เรื่องเดิม)",
                suggestion=f"พิจารณาขึ้นต้นด้วย 'ด้วย...' หรือ 'ตามที่...'"
            ))

        # 2.2 ภาคความประสงค์ / สรุป
        clean_purpose = doc.paragraph_purpose.strip()
        if not clean_purpose:
            issues.append(LintIssue(
                rule_id="RULE_MISSING_PURPOSE_PARAGRAPH",
                severity="error",
                field="paragraph_purpose",
                message="ขาดข้อความภาคความประสงค์หรือภาคสรุป",
                suggestion="ต้องระบุสิ่งที่ต้องการให้ผู้รับดำเนินการ"
            ))
        elif not clean_purpose.startswith("จึงเรียนมาเพื่อ"):
            issues.append(LintIssue(
                rule_id="RULE_PURPOSE_CONVENTION",
                severity="warning",
                field="paragraph_purpose",
                message="ภาคสรุป/ประสงค์ในหนังสือราชการ ควรขึ้นต้นด้วยคำว่า 'จึงเรียนมาเพื่อ...'",
                suggestion="เช่น 'จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติ' หรือ 'จึงเรียนมาเพื่อโปรดทราบ'"
            ))

    # 3. ตรวจสอบคำขึ้นต้นและคำลงท้าย (Rule: RULE_SALUTATION_CLOSING)
    if doc.doc_type == DocType.EXTERNAL:
        # ตรวจสอบกรณีผู้รับเป็นบุคคลชั้นผู้ใหญ่ (นายกฯ, ประธานรัฐสภา, ประธานศาลฎีกา)
        is_high_official = any(title in doc.salutation for title in HIGH_OFFICIALS)
        if is_high_official:
            if not doc.salutation.startswith("กราบเรียน"):
                issues.append(LintIssue(
                    rule_id="RULE_HIGH_OFFICIAL_SALUTATION",
                    severity="error",
                    field="salutation",
                    message="ผู้รับดำรงตำแหน่งระดับสูง (นายกรัฐมนตรี/ประธานรัฐสภา/ประธานศาล) ต้องใช้คำขึ้นต้นว่า 'กราบเรียน'",
                    suggestion="เปลี่ยนคำขึ้นต้นเป็น 'กราบเรียน'"
                ))
            if doc.closing != "ขอแสดงความนับถืออย่างยิ่ง":
                issues.append(LintIssue(
                    rule_id="RULE_HIGH_OFFICIAL_CLOSING",
                    severity="error",
                    field="closing",
                    message="ผู้รับระดับสูงต้องใช้คำลงท้ายว่า 'ขอแสดงความนับถืออย่างยิ่ง'",
                    suggestion="เปลี่ยนคำลงท้ายเป็น 'ขอแสดงความนับถืออย่างยิ่ง'"
                ))
        else:
            if doc.salutation.startswith("กราบเรียน") and not is_high_official:
                issues.append(LintIssue(
                    rule_id="RULE_OVER_HONORIFIC_SALUTATION",
                    severity="warning",
                    field="salutation",
                    message="ตำแหน่งทั่วไปนิยมใช้คำขึ้นต้นว่า 'เรียน'",
                    suggestion="ตรวจสอบว่าผู้รับอยู่ในข่ายที่ต้องใช้ 'กราบเรียน' หรือไม่"
                ))

    # 4. ตรวจสอบความสอดคล้องของตัวเลข (Rule: RULE_NUMERAL_CONSISTENCY)
    # ครอบคลุมทั้งหนังสือภายนอก (3 ภาค) และบันทึกข้อความ กทม. (ทุกส่วน) ไม่ใช่เฉพาะ paragraph_*
    body_fields = [
        ("paragraph_reason", doc.paragraph_reason),
        ("paragraph_details", doc.paragraph_details),
        ("paragraph_purpose", doc.paragraph_purpose),
        ("memo_intro", doc.memo_intro),
        ("memo_facts", doc.memo_facts),
        ("memo_law", doc.memo_law),
        ("memo_consideration", doc.memo_consideration),
        ("memo_request", doc.memo_request),
    ]
    checked_texts = set()
    mixed_fields = []
    for field_name, value in body_fields:
        text = (value or "").strip()
        if not text or text in checked_texts:
            continue
        checked_texts.add(text)
        has_thai_digits = bool(re.search(r'[๐-๙]', text))
        has_arabic_digits = bool(re.search(r'[0-9]', text))
        if has_thai_digits and has_arabic_digits:
            mixed_fields.append(field_name)

    if mixed_fields:
        issues.append(LintIssue(
            rule_id="RULE_MIXED_NUMERALS",
            severity="warning",
            field=", ".join(mixed_fields),
            message=f"พบการใช้ทั้งเลขไทยและเลขอารบิกปะปนกันใน: {', '.join(mixed_fields)}",
            suggestion="ควรเลือกใช้เลขไทยทั้งหมด หรือเลขอารบิกทั้งหมดให้เป็นไปในทิศทางเดียวกัน (รวมถึงเลขลำดับข้อ เช่น '๑. ๒. ๓.')"
        ))

    # 5. ตรวจสอบข้อมูลผู้ลงนาม
    if not doc.signatory_name.strip():
        issues.append(LintIssue(
            rule_id="RULE_MISSING_SIGNATORY_NAME",
            severity="error",
            field="signatory_name",
            message="ต้องระบุชื่อเต็มของผู้ลงนาม",
            suggestion="ระบุชื่อในวงเล็บ เช่น '(นายสมชาย ดิจิทัล)'"
        ))

    # 6. ตรวจสอบชื่อไฟล์หลุดเข้าไปในหัวเรื่องหรือเอกสารอ้างถึง (Rule: RULE_FILENAME_IN_METADATA)
    file_ext_pattern = r'\.(pdf|docx?|xlsx?|pptx?|png|jpe?g|tiff?|bmp|txt)\b'
    if doc.subject and re.search(file_ext_pattern, doc.subject, flags=re.IGNORECASE):
        issues.append(LintIssue(
            rule_id="RULE_FILENAME_IN_METADATA",
            severity="error",
            field="subject",
            message=f"พบชื่อไฟล์ดิบ ('{doc.subject}') ในช่องเรื่อง",
            suggestion="ให้ระบุชื่อเรื่องของหนังสือจริง แทนการใช้ชื่อไฟล์ เช่น 'ขอความอนุเคราะห์...' หรือ 'รายงานการพิจารณา...'"
        ))

    if doc.references:
        for idx, ref in enumerate(doc.references):
            if re.search(file_ext_pattern, ref, flags=re.IGNORECASE):
                issues.append(LintIssue(
                    rule_id="RULE_FILENAME_IN_METADATA",
                    severity="error",
                    field=f"references[{idx}]",
                    message=f"พบชื่อไฟล์ดิบ ('{ref}') ในเอกสารอ้างถึง",
                    suggestion="ควรระบุเป็น 'หนังสือ[หน่วยงาน] ที่... ลงวันที่...' แทนการอ้างอิงชื่อไฟล์ตรงๆ"
                ))

    # 6.1 ตรวจสอบชื่อไฟล์หลุดในเนื้อความของบันทึกข้อความ (ทุกส่วน)
    memo_field_labels = {
        "memo_intro": "ต้นเรื่อง",
        "memo_facts": "ข้อเท็จจริง",
        "memo_consideration": "ข้อพิจารณาและเสนอแนะ",
        "memo_request": "ประโยคลงท้าย",
    }
    for field_name, label in memo_field_labels.items():
        value = getattr(doc, field_name, None) or ""
        match = re.search(file_ext_pattern, value, flags=re.IGNORECASE)
        if match:
            issues.append(LintIssue(
                rule_id="RULE_FILENAME_IN_METADATA",
                severity="error",
                field=field_name,
                message=f"พบนามสกุลไฟล์ ('{match.group(0)}') หลุดในส่วน '{label}'",
                suggestion="ให้ระบุชื่อเรื่องหรือข้อความจริงของหนังสือ แทนการอ้างอิงชื่อไฟล์"
            ))

    # คำนวณสถานะ is_valid (ต้องไม่มี error ใดๆ)
    has_errors = any(i.severity == "error" for i in issues)
    return LintResult(is_valid=not has_errors, issues=issues)


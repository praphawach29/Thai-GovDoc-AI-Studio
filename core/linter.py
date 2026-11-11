"""
linter.py — เครื่องมือตรวจสอบความถูกต้องของหนังสือราชการตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
(Automated Sarabun Rules Linter)
"""

import re
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from core.models import GovDocumentSchema, DocType


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

    # 2. ตรวจสอบโครงสร้าง 3 ภาค (Rule: RULE_3_PARAGRAPHS)
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
    full_text = f"{doc.paragraph_reason} {doc.paragraph_details or ''} {doc.paragraph_purpose}"
    has_thai_digits = bool(re.search(r'[๐-๙]', full_text))
    has_arabic_digits = bool(re.search(r'[0-9]', full_text))
    if has_thai_digits and has_arabic_digits:
        issues.append(LintIssue(
            rule_id="RULE_MIXED_NUMERALS",
            severity="warning",
            field="paragraphs",
            message="พบการใช้ทั้งเลขไทยและเลขอารบิกปะปนกันในเนื้อหา",
            suggestion="ควรเลือกใช้เลขไทยทั้งหมด หรือเลขอารบิกทั้งหมดให้เป็นไปในทิศทางเดียวกัน"
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

    # คำนวณสถานะ is_valid (ต้องไม่มี error ใดๆ)
    has_errors = any(i.severity == "error" for i in issues)
    return LintResult(is_valid=not has_errors, issues=issues)


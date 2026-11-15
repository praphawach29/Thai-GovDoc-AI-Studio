"""
ai_drafter.py — สมองกลยกร่างหนังสือราชการไทย (AI Drafting & Reasoning Engine)
อ้างอิง Prompt Engineering จาก Boom-Vitt/claude-thai-skills และระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
"""

import os
import re
from enum import Enum
from typing import Optional, List

from core.models import (
    GovDocumentSchema,
    SourceDocumentContext,
    DocType,
    UrgencyLevel,
    SecretLevel,
    MemoHierarchyLevel,
)
from core.profile_manager import get_user_profile
from core.security import CloudAIBlocked, assert_cloud_ai_allowed
from core.thai_date import blank_doc_number, format_thai_date
from core.thai_segmenter import to_thai_numerals, to_arabic_numerals


class DraftingIntent(str, Enum):
    ACCEPT = "accept"          # หนังสือตอบรับ / ยินดีให้ความอนุเคราะห์
    DECLINE = "decline"        # หนังสือแจ้งข้อขัดข้อง / ปฏิเสธอย่างสุภาพ
    FORWARD = "forward"        # หนังสือส่งต่อเรื่อง / แจ้งเวียน
    PROPOSAL = "proposal"      # บันทึกข้อความเสนอผู้บังคับบัญชาเพื่อโปรดพิจารณาอนุมัติ
    MEMO_REVIEW = "memo_review"# บันทึกข้อความรายงานการพิจารณา / เกษียนสั่งการรวมกับเรื่องเดิม (ตามโมเดล Ekkasarn)


def draft_from_context_rule_based(ctx: SourceDocumentContext, 
                                  doc_type: DocType = DocType.EXTERNAL,
                                  intent: DraftingIntent = DraftingIntent.ACCEPT,
                                  my_dept: Optional[str] = None,
                                  my_signatory: Optional[str] = None,
                                  my_position: Optional[str] = None,
                                  contact_dept: Optional[str] = None,
                                  contact_tel: Optional[str] = None,
                                  secret: SecretLevel = SecretLevel.NORMAL) -> GovDocumentSchema:
    """
    สร้างร่างหนังสือราชการตามบริบทต้นเรื่องและเจตนา (Intent-aware Drafting)
    พร้อมระบบ Fail-Safe หยุดการยกร่างหากไม่สามารถถอดข้อความได้ และดึงโปรไฟล์หน่วยงานของผู้ใช้
    """
    # 0. FAIL-SAFE CHECK: ห้ามยกร่างหากการสกัดข้อความล้มเหลว หรือไม่มีข้อความ
    if getattr(ctx, "extraction_failed", False) or not (ctx.raw_text or "").strip():
        raise ValueError(
            "ไม่สามารถยกร่างหนังสือได้ เนื่องจากระบบไม่สามารถสกัดข้อความจากเอกสารต้นเรื่องได้ "
            "(กรุณาระบุ GEMINI_API_KEY หรือเปิดใช้งาน Local Docker OCR หรือกรอกข้อความด้วยตนเอง)"
        )

    # โหลดโปรไฟล์หน่วยงานของผู้ใช้งาน
    user_prof = get_user_profile()
    if my_dept is None:
        my_dept = user_prof.department_full if doc_type == DocType.INTERNAL else user_prof.dept_name
    if my_signatory is None:
        my_signatory = user_prof.signatory_name
    if my_position is None:
        my_position = user_prof.signatory_position
    if contact_dept is None:
        contact_dept = user_prof.contact_dept
    if contact_tel is None:
        contact_tel = user_prof.contact_tel

    # AI ต้องไม่สร้างเลขที่เอง — เว้นให้ทะเบียนออกเลขภายหลัง
    doc_no = blank_doc_number(use_thai_numerals=False)
    doc_date = format_thai_date(use_thai_numerals=False)
    
    # 1. การกำหนดเรื่อง (Subject) — ห้ามใช้ชื่อไฟล์ที่มีนามสกุล (.pdf, .docx) เด็ดขาด
    file_ext_pattern = r'\.(pdf|docx?|xlsx?|pptx?|png|jpe?g|txt)\b'
    raw_sub = (ctx.source_subject or "").strip()
    if not raw_sub or re.search(file_ext_pattern, raw_sub, flags=re.IGNORECASE):
        orig_subject = "[✏️ ระบุเรื่อง]"
    else:
        orig_subject = raw_sub

    sep = " " if re.match(r'^[A-Za-z0-9_]', orig_subject) else ""

    if doc_type == DocType.INTERNAL:
        if intent == DraftingIntent.MEMO_REVIEW:
            subject = f"รายงานการพิจารณาหนังสือ{sep}{orig_subject}"
        else:
            subject = f"ขออนุมัติดำเนินการเกี่ยวกับ{sep}{orig_subject}"
        salutation = "เรียน  [✏️ ระบุตำแหน่งผู้บังคับบัญชา]"
    else:
        if intent == DraftingIntent.ACCEPT:
            subject = f"การให้ความอนุเคราะห์{orig_subject.replace('ขอความอนุเคราะห์', '').replace('การขอ', '')}"
        elif intent == DraftingIntent.DECLINE:
            subject = f"แจ้งข้อขัดข้องเกี่ยวกับ{sep}{orig_subject}"
        elif intent == DraftingIntent.FORWARD:
            subject = f"ส่งเรื่อง{sep}{orig_subject} เพื่อโปรดพิจารณา"
        elif intent == DraftingIntent.MEMO_REVIEW:
            subject = f"รายงานผลการพิจารณาเรื่อง{sep}{orig_subject}"
        else:
            subject = orig_subject

        if ctx.source_dept and ctx.source_dept != "หน่วยงานต้นเรื่อง":
            salutation = f"เรียน  {ctx.source_dept}"
        else:
            salutation = "เรียน  [✏️ ระบุตำแหน่งผู้รับ]"

    # 2. การสร้างข้ออ้างถึง (References) — ห้ามใช้ "เอกสาร <filename>.pdf"
    references = []
    ref_desc = ""
    source_dept_label = ctx.source_dept if (ctx.source_dept and ctx.source_dept != "หน่วยงานต้นเรื่อง") else "หน่วยงานต้นเรื่อง"
    if ctx.source_doc_no or ctx.source_date:
        ref_text = f"หนังสือ{source_dept_label}"
        if ctx.source_doc_no:
            ref_text += f" ที่ {ctx.source_doc_no}"
        if ctx.source_date:
            ref_text += f" ลงวันที่ {ctx.source_date}"
        references.append(ref_text)
        ref_desc = "ที่อ้างถึง "
    else:
        references.append(f"หนังสือ{source_dept_label} [✏️ ระบุเลขที่และลงวันที่]")
        ref_desc = "ที่อ้างถึง "

    # 3. โครงสร้างเนื้อความ 3 ภาค (Paragraphs)
    # ภาคเหตุ
    if references:
        paragraph_reason = (
            f"ตามที่ {ctx.source_dept} ได้มีหนังสือ{ref_desc}"
            f"เรื่อง {orig_subject} ความละเอียดแจ้งแล้ว นั้น"
        )
    else:
        paragraph_reason = (
            f"ด้วย {my_dept} ได้รับเรื่องประสานงานเกี่ยวกับ "
            f"{orig_subject} จาก {ctx.source_dept}"
        )

    # ภาคข้อเท็จจริงและข้อพิจารณา (ตามเจตนา Intent)
    # ใช้ถ้อยคำมาตรฐานทางราชการ + ข้อเท็จจริงจากต้นเรื่อง/โปรไฟล์เท่านั้น
    # เหตุผล/ชื่อ/งบประมาณ/ภารกิจเฉพาะที่ไม่มีในต้นเรื่องต้องเป็น placeholder
    if intent == DraftingIntent.ACCEPT:
        paragraph_details = (
            f"{my_dept} ได้พิจารณาแล้ว มีความยินดีและไม่ขัดข้องในการให้ความอนุเคราะห์ตามที่ขอ"
        )
        paragraph_purpose = "จึงเรียนมาเพื่อโปรดทราบ"

    elif intent == DraftingIntent.DECLINE:
        paragraph_details = (
            f"{my_dept} ได้พิจารณาแล้ว มีความจำเป็นต้องขออภัยที่ไม่สามารถให้การสนับสนุนตามที่แจ้งความประสงค์ได้ "
            f"เนื่องจาก[✏️ ระบุเหตุผลข้อขัดข้อง]"
        )
        paragraph_purpose = "จึงเรียนมาเพื่อโปรดทราบและโปรดเข้าใจในข้อขัดข้องดังกล่าวด้วย จะขอบคุณยิ่ง"

    elif intent == DraftingIntent.FORWARD:
        paragraph_details = (
            f"{my_dept} ได้พิจารณาแล้วเห็นว่า เรื่องดังกล่าวอยู่ในอำนาจหน้าที่และความรับผิดชอบของหน่วยงานท่าน "
            f"จึงขอส่งเรื่องดังกล่าวมาเพื่อโปรดพิจารณาดำเนินการตามอำนาจหน้าที่ต่อไป"
        )
        paragraph_purpose = "จึงเรียนมาเพื่อโปรดพิจารณาดำเนินการ และแจ้งผลให้ทราบต่อไปด้วย จะขอบคุณยิ่ง"

    elif intent == DraftingIntent.MEMO_REVIEW:
        paragraph_details = (
            f"ได้ตรวจสอบเรื่อง{orig_subject} แล้ว เห็นควร[✏️ ระบุข้อเสนอ/ความเห็นของหน่วยงาน]"
        )
        paragraph_purpose = "ข้อพิจารณาและข้อเสนอ [✏️ ระบุข้อเสนอ/ความเห็นของหน่วยงาน]"

    else:  # PROPOSAL (บันทึกข้อความ)
        paragraph_details = (
            f"{my_dept} ได้พิจารณาแล้วเห็นว่า เรื่อง{orig_subject} มีความจำเป็นและเป็นประโยชน์ "
            f"จึงขอเสนอ[✏️ ระบุรายละเอียด/งบประมาณ] เพื่อโปรดพิจารณา"
        )
        paragraph_purpose = "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติการดำเนินการตามที่เสนอ"

    # คำนวณฟิลด์เฉพาะสำหรับบันทึกข้อความ ๔ หัวข้อย่อยมาตรฐาน และประโยคลงท้ายตามระดับชั้น
    memo_intro = paragraph_reason if doc_type == DocType.INTERNAL else None
    if doc_type == DocType.INTERNAL and getattr(ctx, "source_case", None):
        synth = ctx.source_case.synthesize_memo_intro()
        if synth and len(synth) > 20:
            memo_intro = synth

    memo_facts = paragraph_details if doc_type == DocType.INTERNAL else None
    if doc_type == DocType.INTERNAL and getattr(ctx, "source_case", None) and ctx.source_case.requested_items:
        # เลขลำดับข้อเป็นเลขไทยล้วน (๑. ๒. ๓.) ไม่ผสมเลขอารบิก
        items_bullets = "\n".join([
            f"{to_thai_numerals(str(i))}. {req}"
            for i, req in enumerate(ctx.source_case.requested_items, 1)
        ])
        if memo_facts:
            memo_facts = f"{memo_facts}\nโดยมีประเด็นคำขอดังนี้\n{items_bullets}"
        else:
            memo_facts = f"ในการนี้ จากการตรวจสอบข้อเท็จจริง มีประเด็นคำขอดังนี้\n{items_bullets}"

    memo_law = None  # Step 0: ข้อกฎหมายต้องมาจากต้นเรื่อง + ผู้ใช้ยืนยันเท่านั้น — ห้ามเติมจาก keyword
    memo_hierarchy_level = MemoHierarchyLevel.DEPT_TO_PERM_SEC
    memo_request = None
    if doc_type == DocType.INTERNAL:
        sal_lower = salutation.lower()
        if "ปลัด" in sal_lower:
            memo_hierarchy_level = MemoHierarchyLevel.DEPT_TO_PERM_SEC
            memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร เพื่อโปรดพิจารณาให้ความเห็นชอบและสั่งการตามที่เสนอข้างต้น"
        elif any(k in sal_lower for k in ["ผู้อำนวยการสำนัก", "อธิบดี"]):
            memo_hierarchy_level = MemoHierarchyLevel.DIV_TO_DEPT
            memo_request = "จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ"
        elif any(k in sal_lower for k in ["หัวหน้ากลุ่มงาน", "ผู้อำนวยการกอง", "หัวหน้าฝ่าย"]):
            memo_hierarchy_level = MemoHierarchyLevel.SECTION_TO_DIV
            memo_request = "จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองลงนามในหนังสือที่แนบ"
        elif any(k in sal_lower for k in ["ผู้ว่าราชการ", "นายกรัฐมนตรี"]):
            memo_hierarchy_level = MemoHierarchyLevel.FINAL_APPROVAL
            memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"
        else:
            memo_hierarchy_level = MemoHierarchyLevel.DEPT_TO_PERM_SEC
            memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"

    memo_consideration = paragraph_purpose if doc_type == DocType.INTERNAL else None

    return GovDocumentSchema(
        doc_type=doc_type,
        urgency=UrgencyLevel.NORMAL,
        secret=secret,
        use_thai_numerals=False,
        doc_number=doc_no,
        dept_name=my_dept,
        doc_date=doc_date,
        subject=subject,
        salutation=salutation,
        references=references if references else None,
        attachments=None,  # Step 0: สิ่งที่ส่งมาด้วยต้องมาจากต้นเรื่อง/ผู้ใช้ — ห้ามสร้างรายการแนบขึ้นเอง
        paragraph_reason=paragraph_reason,
        paragraph_details=paragraph_details,
        paragraph_purpose=paragraph_purpose,
        memo_intro=memo_intro,
        memo_facts=memo_facts,
        memo_law=memo_law,
        memo_consideration=memo_consideration,
        memo_request=memo_request,
        memo_hierarchy_level=memo_hierarchy_level,
        closing="ขอแสดงความนับถือ" if doc_type == DocType.EXTERNAL else "",
        signatory_name=my_signatory,
        signatory_position=my_position,
        contact_dept=contact_dept,
        contact_tel=contact_tel,
        contact_fax=user_prof.contact_fax or "๐ ๒๒๔๖ ๐๒๘๒",
        contact_email=user_prof.contact_email or "sports.bma@bangkok.go.th"
    )



MEMO_DRAFTING_RULES = """สำหรับหนังสือภายใน (บันทึกข้อความ) ต้องแบ่งเนื้อความเป็น ๔ ส่วนและประโยคลงท้ายตามระดับชั้น ดังนี้:
   - memo_intro (ต้นเรื่อง - ต้องมีทุกครั้ง): ที่มาของเรื่อง หนังสือ/คำร้องเดิมที่ได้รับ (เลขที่ ลงวันที่ เรียน เรื่อง) และการสั่งการที่ผ่านมา
   - memo_law (ข้อกฎหมาย - ถ้ามี): ใส่เฉพาะข้อกฎหมาย/ระเบียบ/หนังสือสั่งการที่ปรากฏชัดเจนในข้อความต้นเรื่องเท่านั้น พร้อมมาตรา/ข้อ — หากไม่มีในต้นเรื่องให้เว้นว่าง (None) ห้ามสร้างชื่อกฎหมาย มาตรา หรือข้อระเบียบขึ้นเอง ห้ามยกตัวอย่างเพิ่ม
   - memo_facts (ข้อเท็จจริง - ต้องมีทุกครั้ง): ผลการประสาน/ตรวจสอบ ข้อเท็จจริง และรายการคำขอแยกข้อ "๑. ..." "๒. ..." หรือ "1.1 ..."
   - memo_consideration (ข้อพิจารณาและเสนอแนะ - ต้องมีทุกครั้ง): การวิเคราะห์เหตุผลความจำเป็น ความเห็นของหน่วยงาน และข้อเสนอแนะแยกข้อ "๑. ..." สำหรับให้ผู้บังคับบัญชาพิจารณา
   - memo_request (ประโยคลงท้ายตามระดับชั้น - ต้องมีทุกครั้ง): ประโยคลงท้าย "จึงเรียนมาเพื่อ..." ตามระดับชั้นการเสนอ เช่น
     * เสนอ ปลัด (นำเรียนผู้ว่าฯ): "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร เพื่อโปรดพิจารณา..."
     * เสนอ ผอ.สำนัก (ลงนามหนังสือเรียนปลัด): "จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ"
     * เสนอ ผอ.กอง: "จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกอง...ลงนามในหนังสือที่แนบ"
   - memo_heading_style: "bma"
   - memo_hierarchy_level: "dept_to_perm_sec" | "div_to_dept" | "section_to_div" | "final_approval"
   และสำเนาสาระลง paragraph_reason / paragraph_details / paragraph_purpose ด้วยเสมอ"""


def _build_llm_prompt(ctx: SourceDocumentContext, doc_type: DocType, intent: DraftingIntent) -> str:
    """Prompt กลางที่ใช้กับ LLM ทุกค่าย"""
    return f"""คุณคือนักจัดการงานสารบรรณชำนาญการพิเศษ
จงร่างหนังสือราชการประเภท {doc_type.value} โดยมีเจตนาหลักคือ: {intent.value}
โดยอ้างอิงจากข้อมูลเอกสารต้นเรื่องต่อไปนี้:
- ไฟล์: {ctx.source_filename}
- หน่วยงานผู้ส่งเดิม: {ctx.source_dept}
- เลขที่เดิม: {ctx.source_doc_no}
- วันที่เดิม: {ctx.source_date}
- เรื่องเดิม: {ctx.source_subject}
- เนื้อหาต้นเรื่อง:
{ctx.raw_text[:4000]}

กฎเหล็ก:
1. วันที่: ห้ามมีคำว่า 'วันที่' นำหน้าเด็ดขาด
2. สำหรับหนังสือภายนอก: แบ่งเนื้อความ 3 ภาค (paragraph_reason, paragraph_details, paragraph_purpose)
3. {MEMO_DRAFTING_RULES}
4. ข้อเท็จจริงทั้งหมด (ชื่อบุคคล, หน่วยงาน, เลขที่หนังสือ, วันที่, จำนวนเงิน, ตัวเลข, กำหนดการ, เหตุผล, ข้อกฎหมาย, สิ่งที่ส่งมาด้วย) ต้องมาจากข้อความต้นเรื่อง ข้อมูลที่ผู้ใช้ให้ หรือโปรไฟล์หน่วยงานเท่านั้น — หากไม่มีข้อมูล ให้ใส่ placeholder รูปแบบ '[✏️ ระบุ...]' ห้ามแต่งข้อเท็จจริงที่ดูสมเหตุสมผลขึ้นเอง
5. ส่งออกเป็น JSON ตามโครงสร้าง GovDocumentSchema เท่านั้น
"""


def _sanitize_llm_draft(doc: GovDocumentSchema) -> GovDocumentSchema:
    """บังคับไม่ให้ AI สร้างเลขที่หนังสือ/วันที่/ข้อกฎหมายเอง — เว้นเลขที่ ใช้วันที่ปัจจุบัน และไม่ใส่ข้อกฎหมายที่ยังไม่ยืนยัน"""
    doc.doc_number = blank_doc_number(use_thai_numerals=doc.use_thai_numerals)
    doc.doc_date = format_thai_date(use_thai_numerals=doc.use_thai_numerals)
    doc.memo_law = None  # Step 0: ยังไม่มีกลไกยืนยันแหล่งข้อกฎหมาย — ห้ามใส่จาก LLM
    return doc


def draft_from_context_llm(ctx: SourceDocumentContext, 
                           doc_type: DocType = DocType.EXTERNAL,
                           intent: DraftingIntent = DraftingIntent.ACCEPT,
                           provider: str = "gemini",
                           model_name: Optional[str] = None,
                           api_key: Optional[str] = None,
                           secret: SecretLevel = SecretLevel.NORMAL,
                           allow_cloud: bool = True) -> GovDocumentSchema:
    """
    ร่างหนังสือราชการด้วย AI (Gemini หรือ OpenAI)
    พร้อมระบบสำรอง (Fallback) สู่ Rule-based เสมอหากไม่มี API key หรือเกิดข้อผิดพลาด

    secret: ชั้นความลับของเอกสาร; หากไม่ใช่ normal จะไม่อนุญาตให้ส่งไป AI ภายนอก
    allow_cloud: False = บังคับใช้เฉพาะ Rule-based/local (สำหรับโหมดข้อมูลอ่อนไหว)
    """
    # 0. FAIL-SAFE CHECK: ห้ามยกร่างหากการสกัดข้อความล้มเหลว หรือไม่มีข้อความ
    if getattr(ctx, "extraction_failed", False) or not (ctx.raw_text or "").strip():
        raise ValueError(
            "ไม่สามารถยกร่างหนังสือได้ เนื่องจากระบบไม่สามารถสกัดข้อความจากเอกสารต้นเรื่องได้ "
            "(กรุณาระบุ GEMINI_API_KEY หรือเปิดใช้งาน Local Docker OCR หรือกรอกข้อความด้วยตนเอง)"
        )

    if not allow_cloud:
        raise CloudAIBlocked(
            "โหมดข้อมูลอ่อนไหว: ระบบไม่อนุญาตให้ส่งเนื้อหาไปยัง AI ภายนอก "
            "กรุณาใช้ Rule-based หรือ Template ภายในเครื่อง"
        )
    assert_cloud_ai_allowed(secret)

    prov = (provider or "gemini").lower()
    if prov == "openai":
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            return draft_from_context_rule_based(ctx, doc_type=doc_type, intent=intent)
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            m = model_name or "gpt-4o-mini"
            prompt = _build_llm_prompt(ctx, doc_type, intent)
            res = client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": "You are a professional Thai Government Document Assistant. Always return valid JSON conforming to GovDocumentSchema."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            return _sanitize_llm_draft(GovDocumentSchema.model_validate_json(res.choices[0].message.content))
        except Exception as e:
            print(f"OpenAI drafting failed, falling back to rule-based: {e}")
            return draft_from_context_rule_based(ctx, doc_type=doc_type, intent=intent)
    else:
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            return draft_from_context_rule_based(ctx, doc_type=doc_type, intent=intent)
        try:
            from google import genai
            client = genai.Client(api_key=key)
            m = model_name or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
            prompt = _build_llm_prompt(ctx, doc_type, intent)
            res = client.models.generate_content(
                model=m,
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': GovDocumentSchema,
                }
            )
            return _sanitize_llm_draft(GovDocumentSchema.model_validate_json(res.text))
        except Exception as e:
            print(f"Gemini drafting failed, falling back to rule-based: {e}")
            return draft_from_context_rule_based(ctx, doc_type=doc_type, intent=intent)


def copilot_refine_text(text: str, command: str) -> str:
    """ผู้ช่วย AI Copilot สำหรับขัดเกลาข้อความเฉพาะจุด"""
    if command == "formal":
        text = text.replace("เยอะ", "จำนวนมาก").replace("ขอให้", "ขอความอนุเคราะห์ให้")
        text = text.replace("ช่วย", "โปรดให้ความอนุเคราะห์").replace("เสร็จแล้ว", "ดำเนินการเรียบร้อยแล้ว")
        text = text.replace("ต้องการ", "มีความประสงค์").replace("คุยกัน", "หารือร่วมกัน")
        return text
    elif command == "concise":
        sentences = [s.strip() for s in text.split(" ") if s.strip()]
        return " ".join(sentences[:len(sentences)//2 + 1])
    elif command == "to_thai_nums":
        return to_thai_numerals(text)
    elif command == "to_arabic_nums":
        return to_arabic_numerals(text)
    return text

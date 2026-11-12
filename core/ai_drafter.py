"""
ai_drafter.py — สมองกลยกร่างหนังสือราชการไทย (AI Drafting & Reasoning Engine)
อ้างอิง Prompt Engineering จาก Boom-Vitt/claude-thai-skills และระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
"""

import os
import re
from enum import Enum
from typing import Optional, List

from core.models import GovDocumentSchema, SourceDocumentContext, DocType, UrgencyLevel, SecretLevel, MemoHierarchyLevel
from core.profile_manager import get_user_profile
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
                                  contact_tel: Optional[str] = None) -> GovDocumentSchema:
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

    origin_code = user_prof.doc_origin_code or "กท ๐๒๐๔/"
    doc_no = f"{origin_code}ว ๑๒๓" if doc_type == DocType.EXTERNAL else "๑๒๓/๒๕๖๙"
    doc_date = "๑๕ มีนาคม ๒๕๖๙"
    
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
    if intent == DraftingIntent.ACCEPT:
        paragraph_details = (
            f"{my_dept} ได้พิจารณาข้อเท็จจริงและรายละเอียดดังกล่าวแล้ว "
            f"มีความยินดีและไม่ขัดข้องในการให้ความร่วมมือและสนับสนุนการดำเนินงานดังกล่าว "
            f"โดยได้มอบหมายให้เจ้าหน้าที่ผู้รับผิดชอบประสานงานในรายละเอียดต่อไป"
        )
        paragraph_purpose = "จึงเรียนมาเพื่อโปรดทราบ และได้มอบหมายให้ผู้ประสานงานดำเนินการในส่วนที่เกี่ยวข้องต่อไป"

    elif intent == DraftingIntent.DECLINE:
        paragraph_details = (
            f"{my_dept} ได้พิจารณาข้อเท็จจริงแล้ว มีความจำเป็นต้องขออภัยที่ไม่สามารถให้การสนับสนุนตามที่แจ้งความประสงค์ได้ "
            f"เนื่องจากในช่วงเวลาดังกล่าวหน่วยงานมีภารกิจสำคัญตามแผนงานเร่งด่วนที่ได้กำหนดไว้ล่วงหน้าแล้ว"
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
            f"ในการนี้ จากการตรวจสอบข้อเท็จจริงพบว่า คำขอหรือประเด็นตามหนังสือข้างต้นมีรายละเอียดที่เป็นประโยชน์ต่อทางราชการ "
            f"จึงเห็นควรดำเนินการตามแนวทางของเรื่องเดิม เพื่อให้การปฏิบัติงานเป็นไปด้วยความเรียบร้อย ถูกต้องตามระเบียบ"
        )
        paragraph_purpose = (
            "ข้อพิจารณาและข้อเสนอ เห็นควรดำเนินการเรื่องดังกล่าวเข้ากับเรื่องเดิม และแจ้งผลการพิจารณาให้ทราบต่อไป จึงเรียนมาเพื่อโปรดพิจารณา"
        )

    else:  # PROPOSAL (บันทึกข้อความ)
        paragraph_details = (
            f"ฝ่ายพัฒนาศักยภาพภาครัฐ ได้พิจารณาแล้วเห็นว่า โครงการดังกล่าวมีความจำเป็นและเป็นประโยชน์อย่างยิ่ง "
            f"ในการยกระดับทักษะบุคลากรภาครัฐให้สอดคล้องกับระเบียบงานสารบรรณดิจิทัล "
            f"โดยมีงบประมาณดำเนินการตามแผนงานที่ได้รับอนุมัติไว้แล้ว"
        )
        paragraph_purpose = "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติการดำเนินงานและงบประมาณดังกล่าวต่อไป"

    # คำนวณฟิลด์เฉพาะสำหรับบันทึกข้อความ ๔ หัวข้อย่อยมาตรฐาน และประโยคลงท้ายตามระดับชั้น
    memo_intro = paragraph_reason if doc_type == DocType.INTERNAL else None
    if doc_type == DocType.INTERNAL and getattr(ctx, "source_case", None):
        synth = ctx.source_case.synthesize_memo_intro()
        if synth and len(synth) > 20:
            memo_intro = synth

    memo_facts = paragraph_details if doc_type == DocType.INTERNAL else None
    if doc_type == DocType.INTERNAL and getattr(ctx, "source_case", None) and ctx.source_case.requested_items:
        items_bullets = "\n".join([f"๑.{i} {req}" for i, req in enumerate(ctx.source_case.requested_items, 1)])
        if memo_facts:
            memo_facts = f"{memo_facts}\nโดยมีประเด็นคำขอดังนี้\n{items_bullets}"
        else:
            memo_facts = f"ในการนี้ จากการตรวจสอบข้อเท็จจริง มีประเด็นคำขอดังนี้\n{items_bullets}"

    memo_law = None
    memo_hierarchy_level = MemoHierarchyLevel.DEPT_TO_PERM_SEC
    memo_request = None
    if doc_type == DocType.INTERNAL:
        case_reqs = " ".join(ctx.source_case.requested_items) if getattr(ctx, "source_case", None) else ""
        text_for_law = f"{subject} {case_reqs}"
        if any(w in text_for_law for w in ["พัสดุ", "จัดซื้อ", "จัดจ้าง", "ครุภัณฑ์"]):
            memo_law = "ตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. ๒๕๖๐ และระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. ๒๕๖๐ กำหนดให้หน่วยงานของรัฐจัดทำรายงานขอซื้อขอจ้างเพื่อเสนอหัวหน้าหน่วยงานของรัฐให้ความเห็นชอบก่อนดำเนินการ"
        elif any(w in text_for_law for w in ["เจ้าภาพ", "ตราสัญลักษณ์", "โลโก้", "สถานที่"]):
            # อ้างอิงเฉพาะกฎหมาย/หนังสือสั่งการที่มีอยู่จริง (ตามบันทึกเสนอพิจารณาของ กทม.) — ผู้ใช้ต้องตรวจทานอีกครั้ง
            memo_law = (
                "๑. พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒\n"
                "มาตรา ๖ ห้ามมิให้บุคคลใดใช้เครื่องหมายราชการเว้นแต่หน่วยราชการที่กำหนดเครื่องหมายนั้นจะได้อนุญาต\n"
                "๒. หนังสือกรุงเทพมหานคร ที่ กท ๑๓๐๕/๑๖๔ ลงวันที่ ๒๑ กุมภาพันธ์ ๒๕๕๕ เรื่อง การใช้ตราเครื่องหมายประจำกรุงเทพมหานคร\n"
                "ข้อ ๒ การใช้ตราเครื่องหมายประจำกรุงเทพมหานคร กรณีอื่น ๆ ต้องได้รับอนุญาตจากผู้ว่าราชการกรุงเทพมหานคร"
            )
        else:
            # ไม่ทราบข้อกฎหมายที่เกี่ยวข้อง — ปล่อยว่างเพื่อไม่ให้ระบบแต่งข้อกฎหมายขึ้นเอง
            memo_law = None

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
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number=doc_no,
        dept_name=my_dept,
        doc_date=doc_date,
        subject=subject,
        salutation=salutation,
        references=references if references else None,
        attachments=["สรุปผลการพิจารณา จำนวน ๑ ฉบับ"] if (doc_type == DocType.EXTERNAL or intent == DraftingIntent.MEMO_REVIEW) else None,
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
   - memo_law (ข้อกฎหมาย - ถ้ามี): อ้างเฉพาะกฎหมาย ระเบียบ หรือหนังสือสั่งการที่เกี่ยวข้อง (เช่น พ.ร.บ. เครื่องหมายราชการ, ระเบียบสถานที่, พ.ร.บ. จัดซื้อจัดจ้าง) พร้อมมาตรา/ข้อ — หากไม่มีเรื่องที่ต้องอ้างกฎหมายเฉพาะ ให้เว้นว่าง ห้ามแต่งกฎหมายขึ้นเอง
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
4. ส่งออกเป็น JSON ตามโครงสร้าง GovDocumentSchema เท่านั้น
"""


def draft_from_context_llm(ctx: SourceDocumentContext, 
                           doc_type: DocType = DocType.EXTERNAL,
                           intent: DraftingIntent = DraftingIntent.ACCEPT,
                           provider: str = "gemini",
                           model_name: Optional[str] = None,
                           api_key: Optional[str] = None) -> GovDocumentSchema:
    """
    ร่างหนังสือราชการด้วย AI (Gemini หรือ OpenAI)
    พร้อมระบบสำรอง (Fallback) สู่ Rule-based เสมอหากไม่มี API key หรือเกิดข้อผิดพลาด
    """
    # 0. FAIL-SAFE CHECK: ห้ามยกร่างหากการสกัดข้อความล้มเหลว หรือไม่มีข้อความ
    if getattr(ctx, "extraction_failed", False) or not (ctx.raw_text or "").strip():
        raise ValueError(
            "ไม่สามารถยกร่างหนังสือได้ เนื่องจากระบบไม่สามารถสกัดข้อความจากเอกสารต้นเรื่องได้ "
            "(กรุณาระบุ GEMINI_API_KEY หรือเปิดใช้งาน Local Docker OCR หรือกรอกข้อความด้วยตนเอง)"
        )
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
            return GovDocumentSchema.model_validate_json(res.choices[0].message.content)
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
            m = model_name or "gemini-2.5-flash"
            prompt = _build_llm_prompt(ctx, doc_type, intent)
            res = client.models.generate_content(
                model=m,
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': GovDocumentSchema,
                }
            )
            return GovDocumentSchema.model_validate_json(res.text)
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

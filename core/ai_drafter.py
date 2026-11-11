"""
ai_drafter.py — สมองกลยกร่างหนังสือราชการไทย (AI Drafting & Reasoning Engine)
อ้างอิง Prompt Engineering จาก Boom-Vitt/claude-thai-skills และระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
"""

import os
from enum import Enum
from typing import Optional, List

from core.models import GovDocumentSchema, SourceDocumentContext, DocType, UrgencyLevel, SecretLevel
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
                                  my_dept: str = "สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน)",
                                  my_signatory: str = "(นางสาวสุดา พัฒนารัฐ)",
                                  my_position: str = "ผู้อำนวยการสำนักงานพัฒนารัฐบาลดิจิทัล",
                                  contact_dept: str = "ฝ่ายพัฒนาศักยภาพภาครัฐ",
                                  contact_tel: str = "๐ ๒๖๑๒ ๖๐๐๐ ต่อ ๑๒๓๔") -> GovDocumentSchema:
    """
    สร้างร่างหนังสือราชการตามบริบทต้นเรื่องและเจตนา (Intent-aware Drafting)
    """
    doc_no = "ดพร ๐๑๐๒/ว ๑๒๓" if doc_type == DocType.EXTERNAL else "๑๒๓/๒๕๖๙"
    doc_date = "๑๕ มีนาคม ๒๕๖๙"
    
    # 1. การกำหนดเรื่อง (Subject)
    orig_subject = ctx.source_subject or ctx.source_filename.replace('.pdf', '').replace('.docx', '')
    if doc_type == DocType.INTERNAL:
        if intent == DraftingIntent.MEMO_REVIEW:
            subject = f"รายงานการพิจารณาหนังสือ{orig_subject}"
        else:
            subject = f"ขออนุมัติดำเนินการเกี่ยวกับ{orig_subject}"
        salutation = "เรียน  [✏️ ระบุตำแหน่งผู้บังคับบัญชา]"
    else:
        if intent == DraftingIntent.ACCEPT:
            subject = f"การให้ความอนุเคราะห์{orig_subject.replace('ขอความอนุเคราะห์', '').replace('การขอ', '')}"
        elif intent == DraftingIntent.DECLINE:
            subject = f"แจ้งข้อขัดข้องเกี่ยวกับ{orig_subject}"
        elif intent == DraftingIntent.FORWARD:
            subject = f"ส่งเรื่อง{orig_subject} เพื่อโปรดพิจารณา"
        elif intent == DraftingIntent.MEMO_REVIEW:
            subject = f"รายงานผลการพิจารณาเรื่อง{orig_subject}"
        else:
            subject = orig_subject

        if ctx.source_dept and ctx.source_dept != "หน่วยงานต้นเรื่อง":
            salutation = f"เรียน  {ctx.source_dept}"
        else:
            salutation = "เรียน  [✏️ ระบุตำแหน่งผู้รับ]"

    # 2. การสร้างข้ออ้างถึง (References)
    references = []
    ref_desc = ""
    if ctx.source_doc_no or ctx.source_date:
        ref_text = f"หนังสือ{ctx.source_dept}"
        if ctx.source_doc_no:
            ref_text += f" ที่ {ctx.source_doc_no}"
        if ctx.source_date:
            ref_text += f" ลงวันที่ {ctx.source_date}"
        references.append(ref_text)
        ref_desc = "ที่อ้างถึง "
    elif ctx.source_filename:
        references.append(f"เอกสาร {ctx.source_filename}")

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
        closing="ขอแสดงความนับถือ" if doc_type == DocType.EXTERNAL else "",
        signatory_name=my_signatory,
        signatory_position=my_position,
        contact_dept=contact_dept,
        contact_tel=contact_tel,
        contact_fax="๐ ๒๖๑๒ ๖๐๐๑",
        contact_email="contact@dga.or.th"
    )


def draft_from_context_llm(ctx: SourceDocumentContext, 
                           doc_type: DocType = DocType.EXTERNAL,
                           intent: DraftingIntent = DraftingIntent.ACCEPT,
                           api_key: Optional[str] = None) -> GovDocumentSchema:
    """
    ร่างหนังสือราชการด้วย Multimodal LLM (Gemini 2.5 Flash)
    """
    gemini_key = api_key or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        return draft_from_context_rule_based(ctx, doc_type=doc_type, intent=intent)

    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        
        prompt = f"""คุณคือนักจัดการงานสารบรรณชำนาญการพิเศษ 
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
2. แบ่งเนื้อความ 3 ภาค (ภาคเหตุ, ภาคพิจารณา, ภาคประสงค์)
3. ส่งออกเป็น JSON ตามโครงสร้าง GovDocumentSchema
"""
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_schema': GovDocumentSchema,
            }
        )
        return GovDocumentSchema.model_validate_json(response.text)
    except Exception as e:
        print(f"LLM drafting failed, falling back to rule-based: {e}")
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

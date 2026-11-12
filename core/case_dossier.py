"""
case_dossier.py — ตัวแยกแยะและประมวลผลแฟ้มสำนวนเรื่องสารบรรณหลายฉบับ (Multi-Document Case Dossier)
รองรับกรณี ๑ แฟ้มประกอบด้วย หนังสือภายนอกเดิม + หนังสือฉบับใหม่ที่ส่งมาแทน + บันทึกเกษียนสั่งการตามลำดับชั้น (Chain-of-Command)
"""

import re
from typing import List, Optional, Union
from core.models import SourceCase, SourceItem, RoutingNote


def parse_case_dossier(raw_text_or_pages: Union[str, List[str]], filename: str = "") -> SourceCase:
    """
    วิเคราะห์เอกสารแบบทั้งสำนวนเรื่อง (Dossier)
    แยกแยะเอกสารย่อยในแฟ้ม (เช่น ฉบับลงวันที่ 16 ม.ค. vs ฉบับลงวันที่ 30 ม.ค.)
    และสกัดสายการบังคับบัญชา / บันทึกเกษียนสั่งการ (Routing Notes)
    """
    if isinstance(raw_text_or_pages, list):
        full_text = "\n--- [PAGE BREAK] ---\n".join(raw_text_or_pages)
        pages = raw_text_or_pages
    else:
        full_text = raw_text_or_pages or ""
        pages = [p for p in full_text.split("--- [PAGE BREAK] ---") if p.strip()] or [full_text]

    # 1. สกัดหัวข้อเรื่องหลักของแฟ้ม
    case_title = "สำนวนเรื่องราชการ"
    subj_match = re.search(r'เรื่อง\s+([^\n]+)', full_text)
    if subj_match:
        case_title = subj_match.group(1).strip()
    elif filename:
        clean_name = re.sub(r'\.(pdf|docx|txt|jpg|png)$', '', filename, flags=re.IGNORECASE)
        case_title = f"เรื่องตามเอกสาร {clean_name}"

    items: List[SourceItem] = []
    routing_notes: List[RoutingNote] = []
    deadlines: List[str] = []
    requested_items: List[str] = []

    # 2. ค้นหาเอกสารภายนอกย่อย (Incoming Letters)
    # ค้นหาเลขที่หนังสือหลัก
    doc_no_match = re.search(r'ที่\s+([ก-๙a-zA-Z\.\s\d\u0e50-\u0e59]+?/\s*[\d\u0e50-\u0e59]+)', full_text)
    doc_no = re.sub(r'\s+', '', doc_no_match.group(1)) if doc_no_match else None

    # วันที่ของหนังสือหลัก
    date_match = re.search(r'(?:วันที่|ลงวันที่)\s+((?:\d{1,2}|[\u0e50-\u0e59]{1,2})\s+(?:มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s+(?:\d{2,4}|[\u0e50-\u0e59]{2,4}))', full_text)
    doc_date = date_match.group(1).strip() if date_match else None

    # หน่วยงานผู้ส่ง
    sender_match = re.search(r'(?:^|\n)\s*(สมาคมกีฬา[^\n]+|สมาคม[^\n]+|บริษัท[^\n]+|กรม[^\n]+|สำนักงาน[^\n]+|กระทรวง[^\n]+)', full_text)
    sender = sender_match.group(1).strip() if sender_match else None

    # ตรวจสอบการยกเลิก/ส่งมาแทนหนังสือเดิม (เช่น "ยกเลิกหนังสือฉบับเดิม ที่ ... ลงวันที่ ...")
    old_match = re.search(r'(?:ยกเลิกหนังสือฉบับเดิม|ฉบับเดิม|แทนหนังสือเดิม)\s+ที่\s+([ก-๙a-zA-Z\.\s\d\u0e50-\u0e59]+?/\s*[\d\u0e50-\u0e59]+)(?:\s+ลงวันที่\s+([^\n]+?))?(?:\s+เนื่องจาก|\s*$|\n)', full_text)
    old_item_id = None
    if old_match:
        old_no = re.sub(r'\s+', '', old_match.group(1))
        old_date = old_match.group(2).strip() if old_match.group(2) else None
        old_item_id = "item-old"
        items.append(SourceItem(
            item_id=old_item_id,
            title=case_title,
            doc_no=old_no,
            doc_date=old_date,
            sender=sender,
            page_start=1,
            page_end=len(pages),
            doc_type="external"
        ))

    primary_item = SourceItem(
        item_id="item-primary",
        title=case_title,
        doc_no=doc_no,
        doc_date=doc_date,
        sender=sender,
        page_start=1,
        page_end=len(pages),
        doc_type="external",
        replaces_item_id=old_item_id
    )
    items.insert(0, primary_item)

    # 3. สกัดบันทึกเกษียนสั่งการ (Routing Notes / Chain of Command)
    for p in pages:
        if any(kw in p for kw in ["เห็นควร", "มอบ", "เพื่อโปรดพิจารณา", "โปรดพิจารณา", "เกษียนสั่งการ"]):
            lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
            for i, line in enumerate(lines):
                if line.startswith("เรียน ") or line.startswith("กราบเรียน "):
                    target = line.replace("เรียน ", "").replace("กราบเรียน ", "").strip()
                    body_lines = []
                    author = "ผู้บังคับบัญชา"
                    date_val = None
                    pos_val = None

                    for j in range(i + 1, min(i + 8, len(lines))):
                        sub_line = lines[j]
                        if any(kw in sub_line for kw in ["เห็นควร", "มอบ", "ประสาน", "อนุมัติ", "ดำเนินการ", "พิจารณา"]):
                            body_lines.append(sub_line)
                        if any(kw in sub_line for kw in ["ผอ.", "ผู้อำนวยการ", "ปลัด", "หัวหน้า"]):
                            pos_val = sub_line
                        if sub_line.startswith("(ลงชื่อ)") or sub_line.startswith("ลงชื่อ"):
                            author = sub_line.replace("(ลงชื่อ)", "").replace("ลงชื่อ", "").strip()
                        d_match = re.search(r'((?:\d{1,2}|[\u0e50-\u0e59]{1,2})\s+[ก-๙\.]+\s+(?:\d{2,4}|[\u0e50-\u0e59]{2,4}))', sub_line)
                        if d_match:
                            date_val = d_match.group(1)

                    if body_lines:
                        routing_notes.append(RoutingNote(
                            author=pos_val or author,
                            position=pos_val,
                            target=f"เรียน {target}",
                            order_text=" ".join(body_lines),
                            order_date=date_val,
                            signature_present=True
                        ))

    # 4. สกัดคำขอและประเด็น (Requested items)
    req_keywords = [
        "ขอความอนุเคราะห์", "ขอความร่วมมือ", "ขอรับการสนับสนุน", 
        "ขอใช้สถานที่", "ขอใช้ตราสัญลักษณ์", "ขอร่วมเป็นเจ้าภาพ",
        "ขอสนับสนุนงบประมาณ", "ขอเชิญเป็นเกียรติ", "ขออนุมัติ"
    ]
    for kw in req_keywords:
        if kw in full_text:
            match = re.search(rf'({kw}[^\n\.\;]{{5,80}})', full_text)
            if match:
                req_text = match.group(1).strip()
                if req_text not in requested_items:
                    requested_items.append(req_text)

    # 5. สกัดกำหนดการ/วันครบกำหนด (Deadlines)
    dl_matches = re.findall(r'(?:ระหว่างวันที่|ในวันที่|ตั้งแต่วันที่|ภายในวันที่)\s+(\d{1,2}(?:\s*-\s*\d{1,2})?\s+[ก-๙\.]+\s+\d{4})', full_text)
    for dl in dl_matches:
        if dl not in deadlines:
            deadlines.append(dl)

    return SourceCase(
        case_title=case_title,
        items=items,
        routing_notes=routing_notes,
        deadlines=deadlines,
        requested_items=requested_items,
        raw_text=full_text
    )
